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

    def to_json(self) -> str:
        return json.dumps(self.__dict__, separators=(",", ":"))


def make_chat_payload(sender: str, text: str, kind: str = INNER_CHAT) -> str:
    """Şifrelenecek sohbet yükü JSON'u üret."""
    clean_text = sanitize_text(text) if kind == INNER_CHAT else text
    p = ChatPayload(sender=sender, text=clean_text, kind=kind,
                    nonce=os.urandom(4).hex())
    return p.to_json()


# ---------------------------------------------------------------- yardımcılar


def is_keepalive(env: Dict[str, Any]) -> bool:
    return env.get("t") in (KEEPALIVE, PING, PONG)


def envelope_kind(env: Dict[str, Any]) -> str:
    return env.get("t", "")
