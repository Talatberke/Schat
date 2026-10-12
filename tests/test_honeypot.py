"""Honeypot (siber tuzak) + savunma katmanı testleri.

Kapsadıkları:
- Tuzak oda adı/kodu ve tuzak takma adı tespiti
- Kara liste (TTL) ve yönetici alarm günlüğü
- MQTT topic enjeksiyonu (`+` / `#`) ve oda kodu doğrulaması
- Oda anahtarının koddan türetilmemesi (E2EE bypass kapatma)
- DATA imzası: imzasız/sahte imzalı zarflar, sistem taklidi, takma ad taklidi
- Replay penceresi, gelen HELLO sel limiti
- UI gizli girdi tuzağı + tuzak oda girişinde oturum kilidi
"""
from __future__ import annotations

import time

import pytest

from secretchat import config, crypto, messages, signaling
from secretchat import honeypot
from secretchat.room import Client, Host


@pytest.fixture(autouse=True)
def _clean_honeypot(tmp_path, monkeypatch):
    """Her test öncesi/sonrası: kara liste + alarmlar temiz, log tmp'ye."""
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path))
    honeypot.reset()
    yield
    honeypot.reset()


class _DummyChannel:
    def __init__(self):
        self.published = []

    def publish(self, topic, env):
        self.published.append(env)


# ---------------------------------------------------------------- tespit


def test_trap_room_detection():
    # spesikasyondaki cazip sahte oda adları
    for name in ("admin-secrets", "global-config", "vault"):
        assert honeypot.is_trap_room(name)
        assert honeypot.is_trap_room(name.upper())
        assert honeypot.is_trap_room(f"  {name}  ")
    # ayraç varyantları da yakalanır
    assert honeypot.is_trap_room("admin_secrets")
    assert honeypot.is_trap_room("admin secrets")
    # yem oda kodları (5 hane, alfabeli)
    for code in config.HONEYPOT_TRAP_CODES:
        assert honeypot.is_trap_room(code)
    # normal oda kodu tuzak değildir
    assert not honeypot.is_trap_room("3K7QX")
    assert not honeypot.is_trap_room("")


def test_trap_nick_detection():
    assert honeypot.is_trap_nick("vault-admin")
    assert honeypot.is_trap_nick("SYSADMIN")
    assert not honeypot.is_trap_nick("normal-kullanici")


def test_blacklist_ttl_and_sweep():
    bl = honeypot.Blacklist(ttl=60.0)
    assert not bl.is_banned("s1")
    bl.ban("s1", reason="test")
    assert bl.is_banned("s1")
    assert bl.reason("s1") == "test"
    # süresini elle doldur → temizlenir
    bl._entries["s1"] = (time.time() - 1, "test")
    assert not bl.is_banned("s1")
    bl.ban("s2")
    bl._entries["s2"] = (time.time() - 1, "test")
    bl.sweep()
    assert len(bl) == 0


def test_admin_log_written(tmp_path):
    honeypot.alert("unit-test", "deneme alarmı", ban_key="sess-1")
    from pathlib import Path
    log = Path(config.LOG_DIR) / config.HONEYPOT_LOG_NAME
    assert log.exists()
    content = log.read_text(encoding="utf-8")
    assert "unit-test" in content and "deneme alarmı" in content
    # kara listeye alındı
    assert honeypot.is_banned("sess-1")
    # RAM alarm listesi
    assert any(a["event"] == "unit-test" for a in honeypot.recent_alerts())


# ---------------------------------------------------------------- oda kodu / topic


def test_validate_room_code_blocks_wildcards():
    ok, code = messages.validate_room_code("3k7qx")
    assert ok and code == "3K7QX"
    # MQTT joker karakterleri ve geçersiz uzunluklar reddedilir
    for bad in ("+++++", "#####", "A/B/C", "AB CD", "3K7", "3K7QXTRA"):
        ok, _ = messages.validate_room_code(bad)
        assert not ok, bad


