"""Güvenlik, validasyon, çoklu katılım engeli ve rate limiting birim testleri."""
from __future__ import annotations

import time
import pytest

from secretchat import config, crypto, messages
from secretchat.security import RateLimiter, KeyedRateLimiter
from secretchat.room import Host, Client


def test_nickname_validation():
    # Geçerli isimler
    ok, nick = messages.validate_nickname("alperen")
    assert ok and nick == "alperen"

    ok, nick = messages.validate_nickname("  user_123-x  ")
    assert ok and nick == "user_123-x"

    # Çok kısa / çok uzun
    ok, err = messages.validate_nickname("a")
    assert not ok and "en az" in err

    ok, err = messages.validate_nickname("a" * 25)
    assert not ok and "en fazla" in err

    # Sistemde ayrılmış isimler
    for reserved in ("admin", "sistem", "system", "root"):
        ok, err = messages.validate_nickname(reserved)
        assert not ok and "ayrılmıştır" in err

    # Özel / zararlı karakterler
    ok, err = messages.validate_nickname("user<script>")
    assert not ok


def test_sanitize_text():
    # Null byte ve kontrol karakteri temizliği
    raw = "selam\x00dünya\x07\x08test\nparagraf\tsekme"
    clean = messages.sanitize_text(raw)
    assert "\x00" not in clean
    assert "\x07" not in clean
    assert "paragraf\tsekme" in clean

    # Maksimum uzunluk kısıtlaması
    long_msg = "x" * (config.MAX_MESSAGE_LENGTH + 500)
    clean_long = messages.sanitize_text(long_msg)
    assert len(clean_long) == config.MAX_MESSAGE_LENGTH


def test_rate_limiter():
    limiter = RateLimiter(capacity=3, fill_rate=1.0)
    assert limiter.allow()
    assert limiter.allow()
    assert limiter.allow()
    # 4. deneme reddedilmeli
    assert not limiter.allow()


def test_keyed_rate_limiter():
    keyed = KeyedRateLimiter(capacity=2, fill_rate=1.0)
    assert keyed.allow("user1")
    assert keyed.allow("user1")
    assert not keyed.allow("user1")

    # Farklı kullanıcı bağımsız olmalı
    assert keyed.allow("user2")


def test_host_rejects_duplicate_and_invalid_nicknames():
    host = Host("kurucu")

    # 1. Kurucu ile aynı takma ad
    hello_duplicate = messages.new_envelope(
        messages.HELLO,
        nick="kurucu",
        eph_pub=crypto.b64e(b"\x01" * 32),
        id_pub=crypto.b64e(b"\x02" * 32),
        nonce=crypto.b64e(b"\x03" * 16),
    )
    published = []
    host.channel = type("DummyChannel", (), {"publish": lambda s, t, env: published.append(env)})()

    host.handle_envelope(hello_duplicate, "ctrl")
    assert len(published) == 1
    assert published[0]["t"] == messages.REJECT
    assert published[0]["code"] == messages.REASON_NICKNAME_TAKEN

    # 2. Geçersiz takma ad (ayrılmış sistem adı)
    published.clear()
    hello_invalid = messages.new_envelope(
        messages.HELLO,
        nick="admin",
        eph_pub=crypto.b64e(b"\x01" * 32),
        id_pub=crypto.b64e(b"\x02" * 32),
        nonce=crypto.b64e(b"\x03" * 16),
    )
    host.handle_envelope(hello_invalid, "ctrl")
    assert len(published) == 1
    assert published[0]["t"] == messages.REJECT
    assert published[0]["code"] == messages.REASON_INVALID_NICK


def test_host_rejects_duplicate_client_identity():
    host = Host("kurucu")
    client_id = b"\x07" * 32

    # Üye listesine client_id ekle
    host.member_pubs["mevcut_uye"] = client_id

    hello_duplicate_id = messages.new_envelope(
        messages.HELLO,
        nick="baska_nick",
        eph_pub=crypto.b64e(b"\x01" * 32),
        id_pub=crypto.b64e(client_id),
        nonce=crypto.b64e(b"\x03" * 16),
    )
    published = []
    host.channel = type("DummyChannel", (), {"publish": lambda s, t, env: published.append(env)})()

    host.handle_envelope(hello_duplicate_id, "ctrl")
    assert len(published) == 1
    assert published[0]["t"] == messages.REJECT
    assert published[0]["code"] == messages.REASON_DUPLICATE_CLIENT
