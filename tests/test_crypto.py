"""Kripto katmanı testleri: pytest ile çalıştırın."""
from __future__ import annotations

import os

from secretchat import crypto


def test_ecdh_shared_secret_matches():
    a_priv, a_pub = crypto.generate_ecdh_keypair()
    b_priv, b_pub = crypto.generate_ecdh_keypair()
    s1 = crypto.derive_shared_secret(a_priv, b_pub)
    s2 = crypto.derive_shared_secret(b_priv, a_pub)
    assert s1 == s2 and len(s1) == 32


def test_aes_roundtrip():
    key = os.urandom(32)
    blob = crypto.aesgcm_encrypt(key, "merhaba dünya".encode("utf-8"))
    assert crypto.aesgcm_decrypt(key, blob) == "merhaba dünya".encode("utf-8")


def test_aes_wrong_key_fails():
    key = os.urandom(32)
    blob = crypto.aesgcm_encrypt(key, b"x")
    try:
        crypto.aesgcm_decrypt(os.urandom(32), blob)
        raised = False
    except Exception:
        raised = True
    assert raised


def test_ecies_roundtrip():
    priv, pub = crypto.generate_ecdh_keypair()
    blob = crypto.ecies_encrypt(pub, "sır".encode("utf-8"))
    assert crypto.ecies_decrypt(priv, blob) == "sır".encode("utf-8")


def test_sign_verify():
    priv, pub = crypto.generate_signing_keypair()
    sig = crypto.sign(priv, b"mesaj")
    assert crypto.verify(pub, b"mesaj", sig)
    assert not crypto.verify(pub, "başka".encode("utf-8"), sig)


def test_sas_symmetric():
    a = os.urandom(32)
    b = os.urandom(32)
    assert crypto.compute_sas(a, b) == crypto.compute_sas(b, a)
    assert len(crypto.compute_sas(a, b)) == 6


def test_ed25519_to_x25519_roundtrip():
    sign_priv, sign_pub = crypto.generate_signing_keypair()
    x_priv = crypto.ed25519_priv_to_x25519(sign_priv)
    x_pub = crypto.ed25519_pub_to_x25519(sign_pub)
    shared1 = crypto.derive_shared_secret(x_priv, x_pub)
    shared2 = crypto.derive_shared_secret(
        crypto.ed25519_priv_to_x25519(crypto.generate_signing_keypair()[0]), x_pub)
    assert len(shared1) == 32 and len(shared2) == 32
