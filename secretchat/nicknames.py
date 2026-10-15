"""Otomatik gizli rumuz atama (privacy-preserving anonymous nicknames).

Kullanıcı adı boş bırakıldığında ``"donmuş çilek 6748"`` gibi
sıfat + nesne + sayı kombinasyonu üretilir. Üretilen rumuz
``messages.validate_nickname`` kurallarına uyar (2-24 karakter,
izinli karakterler) ve ayrılmış isimlerle çakışmaz.
"""
from __future__ import annotations

import secrets
from typing import Tuple

from . import messages

# Kısa Türkçe sıfatlar (max ~8 harf → toplam uzunluk ≤24 kalır)
ADJECTIVES = (
    "mavi", "yeşil", "donmuş", "sessiz", "hızlı", "parlak",
    "gizli", "uykulu", "neşeli", "bulutlu", "cesur", "kıvrak",
    "sakin", "turuncu", "mor", "altın", "gümüş", "pamuk",
    "yankılı", "sisli", "çevik", "bilge", "ıssız", "pırıl",
)

# Kısa Türkçe nesneler
NOUNS = (
    "çilek", "bulut", "tilki", "kelebek", "dalga", "yıldız",
    "orman", "nehir", "martı", "kedi", "serçe", "papatya",
    "ateş", "kar", "rüzgar", "deniz", "kum", "meşe",
    "kırlangıç", "zeytin", "elma", "armut", "kuş", "taş",
)

NICK_NUMBER_MIN = 1000
NICK_NUMBER_MAX = 9999


def generate_anonymous_nick() -> str:
    """Rastgele ``sıfat nesne sayı`` rumuzu üret (örn. 'mavi bulut 1923')."""
    for _ in range(20):  # ayrılmış isim çakışmasına karşı sınırlı yeniden deneme
        adj = secrets.choice(ADJECTIVES)
        noun = secrets.choice(NOUNS)
        num = secrets.randbelow(NICK_NUMBER_MAX - NICK_NUMBER_MIN + 1) + NICK_NUMBER_MIN
        nick = f"{adj} {noun} {num}"
        if len(nick) > 24:  # güvenlik: uzun kombinasyonu ele
            continue
        if nick.lower() in messages.RESERVED_NICKNAMES:
            continue
        ok, _ = messages.validate_nickname(nick)
        if ok:
            return nick
    # Son çare: deterministik kısa yedek
    return f"sessiz tilki {secrets.randbelow(9000) + 1000}"


def resolve_nickname(raw: str) -> Tuple[bool, str]:
    """Boş girdide otomatik rumuz ata, dolu girdide doğrula.

    Dönüş: (True, nickname) veya (False, hata_mesajı).
    """
    cleaned = (raw or "").strip()
    if not cleaned:
        return True, generate_anonymous_nick()
    return messages.validate_nickname(cleaned)
