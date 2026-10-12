"""Protokol ve oturum katmanı testleri (ağ olmadan)."""
from __future__ import annotations

import json

from secretchat import crypto, messages
from secretchat.room import generate_room_code, sas_of


def test_envelope_roundtrip():
    env = messages.new_envelope(messages.HELLO, nick="ayse")
    data = messages.encode_envelope(env)
    parsed = messages.decode_envelope(data)
    assert parsed["t"] == messages.HELLO
    assert parsed["nick"] == "ayse"


def test_envelope_rejects_garbage():
    for bad in (b"", b"{", b"[]"):
        try:
            messages.decode_envelope(bad)
            ok = False
        except ValueError:
            ok = True
        assert ok


def test_chat_payload_has_nonce():
    payload = messages.make_chat_payload("mehmet", "selam")
    data = json.loads(payload)
    assert data["sender"] == "mehmet"
    assert data["text"] == "selam"
    assert data["nonce"]  # tekrar saldırılarına karşı rastgele


def test_room_code_shape():
    code = generate_room_code()
    assert len(code) == 5
    assert all(c in "23456789ABCDEFGHJKMNPQRSTUVWXYZ" for c in code)


def test_sas_matches_between_parties():
    priv, pub = crypto.generate_signing_keypair()
    _, pub2 = crypto.generate_signing_keypair()
    assert sas_of(pub, pub2) == sas_of(pub2, pub)


def test_full_handshake_crypto_flow():
    """Host ve client'ın gerçek el sıkışma adımlarını simüle et."""
    # 1) Katılan HELLO gönderir (geçici ECDH + kimlik + nonce)
    c_eph = crypto.generate_ecdh_keypair()
    c_id = crypto.generate_signing_keypair()
    nonce = b"\x11" * 16

    # 2) Host: paylaşılan sırrı türetir, nonce'u şifreleyip kanıtlar
    h_eph = crypto.generate_ecdh_keypair()
    h_shared = crypto.derive_shared_secret(h_eph[0], c_eph[1])
    h_session = crypto.derive_session_key(h_shared)
    proof = crypto.aesgcm_encrypt(h_session, nonce)

    # 3) Katılan: aynı sırrı türetip kanıtı çözer
    c_shared = crypto.derive_shared_secret(c_eph[0], h_eph[1])
    c_session = crypto.derive_session_key(c_shared)
    assert crypto.aesgcm_decrypt(c_session, proof) == nonce
    assert h_session == c_session

    # 4) Grup anahtarı ECIES ile sarılır ve açılır
    room_key = b"\xab" * 32
    wrap = crypto.ecies_encrypt(crypto.ed25519_pub_to_x25519(c_id[1]), room_key)
    opened = crypto.ecies_decrypt(crypto.ed25519_priv_to_x25519(c_id[0]), wrap)
    assert opened == room_key

    # 5) Grup mesajı oda anahtarıyla şifrelenir
    blob = crypto.aesgcm_encrypt(room_key, "selam".encode())
    assert crypto.aesgcm_decrypt(room_key, blob) == b"selam"
