"""Oturum katmanı: oda kurma, katılma, el sıkışma ve grup anahtarı dağıtımı.

Akış (relay modu — P2P aynı zarfları UDP üzerinden taşır):
  Kurucu : broker'a bağlanır, rastgele ODA KODU üretir, topic dinler.
  Katılan: kod + ECDH pub -> HELLO
  Kurucu : host pub + ECIES ile sarılı "host onayı" -> HELLO_BACK
           (böylece katılan, host'un gerçekten o pub'ın sahibi olduğunu
            ECDH üzerinden kanıtlar; MITM SAS ile kontrol edilir)
  Katılan: şifreli ACK -> HELLO_BACK_ACK
  Kurucu : grup anahtarını herkese ECIES ile sarar -> MEMBER_JOIN
  Herkes : DATA zarfları (grup anahtarıyla AES-256-GCM)
"""
from __future__ import annotations

import json
import logging
import os
import queue
import random
import secrets
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, crypto, honeypot, messages
from .security import KeyedRateLimiter, RateLimiter
from .signaling import SignalingChannel, topic_for

logger = logging.getLogger("secretchat.room")

StatusCb = Optional[Callable[[str], None]]
LogCb = Optional[Callable[[str], None]]

# ---------------------------------------------------------------- yardımcılar


def generate_room_code() -> str:
    """Kopyalanabilir kısa oda kodu üret (örn. 3K7QX)."""
    alphabet = config.ROOM_CODE_ALPHABET
    return "".join(secrets.choice(alphabet) for _ in range(config.ROOM_CODE_LENGTH))


def sas_of(pub_a: bytes, pub_b: bytes) -> str:
    """İki tarafın gördüğü ortak doğrulama kodu."""
    return crypto.compute_sas(pub_a, pub_b)


# ---------------------------------------------------------------- temel sınıf