def test_topic_for_rejects_injection():
    assert signaling.topic_for("3K7QX", "data") == "sc/v3/3K7QX/data"
    with pytest.raises(ValueError):
        signaling.topic_for("+", "data")     # tüm odalara abonelik denemesi
    with pytest.raises(ValueError):
        signaling.topic_for("3K7Q#", "ctrl")
    with pytest.raises(ValueError):
        signaling.topic_for("3K7QX", "evil")  # geçersiz son ek


def test_client_rejects_wildcard_room_code():
    with pytest.raises(ValueError):
        Client("nick", "+++++")
    with pytest.raises(ValueError):
        Client("nick", "ab")


# ---------------------------------------------------------------- kripto


def test_room_key_is_random_not_code_derived():
    """KRİTİK: oda anahtarı oda kodundan TÜRETİLMEMELİ (broker kodu biliyor)."""
    h1 = Host("kurucu1")
    h2 = Host("kurucu2")
    assert len(h1.room_key) == 32
    assert h1.room_key != crypto.derive_room_key(h1.room_code)
    assert h1.room_key != h2.room_key  # odalar arası bağımsız anahtar
    h1.stop()
    h2.stop()


def test_stop_clears_session_secrets():
    h = Host("kurucu")
    h.stop()
    assert h.room_key is None
    assert h.eph_priv is None
    c = Client("katilan", "3K7QX")
    c.stop()
    assert c.room_key is None and c.eph_priv is None


def test_data_signature_required_and_verified():
    h = Host("kurucu")
    key = h.room_key
    raw = messages.make_chat_payload("ada", "selam").encode("utf-8")
    blob = crypto.b64e(crypto.aesgcm_encrypt(key, raw))

    # 1) imzasız zarf kesin reddedilir
    env = messages.new_envelope(messages.DATA, blob=blob)
    assert h._decrypt_data(env, key) is None

    # 2) yanlış/imkânsız imza reddedilir
    env2 = messages.new_envelope(
        messages.DATA, blob=blob,
        sid=crypto.b64e(b"\x05" * 32),
        sig=crypto.b64e(b"\x06" * 64))
    assert h._decrypt_data(env2, key) is None

    # 3) doğru imza + doğru anahtar → çözülür, sid döner
    env3 = messages.new_envelope(
        messages.DATA, blob=blob,
        sid=crypto.b64e(h.id_pub),
        sig=crypto.b64e(crypto.sign(h.id_priv, raw)))
    res = h._decrypt_data(env3, key)
    assert res is not None
    payload, sid = res
    assert payload.text == "selam"
    assert sid == h.id_pub

    # 4) yanlış anahtarla çözülemez (GCM)
    assert h._decrypt_data(env3, b"\x00" * 32) is None
    h.stop()


def test_impersonation_and_fake_system_blocked():
    """İmza kimlik bağlama: sahte sistem mesajı ve takma ad taklidi düşer."""
    c = Client("katilan", "3K7QX")
    c.room_key = b"\x11" * 32
    c.host_pub = b"\x22" * 32          # gerçek host kimliği
    c._member_pubs = {"ada": b"\x33" * 32}
    received = []
    c.on_message = lambda s, t, is_sys: received.append((s, t, is_sys))

    def _env(sender: str, text: str, signer_priv: bytes, signer_pub: bytes):
        raw = messages.make_chat_payload(sender, text).encode("utf-8")
        blob = crypto.b64e(crypto.aesgcm_encrypt(c.room_key, raw))
        return messages.new_envelope(
            messages.DATA, blob=blob,
            sid=crypto.b64e(signer_pub),
            sig=crypto.b64e(crypto.sign(signer_priv, raw)))

    atk_priv, atk_pub = crypto.generate_signing_keypair()

    # a) saldırgan "sistem" taklidi → host_pub olmadığı için düşer
    c._on_data(_env("sistem", "anahtarları çaldık", atk_priv, atk_pub))
    assert received == []

    # b) saldırgan "ada" taklidi → sid üye haritasıyla uyuşmuyor → düşer
    c._on_data(_env("ada", "ben ada değilim", atk_priv, atk_pub))
    assert received == []

    # c) meşru: host'un kendi imzasıyla sistem mesajı → geçer
    host_priv, host_pub = crypto.generate_signing_keypair()
    c.host_pub = host_pub
    c._on_data(_env("sistem", "hoş geldin", host_priv, host_pub))
    assert received == [("sistem", "hoş geldin", True)]

    # d) meşru üye (ada'nın kendi anahtarı) → geçer
    ada_priv, ada_pub = crypto.generate_signing_keypair()
    c._member_pubs = {"ada": ada_pub}
    c._on_data(_env("ada", "selam", ada_priv, ada_pub))
    assert received[-1] == ("ada", "selam", False)
    c.stop()


