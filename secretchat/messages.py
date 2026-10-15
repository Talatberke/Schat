"""Tel protokolü: JSON zarfları ve serileştirme yardımcıları.

Tüm zarflar relay/broker üzerinden düz metin olarak taşınabilen JSON
belgeleridir; hassas alanlar (mesaj gövdesi, anahtarlar) şifrelidir.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from . import config

# ---------------------------------------------------------------- zarf türleri
HELLO = "hello"            # katılan -> host: ECDH pub + kimlik
HELLO_BACK = "hello_back"  # host -> katılan: host pub + şifreli doğrulama
HELLO_BACK_ACK = "hb_ack"  # katılan -> host: 1-1 anahtar onayı
KEEPALIVE = "keepalive"
BYE = "bye"
MEMBERS = "members"        # host -> tümü: üye listesi (oda anahtarıyla)
MEMBER_JOIN = "m_join"     # host -> yeni üye: grup anahtarı (ECIES sarmalı)
MEMBER_LEFT = "m_left"
DATA = "data"              # şifreli grup trafiği
PING = "ping"
PONG = "pong"
REJECT = "reject"          # host -> katılan: katılım reddi (benzersiz kullanıcı / çift katılım)

# Red Neden Kodları
REASON_NICKNAME_TAKEN = "nickname_taken"
REASON_DUPLICATE_CLIENT = "duplicate_client"
REASON_INVALID_NICK = "invalid_nickname"
REASON_RATE_LIMITED = "rate_limited"

# Sistemde ayrılmış/yasaklı kullanıcı adları
RESERVED_NICKNAMES = {
    "sistem", "system", "admin", "administrator", "root",
    "all", "everyone", "null", "undefined", "bot"
}

# DATA zarfı içindeki türlar
INNER_CHAT = "chat"
INNER_EMOTE = "emote"
INNER_TYPING = "typing"
INNER_PING = "ping"
INNER_PONG = "pong"
INNER_IMAGE = "image"  # fotoğraf gönderimi (base64 + açıklama)
INNER_EDIT = "edit"    # mesaj düzenleme (msg_id + yeni metin)
INNER_DELETE = "delete"  # mesaj silme (msg_id)

MAX_ENVELOPE_SIZE = 256 * 1024  # 256 kB


def _now() -> float:
    return time.time()


def new_envelope(kind: str, **fields: Any) -> Dict[str, Any]:
    """Yeni zarf oluştur."""
    env = {"v": 1, "t": kind, "ts": _now(), "mid": uuid.uuid4().hex[:12]}
    env.update(fields)
    return env


def encode_envelope(env: Dict[str, Any]) -> bytes:
    """Zararı sıkıştırıp bayta çevir."""
    data = json.dumps(env, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_ENVELOPE_SIZE:
        raise ValueError("zarf çok büyük")
    return data


def decode_envelope(data: bytes) -> Dict[str, Any]:
    """Baytları zarf sözlüğüne çevir (boyut sınırı uygulanır)."""
    if len(data) > MAX_ENVELOPE_SIZE:
        raise ValueError("gelen zarf çok büyük")
    try:
        env = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise ValueError("geçersiz zarf") from exc
    if not isinstance(env, dict) or "t" not in env:
        raise ValueError("geçersiz zarf")
    return env


# ---------------------------------------------------------------- doğrulama ve temizleme (validation & sanitization)


def validate_nickname(nick: str) -> Tuple[bool, str]:
    """Takma ad kurallarını denetle: 2-24 karakter, alfanümerik/alt çizgi/tire/boşluk."""
    if not isinstance(nick, str):
        return False, "Takma ad geçerli bir metin olmalıdır."
    cleaned = nick.strip()
    if len(cleaned) < config.NICKNAME_MIN_LEN:
        return False, f"Takma ad en az {config.NICKNAME_MIN_LEN} karakter olmalıdır."
    if len(cleaned) > config.NICKNAME_MAX_LEN:
        return False, f"Takma ad en fazla {config.NICKNAME_MAX_LEN} karakter olabilir."
    if cleaned.lower() in RESERVED_NICKNAMES:
        return False, "Bu takma ad sistem tarafından ayrılmıştır."
    if not re.match(r"^[a-zA-Z0-9_\-\u00C0-\u017F ]+$", cleaned):
        return False, "Takma ad özel karakterler veya kontrol karakterleri içeremez."
    return True, cleaned


def validate_room_code(code: str) -> Tuple[bool, str]:
    """Oda kodu doğrulaması: yalnızca oda alfabesinden 5 karakter.

    MQTT topic enjeksiyonunu (`+` / `#` joker karakterleri) ve kontrol
    karakteri sızıntısını engeller. Geçerliyse büyük-normalize hâli döner.
    """
    if not isinstance(code, str):
        return False, "Oda kodu metin olmalıdır."
    c = code.strip().upper()
    if len(c) != config.ROOM_CODE_LENGTH:
        return False, f"Oda kodu {config.ROOM_CODE_LENGTH} haneli olmalıdır."
    if any(ch not in config.ROOM_CODE_ALPHABET for ch in c):
        return False, "Oda kodu yalnızca sayılardan ve harflerden oluşabilir."
    return True, c


def sanitize_text(text: str) -> str:
    """Mesaj metnini temizle: kontrol karakterlerini ve uzunluk taşmalarını engelle."""
    if not isinstance(text, str):
        return ""
    # Maksimum uzunluk sınırlaması
    bounded = text[:config.MAX_MESSAGE_LENGTH]
    # Null byte ve istenmeyen ASCII kontrol karakterlerini temizle (CR, LF, TAB hariç)
    cleaned = "".join(ch for ch in bounded if ch in ("\n", "\t", "\r") or ord(ch) >= 32)
    return cleaned.strip()


# ---------------------------------------------------------------- konuşma (inner)


@dataclass
class ChatPayload:
    """DATA zarfı içindeki şifreli sohbet yükü."""
    sender: str           # gönderen nickname
    text: str             # düz metin (yalnızca şifreleme sonrası ağa çıkar)
    nonce: str = ""       # istemci üretir; host tuzlayıp doğrular
    kind: str = INNER_CHAT
    ts: float = field(default_factory=_now)
    # --- fotoğraf gönderimi (yalnızca kind == INNER_IMAGE iken dolu) ---
    image: str = ""       # base64 kodlu JPEG/PNG
    caption: str = ""     # fotoğraf altı açıklama (en fazla 200 karakter)
    w: int = 0            # orijinal genişlik (px, bilgi amaçlı)
    h: int = 0            # orijinal yükseklik (px, bilgi amaçlı)
    # --- düzenleme / silme (kind == edit/delete iken hedef mesaj kimliği) ---
    msg_id: str = ""      # hedeflenen orijinal mesajın kimliği

    def to_json(self) -> str:
        return json.dumps(self.__dict__, separators=(",", ":"))


def parse_chat_payload(data: Dict[str, Any]) -> ChatPayload:
    """Bilinmeyen alanları yoksayarak toleranslı yük ayrıştırma.

    İleriye dönük uyumluluk: yeni alanlar eski istemcileri çökertmez.
    """
    known = {f for f in ChatPayload.__dataclass_fields__}
    filtered = {k: v for k, v in data.items() if k in known}
    return ChatPayload(**filtered)


def make_chat_payload(sender: str, text: str, kind: str = INNER_CHAT,
                      msg_id: str = "") -> str:
    """Şifrelenecek sohbet yükü JSON'u üret.

    Her sohbet/fotoğraf yüküne düzenleme/silme için sabit bir ``msg_id``
    atanır (verilmezse üretilir). Dönüş JSON'undan ``msg_id`` okunarak
    UI kaydı tutulabilir.
    """
    clean_text = sanitize_text(text) if kind == INNER_CHAT else text
    mid = msg_id or uuid.uuid4().hex[:12]
    p = ChatPayload(sender=sender, text=clean_text, kind=kind,
                    nonce=os.urandom(4).hex(), msg_id=mid)
    return p.to_json()


def make_edit_payload(sender: str, msg_id: str, new_text: str) -> str:
    """Mesaj düzenleme yükü (hedef msg_id + yeni metin)."""
    if not msg_id:
        raise ValueError("Düzenlenecek mesaj kimliği boş.")
    clean = sanitize_text(new_text)
    if not clean:
        raise ValueError("Yeni mesaj metni boş.")
    p = ChatPayload(sender=sender, text=clean, kind=INNER_EDIT,
                    nonce=os.urandom(4).hex(), msg_id=msg_id)
    return p.to_json()


def make_delete_payload(sender: str, msg_id: str) -> str:
    """Mesaj silme yükü (hedef msg_id)."""
    if not msg_id:
        raise ValueError("Silinecek mesaj kimliği boş.")
    p = ChatPayload(sender=sender, text="", kind=INNER_DELETE,
                    nonce=os.urandom(4).hex(), msg_id=msg_id)
    return p.to_json()


def validate_image_b64(image_b64: str) -> Tuple[bool, str]:
    """Fotoğraf base64 yükünü boyut/sözdizimi açısından denetle."""
    if not isinstance(image_b64, str) or not image_b64:
        return False, "Görüntü verisi boş."
    if len(image_b64) > config.IMAGE_MAX_B64_LEN:
        return False, "Görüntü çok büyük."
    if len(image_b64) % 4 != 0:
        return False, "Görüntü verisi bozuk."
    return True, ""


def make_image_payload(sender: str, image_b64: str, caption: str = "",
                       w: int = 0, h: int = 0, msg_id: str = "") -> str:
    """Şifrelenecek fotoğraf yükü JSON'u üret (boyut korumalı)."""
    ok, reason = validate_image_b64(image_b64)
    if not ok:
        raise ValueError(reason)
    clean_cap = sanitize_text(caption or "")[:config.IMAGE_CAPTION_MAX]
    try:
        w_i, h_i = int(w), int(h)
    except (TypeError, ValueError):
        w_i, h_i = 0, 0
    w_i = max(0, min(w_i, 8192))
    h_i = max(0, min(h_i, 8192))
    mid = msg_id or uuid.uuid4().hex[:12]
    p = ChatPayload(sender=sender, text="", kind=INNER_IMAGE,
                    nonce=os.urandom(4).hex(), image=image_b64,
                    caption=clean_cap, w=w_i, h=h_i, msg_id=mid)
    blob = p.to_json()
    if len(blob.encode("utf-8")) + 1024 > MAX_ENVELOPE_SIZE:
        raise ValueError("Fotoğraf zarf sınırını aşıyor, daha küçük bir dosya seçin.")
    return blob


# ---------------------------------------------------------------- yardımcılar


def is_keepalive(env: Dict[str, Any]) -> bool:
    return env.get("t") in (KEEPALIVE, PING, PONG)


def envelope_kind(env: Dict[str, Any]) -> str:
    return env.get("t", "")