class _Base:
    """Kurucu ve katılanın ortak davranışları."""

    def __init__(self, nickname: str, status_cb: StatusCb = None,
                 log_cb: LogCb = None):
        self.nickname = nickname
        self.status_cb = status_cb
        self.log_cb = log_cb
        self.id_priv, self.id_pub = crypto.generate_signing_keypair()
        self.channel: Optional[SignalingChannel] = None
        self.running = False
        self.lock = threading.RLock()
        self.rate_limiter = RateLimiter()
        # -- gelen trafik denetimi (inbound flood / DoS koruması) --
        self._hello_limiter = RateLimiter(config.INBOUND_BURST, config.INBOUND_RATE)
        self._peer_limiter = KeyedRateLimiter(config.INBOUND_BURST, config.INBOUND_RATE,
                                              max_keys=200)
        # -- tekrar-savunması: mid/nonce -> zaman damgası (sınırlı önbellek) --
        self._seen_tokens: Dict[str, float] = {}
        self._tokens_lock = threading.Lock()
        self.is_honeypot = False  # tuzak (decoy) oda bayrağı
        self.on_message: Optional[Callable[[str, str, bool], None]] = None
        self.on_image: Optional[Callable[[str, str, str], None]] = None  # sender, b64, caption
        self.on_edit: Optional[Callable[[str, str, str], None]] = None  # sender, msg_id, new_text
        self.on_delete: Optional[Callable[[str, str], None]] = None  # sender, msg_id
        self.on_peer_left: Optional[Callable[[str], None]] = None
        self.on_sas: Optional[Callable[[str], None]] = None
        self.members: Dict[str, Dict[str, Any]] = {}

    # ----- durum bildirimi

    def _status(self, text: str) -> None:
        if self.status_cb:
            try:
                self.status_cb(text)
            except Exception:
                pass

    def _log(self, text: str) -> None:
        if self.log_cb:
            try:
                self.log_cb(text)
            except Exception:
                pass

    # ----- tekrar / tazelik savunması

    def _is_duplicate(self, prefix: str, token: Any) -> bool:
        """mid/nonce tekrar mı? (TTL penceresi + MAX_SEEN_TOKENS boyut tavanı)."""
        if token is None:
            return False
        key = prefix + str(token)
        now = time.time()
        with self._tokens_lock:
            if key in self._seen_tokens:
                return True
            self._seen_tokens[key] = now
            if len(self._seen_tokens) > config.MAX_SEEN_TOKENS:
                # en eski ~%25'ini ayıkla — bellek şişmesi (DoS) engeli
                oldest = sorted(self._seen_tokens.items(), key=lambda kv: kv[1])
                for k, _ in oldest[: max(1, len(oldest) // 4)]:
                    del self._seen_tokens[k]
            return False

    @staticmethod
    def _ts_fresh(ts: Any) -> bool:
        """Zaman damgası MAX_CLOCK_SKEW penceresinde mi? (replay koruması)"""
        try:
            return abs(time.time() - float(ts)) <= config.MAX_CLOCK_SKEW
        except (TypeError, ValueError):
            return False

    # ----- kanal

    def _open_channel(self, topics: Tuple[str, ...]) -> bool:
        self.channel = SignalingChannel(status_cb=self._status, topics=topics)
        # Eğer ön-bağlantı probe'u bir kazanan broker belirlemiştik, iletelim.
        # SignalingChannel.start() bunu rotasyonun başına alır → soğuk başlatma bypass.
        preferred = getattr(self, "_preferred_broker", None)
        if preferred is not None:
            self.channel._preferred_broker = preferred
        self.channel.on_message = self._on_wire
        return self.channel.start()

    def stop(self) -> None:
        """Oturumu ve kanalı kapat."""
        self.running = False
        if self.channel is not None:
            try:
                self.channel.stop()
            except Exception:
                pass
            self.channel = None

    def _on_wire(self, topic: str, payload: bytes) -> None:
        """Broker'dan gelen ham zarfı ayrıştırıp işleyiciye devret."""
        try:
            env = messages.decode_envelope(payload)
        except ValueError:
            return
        try:
            self.handle_envelope(env, topic)
        except Exception as exc:  # bozuk paket oturumu düşürmesin
            self._log(f"[hata] zarf işlenemedi: {exc}")

    def handle_envelope(self, env: Dict[str, Any], topic: str) -> None:
        raise NotImplementedError

    # ----- grup trafiği

    def _send_data(self, payload_json: str, key: bytes) -> None:
        """Grup anahtarıyla şifreleyip Ed25519 ile imzalayarak DATA yayınla.

        İmza (sid = id_pub): alıcılar gönderenin gerçekten o kimlik sahibi
        olduğunu kanıtlar — sahte "sistem" mesajı ve takma ad taklidi (nick
        spoofing) imzasız/kötü imzalı zarflar reddedilerek engellenir.
        """
        if key is None:
            return
        raw = payload_json.encode("utf-8")
        blob = crypto.aesgcm_encrypt(key, raw)
        env = messages.new_envelope(
            messages.DATA, blob=crypto.b64e(blob),
            sid=crypto.b64e(self.id_pub),
            sig=crypto.b64e(crypto.sign(self.id_priv, raw)))
        self._publish(env)

    def _publish(self, env: Dict[str, Any]) -> None:
        if self.channel is not None:
            self.channel.publish(self.data_topic, env)

    def send_image(self, image_b64: str, caption: str = "",
                   w: int = 0, h: int = 0):
        """Fotoğrafı grup anahtarıyla yayınla (Host ve Client ortak).

        ``image_b64``: ``media.prepare_image`` çıktısı olmalıdır.
        Başarıda mesaj kimliği (``msg_id``) döner, başarısızlıkta ``False``.
        Dönüşün truthy olması eski ``if sent:`` kontrolleriyle uyumludur.
        """
        room_key = getattr(self, "room_key", None)
        if room_key is None:
            self._status("Henüz bağlı değilsin")
            return False
        try:
            payload = messages.make_image_payload(
                self.nickname, image_b64, caption, w, h)
        except ValueError as exc:
            self._status(str(exc))
            return False
        if not self.rate_limiter.allow():
            self._status("Çok hızlı mesaj gönderiyorsunuz (Rate limit), lütfen bekleyin.")
            return False
        self._send_data(payload, room_key)
        try:
            return json.loads(payload).get("msg_id") or True
        except Exception:
            return True

    def send_edit(self, msg_id: str, new_text: str) -> bool:
        """Kendi mesajında düzenleme yayınla (yalnızca sahibi çağırmalı)."""
        room_key = getattr(self, "room_key", None)
        if room_key is None:
            self._status("Henüz bağlı değilsin")
            return False
        try:
            payload = messages.make_edit_payload(self.nickname, msg_id, new_text)
        except ValueError as exc:
            self._status(str(exc))
            return False
        if not self.rate_limiter.allow():
            self._status("Çok hızlı mesaj gönderiyorsunuz (Rate limit), lütfen bekleyin.")
            return False
        self._send_data(payload, room_key)
        return True

    def send_delete(self, msg_id: str) -> bool:
        """Kendi mesajında silme yayınla (yalnızca sahibi çağırmalı)."""
        room_key = getattr(self, "room_key", None)
        if room_key is None:
            self._status("Henüz bağlı değilsin")
            return False
        if not msg_id:
            return False
        if not self.rate_limiter.allow():
            self._status("Çok hızlı mesaj gönderiyorsunuz (Rate limit), lütfen bekleyin.")
            return False
        try:
            payload = messages.make_delete_payload(self.nickname, msg_id)
        except ValueError as exc:
            self._status(str(exc))
            return False
        self._send_data(payload, room_key)
        return True

    def _emit_group_payload(self, payload: messages.ChatPayload) -> None:
        """Çözülmüş grup yükünü doğru callback'e yönlendir.

        Metin → ``on_message``, fotoğraf → ``on_image`` (yoksa metin
        yedeği ``"[fotoğraf] <açıklama>"`` olarak ``on_message``'e düşer),
        düzenleme → ``on_edit``, silme → ``on_delete``.

        ``on_message``/``on_image`` eski 3-arg imzayla da çağrılabilir:
        önce ``msg_id``'li 4-arg denenir, ``TypeError``'da 3-arg'a düşülür.
        Böylece eski testler ve harici dinleyiciler kırılmaz.
        """
        try:
            kind = payload.kind
            if kind == messages.INNER_IMAGE:
                mid = payload.msg_id or ""
                if self.on_image is not None:
                    try:
                        self.on_image(payload.sender, payload.image,
                                      payload.caption or "", mid)
                    except TypeError:
                        self.on_image(payload.sender, payload.image,
                                      payload.caption or "")
                elif self.on_message is not None:
                    fallback = ("[fotoğraf]" +
                                (f" {payload.caption}" if payload.caption else ""))
                    self._call_message(payload.sender, fallback, False, mid)
            elif kind == messages.INNER_EDIT:
                if self.on_edit is not None:
                    self.on_edit(payload.sender, payload.msg_id or "",
                                 payload.text or "")
                elif self.on_message is not None:
                    self._call_message(payload.sender, payload.text or "",
                                       False, payload.msg_id or "")
            elif kind == messages.INNER_DELETE:
                if self.on_delete is not None:
                    self.on_delete(payload.sender, payload.msg_id or "")
            elif self.on_message is not None:
                is_system = payload.sender == "sistem"
                text = payload.text
                self._call_message(payload.sender, text, is_system,
                                   payload.msg_id or "")
        except Exception:
            logger.debug("grup yükü callback hatası", exc_info=True)

    def _call_message(self, sender: str, text: str, system: bool,
                      msg_id: str = "") -> None:
        """``on_message``'i msg_id uyumlu çağır (eski 3-arg'e geri düşer)."""
        cb = self.on_message
        if cb is None:
            return
        try:
            cb(sender, text, system, msg_id)
        except TypeError:
            cb(sender, text, system)

    def _decrypt_data(self, env: Dict[str, Any], key: bytes
                      ) -> Optional[Tuple[messages.ChatPayload, bytes]]:
        """DATA zarfını çöz + Ed25519 imzasını doğrula.

        Dönüş: (payload, sid) — sid, imzalayanın id_pub'ıdır; çağıran taraf
        göndereni üye listesi / host_pub ile karşılaştırır (kimlik bağlama).
        Anahtarı olmayan, imzasız veya yanlış imzalı zarflar kesin reddedilir.
        """
        if key is None:
            return None
        try:
            blob = crypto.b64d(env["blob"])
            plain = crypto.aesgcm_decrypt(key, blob)
            sid = crypto.b64d(env["sid"])
            sig = crypto.b64d(env["sig"])
        except Exception:
            return None
        if not crypto.verify(sid, plain, sig):
            logger.warning("DATA imzası doğrulanamadı — zarf düşürüldü")
            return None
        try:
            data = json.loads(plain.decode("utf-8"))
            payload = messages.parse_chat_payload(data)
        except Exception:
            return None
        # gelen metni de temizle (uzunluk / kontrol karakteri savunması)
        if payload.kind == messages.INNER_CHAT:
            payload.text = messages.sanitize_text(payload.text)
        elif payload.kind == messages.INNER_EDIT:
            if not payload.msg_id:
                return None
            payload.text = messages.sanitize_text(payload.text)
            if not payload.text:
                return None
        elif payload.kind == messages.INNER_DELETE:
            if not payload.msg_id:
                return None
        elif payload.kind == messages.INNER_IMAGE:
            ok, _ = messages.validate_image_b64(payload.image)
            if not ok:
                return None
            payload.caption = messages.sanitize_text(
                payload.caption or "")[:config.IMAGE_CAPTION_MAX]
        return payload, sid


# ---------------------------------------------------------------- KURUCU (host)


class Host(_Base):
    """Oda kurucusu: kod üretir, el sıkışır, grup anahtarını dağıtır."""

    def __init__(self, nickname: str, status_cb: StatusCb = None,
                 log_cb: LogCb = None, room_code: Optional[str] = None):
        super().__init__(nickname, status_cb, log_cb)
        if room_code is not None:
            ok, code_or_reason = messages.validate_room_code(room_code)
            if not ok:
                raise ValueError(code_or_reason)
            self.room_code = code_or_reason
        else:
            self.room_code = generate_room_code()
        self.data_topic = topic_for(self.room_code, "data")
        self.ctrl_topic = topic_for(self.room_code, "ctrl")
        self.eph_priv, self.eph_pub = crypto.generate_ecdh_keypair()
        # KRITİK DÜZELTME: oda anahtarı oda kodundan TÜRETİLMEZ.
        # Kod, topic adında broker'a açık olduğu için (sc/v3/CODE/...) koddan
        # türetilen herhangi bir anahtar broker'ın tüm grup trafiğini
        # çözebilmesi anlamına gelirdi (E2EE bypass). Anahtar artık rastgele
        # üretilir ve yalnızca ECIES ile üyelere dağıtılır.
        self.room_key = secrets.token_bytes(32)
        self.session_keys: Dict[str, bytes] = {}       # nickname -> AES anahtarı
        self.member_pubs: Dict[str, bytes] = {}        # nickname -> id_pub
        self.member_wraps: Dict[str, bytes] = {}       # nickname -> grup anahtarı sarmalı
        self.pending_sas: Dict[str, str] = {}
        self._reject_count = 0

    # ----- başlatma

    def start(self) -> bool:
        """Broker'a bağlan ve odayı duyur."""
        if not self._open_channel((self.data_topic, self.ctrl_topic)):
            self._status("Broker'a ulaşılamadı (internet yok?)")
            return False
        self.running = True
        self._status("Oda hazır")
        threading.Thread(target=self._announce_loop, daemon=True).start()
        return True

    def _announce_loop(self) -> None:
        """Katılanlar için topic dinleme yapılır; duyuru zarfları yayımlanır."""
        logger.debug("announce_loop başladı")
        try:
            while self.running:
                try:
                    env = messages.new_envelope(
                        messages.HELLO_BACK,  # duyuru tipi: "oda açık"
                        room=self.room_code,
                        host=self.nickname,
                        eph_pub=crypto.b64e(self.eph_pub),
                        id_pub=crypto.b64e(self.id_pub),
                        announce=True,
                    )
                    self._publish(env)
                except Exception as exc:
                    logger.error("announce_loop iterasyon hatası: %s", exc, exc_info=True)
                time.sleep(config.ANNOUNCE_POLL)
        except Exception as exc:
            logger.critical("announce_loop beklenmedik hata — thread sonlandı: %s", exc, exc_info=True)
        finally:
            logger.debug("announce_loop bitti (running=%s)", self.running)

    # ----- el sıkışma

    def handle_envelope(self, env: Dict[str, Any], topic: str) -> None:
        kind = env.get("t")

        # Kendi duyurularını yut (mid tekrar savunması — sınırlı önbellek).
        if self._is_duplicate("m:", env.get("mid")):
            return

        if kind == messages.HELLO and env.get("announce") is None:
            self._on_hello(env)
        elif kind == messages.HELLO_BACK_ACK:
            self._on_hb_ack(env)
        elif kind == messages.DATA:
            self._on_data(env)
        elif kind == messages.BYE:
            self._on_bye(env)

    def _reject_hello(self, env: Dict[str, Any], reason: str, code: str) -> None:
        """Katılımı reddet (kanal yoksa sessizce geç)."""
        self._reject_count += 1
        reject = messages.new_envelope(
            messages.REJECT,
            to=env.get("mid"),
            reason=reason,
            code=code,
            reply_to=env.get("mid"),
        )
        if self.channel is not None:
            self.channel.publish(self.ctrl_topic, reject)

    def _on_hello(self, env: Dict[str, Any]) -> None:
        """Katılanın HELLO zarfı: Validasyon, tekil kullanıcı adı ve çoklu katılım denetimi."""
        # 0) Gelen sel kontrolü (inbound flood / DoS): ağır iş öncesi kota
        if not self._hello_limiter.allow():
            logger.warning("HELLO sel baskısı — zarf düşürüldü")
            return

        raw_nick = str(env.get("nick", ""))
        valid, nick_or_reason = messages.validate_nickname(raw_nick)
        if not valid:
            logger.warning("Geçersiz takma ad: %s (%s)", raw_nick, nick_or_reason)
            self._reject_hello(env, nick_or_reason, messages.REASON_INVALID_NICK)
            return

        nick = nick_or_reason

        # ham kimlik anahtarlarını ERKEN ayrıştır (tuzak/kara liste denetimi)
        try:
            client_eph_pub = crypto.b64d(env["eph_pub"])
            client_id_pub = crypto.b64d(env["id_pub"])
            client_nonce = crypto.b64d(env["nonce"])
        except Exception as exc:
            logger.warning("Bozuk HELLO verisi: %s", exc)
            return
        sid = crypto.b64e(client_id_pub)

        # 1) HONEYPOT: tuzak takma ad veya kara listedeki oturum →
        #    anında ret + yönetici alarmı + IP/oturum kara listesi.
        #    Red mesajı STEALTH: normal bir "nick çakışması" gibi görünür.
        if honeypot.is_trap_nick(nick) or honeypot.is_banned(sid):
            honeypot.alert(
                "honeypot-hello",
                f"tuzak/kara-liste katılımı: room={self.room_code} nick={nick} "
                f"sid={sid[:16]}…",
                ban_key=sid)
            self._reject_hello(
                env,
                "Bu takma ad odadaki başka bir katılımcı tarafından kullanılıyor.",
                messages.REASON_NICKNAME_TAKEN)
            return

        # 1b) Tuzak (decoy) odaya HER katılım denemesi yetkisiz girişdir:
        #     sahte oda "cazip" davranır, katılımcıyı hemen kara listeler.
        if self.is_honeypot:
            honeypot.alert(
                "decoy-join-attempt",
                f"tuzak odaya katılım: room={self.room_code} nick={nick} "
                f"sid={sid[:16]}…",
                ban_key=sid)
            self._reject_hello(
                env, "Bu odaya şu anda katılınamıyor.",
                messages.REASON_NICKNAME_TAKEN)
            return

        # 1. Tekil Kullanıcı Adı Denetimi (Kurucu ve diğer üyelerle çakışma)
        with self.lock:
            if nick.lower() == self.nickname.lower():
                logger.warning("Kurucu takma adıyla katılım reddedildi: %s", nick)
                reject = messages.new_envelope(
                    messages.REJECT,
                    to=env.get("mid"),
                    reason="Bu takma ad oda kurucusuna aittir. Lütfen farklı bir takma ad seçin.",
                    code=messages.REASON_NICKNAME_TAKEN,
                    reply_to=env.get("mid"),
                )
                self.channel.publish(self.ctrl_topic, reject)
                return

            if any(m.lower() == nick.lower() for m in self.members):
                logger.warning("Zaten odada olan takma adla katılım reddedildi: %s", nick)
                reject = messages.new_envelope(
                    messages.REJECT,
                    to=env.get("mid"),
                    reason="Bu takma ad odadaki başka bir katılımcı tarafından kullanılıyor.",
                    code=messages.REASON_NICKNAME_TAKEN,
                    reply_to=env.get("mid"),
                )
                self.channel.publish(self.ctrl_topic, reject)
                return

        # 2. Çoklu Katılım (Duplicate Participation) Denetimi: Aynı istemci anahtarı zaten bağlı mı?
        with self.lock:
            if any(crypto.constant_time_eq(client_id_pub, existing_pub) for existing_pub in self.member_pubs.values()):
                logger.warning("Aynı istemci anahtarıyla mükerrer katılım engellendi: %s", nick)
                reject = messages.new_envelope(
                    messages.REJECT,
                    to=env.get("mid"),
                    reason="Bu cihaz/oturum zaten odaya bağlıdır (Çoklu katılım engellendi).",
                    code=messages.REASON_DUPLICATE_CLIENT,
                    reply_to=env.get("mid"),
                )
                self.channel.publish(self.ctrl_topic, reject)
                return

        # 1-1 oturum anahtarı: kurucunun geçici ECDH anahtarı x katılanın pub'ı
        shared = crypto.derive_shared_secret(self.eph_priv, client_eph_pub)
        session_key = crypto.derive_session_key(shared)

        # Host onayı: katılanın nonce'unu oturum anahtarıyla şifrele -> katılan
        # bu nonce'u çözebiliyorsa host'un priv anahtarı gerçek (ECDH kanıtı).
        proof = crypto.aesgcm_encrypt(session_key, client_nonce)

        back = messages.new_envelope(
            messages.HELLO_BACK,
            to=env.get("mid"),
            room=self.room_code,
            host=self.nickname,
            eph_pub=crypto.b64e(self.eph_pub),
            id_pub=crypto.b64e(self.id_pub),
            proof=crypto.b64e(proof),
            reply_to=env.get("mid"),
        )
        self.channel.publish(self.ctrl_topic, back)

        # SAS kodunu hesapla ve UI'a bildir.
        sas = sas_of(self.id_pub, client_id_pub)
        with self.lock:
            self.pending_sas[nick] = sas
            self.member_pubs[nick] = client_id_pub
            self.session_keys[nick] = session_key
        if self.on_sas:
            try:
                self.on_sas(f"{nick}: {sas}")
            except Exception as exc:
                logger.debug("on_sas callback hatası: %s", exc)
        self._status(f"{nick} el sıkışıyor...")

    def _on_hb_ack(self, env: Dict[str, Any]) -> None:
        """Katılan 1-1 anahtarı onayladı: grup anahtarını kendine sar."""
        nick = str(env.get("nick", ""))[:24] or "misafir"
        with self.lock:
            session_key = self.session_keys.get(nick)
            if session_key is None:
                return  # el sıkışma yok
            if nick in self.members:
                return  # zaten üye
            # Grup anahtarını katılanın kimlik pub'ı ile ECIES sar.
            id_pub = self.member_pubs.get(nick)
            if id_pub is None:
                return
            x_pub = crypto.ed25519_pub_to_x25519(id_pub)
            wrap = crypto.ecies_encrypt(x_pub, self.room_key)
            self.member_wraps[nick] = wrap
            self.members[nick] = {"key": session_key, "joined": time.time()}
        join = messages.new_envelope(
            messages.MEMBER_JOIN,
            nick=nick,
            wrap=crypto.b64e(wrap),
            host=self.nickname,
        )
        self.channel.publish(self.ctrl_topic, join)
        self._broadcast_members()
        self._status(f"{nick} odaya katıldı")
        self._system(f"{nick} odaya katıldı")

    def _on_bye(self, env: Dict[str, Any]) -> None:
        nick = str(env.get("nick", ""))
        with self.lock:
            left = self.members.pop(nick, None)
            self.member_pubs.pop(nick, None)
            self.member_wraps.pop(nick, None)
            self.session_keys.pop(nick, None)
            self.pending_sas.pop(nick, None)
        if left:
            self._broadcast_members()
            self._system(f"{nick} odadan ayrıldı")
            if self.on_peer_left:
                try:
                    self.on_peer_left(nick)
                except Exception as exc:
                    logger.debug("on_peer_left callback hatası: %s", exc)

    # ----- grup yönetimi

    def _broadcast_members(self) -> None:
        """Üye listesini oda anahtarıyla şifreli + host imzasıla yayınla.

        İçerik: nick -> id_pub haritası (alıcıların kimlik bağlama yapabilmesi
        için) ve host_pub. Yalnızca host'un Ed25519 imzasıyla kabul edilir.
        """
        if self.room_key is None:
            return  # oda kapandı
        with self.lock:
            names = sorted(self.members.keys()) + [self.nickname]
            pubs = {n: crypto.b64e(p) for n, p in self.member_pubs.items()}
        inner = {"names": names, "host": self.nickname,
                 "host_pub": crypto.b64e(self.id_pub), "pubs": pubs,
                 "ts": time.time()}
        raw = json.dumps(inner, separators=(",", ":")).encode("utf-8")
        blob = crypto.aesgcm_encrypt(self.room_key, raw)
        sig = crypto.sign(self.id_priv, raw)
        self._publish(messages.new_envelope(
            messages.MEMBERS, blob=crypto.b64e(blob),
            sid=crypto.b64e(self.id_pub), sig=crypto.b64e(sig)))

    def send_chat(self, text: str):
        """Kurucunun sohbet mesajını grup anahtarıyla yayınla.

        Başarıda ``msg_id`` (düzenleme/silme için kimlik) döner,
        başarısızlıkta ``False``. Truthy kontrolü eski kodla uyumludur.
        """
        clean_text = messages.sanitize_text(text)
        if not clean_text:
            return False
        if not self.rate_limiter.allow():
            self._status("Çok hızlı mesaj gönderiyorsunuz (Rate limit), lütfen bekleyin.")
            return False
        payload = messages.make_chat_payload(self.nickname, clean_text)
        self._send_data(payload, self.room_key)
        try:
            return json.loads(payload).get("msg_id") or True
        except Exception:
            return True

    def send_typing(self) -> None:
        """Yazıyor bildirimi."""
        payload = messages.make_chat_payload(self.nickname, "", messages.INNER_TYPING)
        self._send_data(payload, self.room_key)

    def leave(self) -> None:
        """Odadan ayrıl (kurucu için = kapat)."""
        self.stop()

    def stop(self) -> None:
        """Oturumu ve kanalı kapat, durum değişkenlerini ve sırları sıfırla."""
        super().stop()
        with self.lock:
            self.members.clear()
            self.session_keys.clear()
            self.member_pubs.clear()
            self.member_wraps.clear()
            self.pending_sas.clear()
        # oturum sırlarını bellekten düşür (Python bayt silinemez; referans
        # bırakmamak GC'ye temizletir) + tekrar önbelleğini boşalt
        self.room_key = None
        self.eph_priv = None
        with self._tokens_lock:
            self._seen_tokens.clear()

    # ----- gelen veri

    def _on_data(self, env: Dict[str, Any]) -> None:
        result = self._decrypt_data(env, self.room_key)
        if result is None:
            return
        payload, sid = result

        # kişi başı gelen kotası (flood/DoS)
        if not self._peer_limiter.allow("d:" + crypto.b64e(sid)):
            logger.warning("DATA rate limit aşıldı — düşürüldü (%s)", payload.sender)
            return
        # replay penceresi + payload nonce tekilleştirme
        if not self._ts_fresh(payload.ts) or self._is_duplicate(
                "n:", f"{payload.sender}:{payload.nonce}"):
            logger.warning("Tekrarlanan/eski DATA — düşürüldü (%s)", payload.sender)
            return
        if payload.kind == messages.INNER_TYPING:
            return
        # Broker kendi mesajımızı geri yansıtır; yut.
        if payload.sender == self.nickname:
            return
        # kimlik bağlama: gönderen kayıtlı bir üye olmalı
        # (üye olmayan sid / sahte zarf burada düşer)
        if not any(crypto.constant_time_eq(sid, pub)
                   for pub in self.member_pubs.values()):
            logger.warning("Üye olmayan gönderenden DATA — düşürüldü")
            return
        self._emit_group_payload(payload)

    def _system(self, text: str) -> None:
        """Sistem mesajını da şifreli yayınla (herkes görsün)."""
        payload = messages.make_chat_payload("sistem", text)
        self._send_data(payload, self.room_key)
        if self.on_message:
            try:
                self.on_message("sistem", text, True)
            except Exception:
                pass


# ---------------------------------------------------------------- KATILAN (client)


class Client(_Base):
    """Odaya katılan taraf: kod + nickname ile bağlanır."""

    def __init__(self, nickname: str, room_code: str, status_cb: StatusCb = None,
                 log_cb: LogCb = None):
        super().__init__(nickname, status_cb, log_cb)
        # MQTT topic joker enjeksiyonuna (`+` / `#`) karşı sıkı kod doğrulama
        ok, code_or_reason = messages.validate_room_code(room_code)
        if not ok:
            raise ValueError(code_or_reason)
        self.room_code = code_or_reason
        self.data_topic = topic_for(self.room_code, "data")
        self.ctrl_topic = topic_for(self.room_code, "ctrl")
        self.eph_priv, self.eph_pub = crypto.generate_ecdh_keypair()
        self.nonce = os.urandom(16)
        self.session_key: Optional[bytes] = None
        self.room_key: Optional[bytes] = None
        self.host_pub: Optional[bytes] = None
        self.sas: Optional[str] = None
        self.last_error: str = ""
        self.on_rejected: Optional[Callable[[str], None]] = None
        self._member_pubs: Dict[str, bytes] = {}  # nick -> id_pub (kimlik bağlama)
        self._handshake_done = threading.Event()
        self._joined = threading.Event()

    # ----- başlatma

    def start(self) -> bool:
        """Broker'a bağlan ve el sıkışmayı başlat."""
        if not self._open_channel((self.data_topic, self.ctrl_topic)):
            self._status("Broker'a ulaşılamadı (internet yok?)")
            return False
        self.running = True
        self._status("Odaya bağlanılıyor...")
        threading.Thread(target=self._handshake_loop, daemon=True).start()
        threading.Thread(target=self._keepalive_loop, daemon=True).start()
        return True

    def wait_joined(self, timeout: float = config.CONNECT_TIMEOUT) -> bool:
        """El sıkışma + grup anahtarı tamamlanana kadar bekler."""
        return self._joined.wait(timeout)

    # ----- el sıkışma

    def _handshake_loop(self) -> None:
        logger.debug("handshake_loop başladı")
        try:
            deadline = time.time() + config.CONNECT_TIMEOUT
            sent = 0
            while self.running and time.time() < deadline and not self._handshake_done.is_set():
                try:
                    hello = messages.new_envelope(
                        messages.HELLO,
                        nick=self.nickname,
                        eph_pub=crypto.b64e(self.eph_pub),
                        id_pub=crypto.b64e(self.id_pub),
                        nonce=crypto.b64e(self.nonce),
                    )
                    self.channel.publish(self.ctrl_topic, hello)
                    sent += 1
                except Exception as exc:
                    logger.error("handshake_loop HELLO gönderme hatası: %s", exc, exc_info=True)
                self._handshake_done.wait(1.0)
            if not self._handshake_done.is_set():
                if not self.last_error:
                    self.last_error = "Oda bulunamadı veya el sıkışma zaman aşımı"
                self._status(self.last_error)
        except Exception as exc:
            logger.critical("handshake_loop beklenmedik hata — thread sonlandı: %s", exc, exc_info=True)
            if not self.last_error:
                self.last_error = f"İç hata: {exc}"
            self._status(self.last_error)
        finally:
            logger.debug("handshake_loop bitti (running=%s)", self.running)

    def _keepalive_loop(self) -> None:
        logger.debug("keepalive_loop başladı")
        try:
            while self.running:
                time.sleep(10)
                if self.running and self._joined.is_set():
                    try:
                        env = messages.new_envelope(messages.KEEPALIVE, nick=self.nickname)
                        self._publish(env)
                    except Exception as exc:
                        logger.warning("keepalive_loop gönderme hatası: %s", exc)
        except Exception as exc:
            logger.critical("keepalive_loop beklenmedik hata — thread sonlandı: %s", exc, exc_info=True)
        finally:
            logger.debug("keepalive_loop bitti (running=%s)", self.running)

    def handle_envelope(self, env: Dict[str, Any], topic: str) -> None:
        kind = env.get("t")
        if self._is_duplicate("m:", env.get("mid")):
            return

        if kind == messages.HELLO_BACK:
            if env.get("announce"):
                return  # duyuru zarfı; katılım için HELLO zaten gönderildi
            self._on_hello_back(env)
        elif kind == messages.REJECT:
            self._on_reject(env)
        elif kind == messages.MEMBER_JOIN and env.get("nick") == self.nickname:
            self._on_member_join(env)
        elif kind == messages.MEMBERS:
            self._on_members(env)
        elif kind == messages.DATA:
            self._on_data(env)

    def _on_reject(self, env: Dict[str, Any]) -> None:
        """Host katılımı reddettiğinde el sıkışmayı anında durdur ve nedeni bildir."""
        reason = env.get("reason", "Bağlantı host tarafından reddedildi.")
        self.last_error = reason
        self._handshake_done.set()  # Zaman aşımını beklemeden çık
        self._status(f"Reddedildi: {reason}")
        logger.warning("Katılım host tarafından reddedildi: %s", reason)
        if self.on_rejected:
            try:
                self.on_rejected(reason)
            except Exception as exc:
                logger.debug("on_rejected callback hatası: %s", exc)

    def _on_hello_back(self, env: Dict[str, Any]) -> None:
        """Host'un onayı: proof'u çözüp nonce'u doğrula, sonra ACK gönder."""
        try:
            host_eph_pub = crypto.b64d(env["eph_pub"])
            host_id_pub = crypto.b64d(env["id_pub"])
            proof = crypto.b64d(env["proof"])
        except Exception as exc:
            logger.debug("Bozuk HELLO_BACK zarfı: %s", exc)
            return

        shared = crypto.derive_shared_secret(self.eph_priv, host_eph_pub)
        session_key = crypto.derive_session_key(shared)
        try:
            recovered = crypto.aesgcm_decrypt(session_key, proof)
        except Exception:
            self.last_error = "El sıkışma doğrulaması başarısız (MITM şüphesi)"
            self._status(self.last_error)
            return
        if recovered != self.nonce:
            self.last_error = "Nonce doğrulaması başarısız"
            self._status(self.last_error)
            return

        # Host kimliğini ve 1-1 anahtarı kaydet, ACK gönder.
        self.host_pub = host_id_pub
        self.session_key = session_key
        self.sas = sas_of(self.id_pub, host_id_pub)
        if self.on_sas:
            try:
                self.on_sas(f"host: {self.sas}")
            except Exception as exc:
                logger.debug("on_sas callback hatası: %s", exc)

        ack = messages.new_envelope(messages.HELLO_BACK_ACK, nick=self.nickname)
        self.channel.publish(self.ctrl_topic, ack)
        self._handshake_done.set()
        self._status("El sıkışma tamam, grup anahtarı bekleniyor...")

    def _on_member_join(self, env: Dict[str, Any]) -> None:
        """Host'un ECIES sarmalı grup anahtarını aç."""
        try:
            wrap = crypto.b64d(env["wrap"])
            x_priv = crypto.ed25519_priv_to_x25519(self.id_priv)
            room_key = crypto.ecies_decrypt(x_priv, wrap)
        except Exception as exc:
            self.last_error = f"Grup anahtarı açılamadı: {exc}"
            self._status(self.last_error)
            return
        self.room_key = room_key
        self._joined.set()
        self._status("Bağlandı")

    def _on_members(self, env: Dict[str, Any]) -> None:
        """Şifreli + host imzalı üye listesi (nick -> id_pub haritası dahil)."""
        if self.room_key is None or self.host_pub is None:
            return
        try:
            blob = crypto.b64d(env["blob"])
            raw = crypto.aesgcm_decrypt(self.room_key, blob)
            sid = crypto.b64d(env["sid"])
            sig = crypto.b64d(env["sig"])
        except Exception:
            return
        # üye listesi SADECE host imzasıyla kabul edilir (sahte harita engeli)
        if not crypto.constant_time_eq(sid, self.host_pub) or \
                not crypto.verify(self.host_pub, raw, sig):
            logger.warning("Sahte üye listesi — düşürüldü")
            return
        try:
            inner = json.loads(raw.decode("utf-8"))
        except Exception:
            return
        self.members = {n: {} for n in inner.get("names", [])}
        pubs = inner.get("pubs") or {}
        new_pubs: Dict[str, bytes] = {}
        for nick, pub_b64 in pubs.items():
            try:
                new_pubs[str(nick)] = crypto.b64d(pub_b64)
            except Exception:
                continue
        self._member_pubs = new_pubs

    def _on_data(self, env: Dict[str, Any]) -> None:
        if self.room_key is None:
            return
        result = self._decrypt_data(env, self.room_key)
        if result is None:
            return
        payload, sid = result

        # kişi başı gelen kotası (flood/DoS)
        if not self._peer_limiter.allow("d:" + payload.sender):
            logger.warning("DATA rate limit aşıldı — düşürüldü (%s)", payload.sender)
            return
        # replay penceresi + payload nonce tekilleştirme
        if not self._ts_fresh(payload.ts) or self._is_duplicate(
                "n:", f"{payload.sender}:{payload.nonce}"):
            logger.warning("Tekrarlanan/eski DATA — düşürüldü (%s)", payload.sender)
            return
        if payload.kind == messages.INNER_TYPING:
            return
        # Broker kendi mesajımızı geri yansıtır; yut.
        if payload.sender == self.nickname:
            return

        # --- kimlik bağlama (impersonation savunması) ---
        is_system = payload.sender == "sistem"
        if is_system:
            # "sistem" mesajı YALNIZCA host'un imzasıyla geçerli
            if self.host_pub is None or not crypto.constant_time_eq(sid, self.host_pub):
                logger.warning("Sahte sistem mesajı — düşürüldü")
                return
        else:
            expected = self._member_pubs.get(payload.sender)
            if expected is not None and not crypto.constant_time_eq(sid, expected):
                logger.warning("Takma ad taklidi (sid uyuşmuyor) — düşürüldü: %s",
                               payload.sender)
                return

        self._emit_group_payload(payload)

    # ----- gönderim

    def send_chat(self, text: str):
        """Sohbet mesajını grup anahtarıyla yayınla.

        Başarıda ``msg_id`` döner, başarısızlıkta ``False``.
        """
        if self.room_key is None:
            self._status("Henüz bağlı değilsin")
            return False
        clean_text = messages.sanitize_text(text)
        if not clean_text:
            return False
        if not self.rate_limiter.allow():
            self._status("Çok hızlı mesaj gönderiyorsunuz (Rate limit), lütfen bekleyin.")
            return False
        payload = messages.make_chat_payload(self.nickname, clean_text)
        self._send_data(payload, self.room_key)
        try:
            return json.loads(payload).get("msg_id") or True
        except Exception:
            return True

    def leave(self) -> None:
        """Odadan ayrıl (BYE yayınla)."""
        if self.running and self._joined.is_set():
            try:
                self._publish(messages.new_envelope(messages.BYE, nick=self.nickname))
                time.sleep(0.2)  # yayının gitmesine izin ver
            except Exception as exc:
                logger.debug("BYE gönderme hatası: %s", exc)
        self.stop()

    def stop(self) -> None:
        """Oturumu ve kanalı kapat; durum değişkenlerini ve sırları sıfırla."""
        self.running = False
        self._handshake_done.set()
        self._joined.clear()
        super().stop()
        self.session_key = None
        self.room_key = None
        self.host_pub = None
        self.eph_priv = None
        self._member_pubs.clear()
        with self._tokens_lock:
            self._seen_tokens.clear()
        self.members.clear()