def test_replay_window_rejected():
    """MAX_CLOCK_SKEW dışındaki (eski) mesajlar düşürülür."""
    c = Client("katilan", "3K7QX")
    c.room_key = b"\x11" * 32
    c.host_pub = b"\x22" * 32
    c._member_pubs = {"ada": b"\x33" * 32}
    received = []
    c.on_message = lambda s, t, sys_: received.append(t)

    ada_priv, ada_pub = crypto.generate_signing_keypair()
    c._member_pubs = {"ada": ada_pub}

    old = messages.ChatPayload(sender="ada", text="eski mesaj",
                               nonce="aa11bb22",
                               ts=time.time() - (config.MAX_CLOCK_SKEW + 60))
    raw = old.to_json().encode("utf-8")
    env = messages.new_envelope(
        messages.DATA,
        blob=crypto.b64e(crypto.aesgcm_encrypt(c.room_key, raw)),
        sid=crypto.b64e(ada_pub),
        sig=crypto.b64e(crypto.sign(ada_priv, raw)))
    c._on_data(env)
    assert received == []  # eski ts → replay olarak düştü

    # aynı zarfın TEKRARI (aynı nonce) da düşer
    fresh = messages.make_chat_payload("ada", "yeni")
    raw2 = fresh.encode("utf-8")
    env2 = messages.new_envelope(
        messages.DATA,
        blob=crypto.b64e(crypto.aesgcm_encrypt(c.room_key, raw2)),
        sid=crypto.b64e(ada_pub),
        sig=crypto.b64e(crypto.sign(ada_priv, raw2)))
    c._on_data(env2)
    assert len(received) == 1
    c._on_data(env2)  # birebir tekrar
    assert len(received) == 1
    c.stop()


def test_inbound_hello_flood_rate_limit():
    """30 sel HELLO → en fazla INBOUND_BURST kadarı işlenir."""
    host = Host("kurucu")
    host.channel = _DummyChannel()
    eph = crypto.generate_ecdh_keypair()[1]
    accepted = 0
    for i in range(30):
        env = messages.new_envelope(
            messages.HELLO,
            nick=f"flood{i:02d}",        # 2-24, benzersiz
            eph_pub=crypto.b64e(eph),
            id_pub=crypto.b64e(bytes([i]) * 32),
            nonce=crypto.b64e(b"\x03" * 16))
        before = len(host.channel.published)
        host.handle_envelope(env, "ctrl")
        if len(host.channel.published) > before:
            accepted += 1
    assert accepted <= config.INBOUND_BURST, \
        f"sel limiti aşıldı: {accepted} HELLO işlendi"
    host.stop()


# ---------------------------------------------------------------- honeypot: host


def test_host_rejects_trap_nick_and_bans():
    host = Host("kurucu")
    host.channel = _DummyChannel()

    env = messages.new_envelope(
        messages.HELLO,
        nick="vault-admin",            # tuzak takma adı (geçerli formatta)
        eph_pub=crypto.b64e(crypto.generate_ecdh_keypair()[1]),
        id_pub=crypto.b64e(b"\x42" * 32),
        nonce=crypto.b64e(b"\x03" * 16))
    host.handle_envelope(env, "ctrl")

    assert len(host.channel.published) == 1
    assert host.channel.published[0]["t"] == messages.REJECT
    assert host.channel.published[0]["code"] == messages.REASON_NICKNAME_TAKEN

    # oturum kara listeye alındı + yönetici alarmı düştü
    assert honeypot.is_banned(crypto.b64e(b"\x42" * 32))
    assert any(a["event"] == "honeypot-hello" for a in honeypot.recent_alerts())

    # kara listedeki oturumun sonraki denemesi de REDDEDİLİR
    env2 = messages.new_envelope(
        messages.HELLO,
        nick="masum-kullanici",
        eph_pub=crypto.b64e(crypto.generate_ecdh_keypair()[1]),
        id_pub=crypto.b64e(b"\x42" * 32),
        nonce=crypto.b64e(b"\x03" * 16))
    host.handle_envelope(env2, "ctrl")
    assert host.channel.published[-1]["t"] == messages.REJECT
    host.stop()


def test_decoy_room_rejects_and_bans_all():
    """Tuzak (decoy) odaya HER katılım denemesi = yetkisiz giriş."""
    decoy = honeypot.spawn_decoy_host("sistemci")
    try:
        assert decoy.is_honeypot is True
        assert decoy.room_code in config.HONEYPOT_TRAP_CODES
        decoy.channel = _DummyChannel()

        env = messages.new_envelope(
            messages.HELLO,
            nick="avci",                # normal, geçerli takma ad
            eph_pub=crypto.b64e(crypto.generate_ecdh_keypair()[1]),
            id_pub=crypto.b64e(b"\x55" * 32),
            nonce=crypto.b64e(b"\x03" * 16))
        decoy.handle_envelope(env, "ctrl")

        assert len(decoy.channel.published) == 1
        assert decoy.channel.published[0]["t"] == messages.REJECT
        assert honeypot.is_banned(crypto.b64e(b"\x55" * 32))
        alerts = honeypot.recent_alerts()
        assert any(a["event"] == "decoy-join-attempt" for a in alerts)
    finally:
        decoy.stop()


# ---------------------------------------------------------------- honeypot: UI


def _open_ui():
    import tkinter as tk
    from secretchat import ui
    try:
        root = tk.Tk()
    except Exception as exc:  # başsız ortam
        pytest.skip(f"Tk display yok: {exc}")
    app = ui.ChatApp(root)
    root.update_idletasks()
    return root, app


def test_ui_trap_code_trips_and_locks():
    root, app = _open_ui()
    try:
        app.nick_var.set("tester")
        app.code_var.set("vault")          # tuzak oda adı
        app._join_room()

        # katılım BAŞLATILMADI, oturum kilitlendi, aldatıcı yanıt verildi
        assert app.room is None
        assert app._honeypot_tripped is True
        assert "bulunamadı" in str(app.welcome_status.cget("text"))
        assert any(a["event"] == "honeypot-join-input"
                   for a in honeypot.recent_alerts())

        # kilitliyken normal kodla da giriş engelli
        app.code_var.set("3K7QX")
        app._join_room()
        assert app.room is None
        assert "kilitlendi" in str(app.welcome_status.cget("text"))
    finally:
        root.destroy()


def test_ui_hidden_input_catches_bots():
    root, app = _open_ui()
    try:
        assert app._honeypot_tripped is False
        # bot gizli form alanına yazar → anında algı
        app._hp_var.set("otomatik-doldurma")
        assert app._honeypot_tripped is True
        assert any(a["event"] == "honeypot-hidden-input"
                   for a in honeypot.recent_alerts())
        # kilit aktif: host/join bloke
        app.nick_var.set("tester")
        app._start_host()
        assert app.room is None
    finally:
        root.destroy()


def test_ui_trap_typing_is_logged_but_not_locked():
    """Tuzak adı yazılırken izlenir; kullanıcı henüz kilitlemez (yanlışlık azalt)."""
    root, app = _open_ui()
    try:
        app.code_var.set("admin-secrets")
        assert any(a["event"] == "honeypot-join-input-typing"
                   for a in honeypot.recent_alerts())
        assert app._honeypot_tripped is False
    finally:
        root.destroy()
