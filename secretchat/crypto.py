"""Uçtan uca şifreleme katmanı.

Anahtar takası : X25519 (ECDH)  — hem 1-1 el sıkışma hem ECIES sarma
Türetme        : HKDF-SHA256
Sohbet şifresi : AES-256-GCM (AEAD; gizlilik + bütünlük)
Kimlik         : her kullanıcı Ed25519 imza anahtarı üretir (SAS doğrulaması)

Relay/broker yalnızca şifreli zarfları taşır; içeriği asla göremez.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from typing import Optional, Tuple

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import (X25519PrivateKey,
                                                              X25519PublicKey)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from nacl.public import PrivateKey as BoxPrivateKey
from nacl.public import PublicKey as BoxPublicKey
from nacl.signing import SigningKey, VerifyKey

from .config import (ECIES_NONCE_LEN, HKDF_INFO_B, HKDF_INFO_N, HKDF_INFO_R,
                     HKDF_INFO_S, PBKDF2_ITERATIONS)

# ---------------------------------------------------------------- ECDH (X25519)


def generate_ecdh_keypair() -> Tuple[bytes, bytes]:
    """X25519 anahtar çifti üret: (priv, pub)."""
    priv = X25519PrivateKey.generate()
    pub = priv.public_key().public_bytes_raw()
    return priv.private_bytes_raw(), pub


def derive_shared_secret(my_priv: bytes, their_pub: bytes) -> bytes:
    """ECDH paylaşılan sırrını hesapla (32 byte)."""
    priv = X25519PrivateKey.from_private_bytes(my_priv)
    return priv.exchange(X25519PublicKey.from_public_bytes(their_pub))


# ---------------------------------------------------------------- HKDF türetme


def _hkdf(secret: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    """HKDF-SHA256 türetme yardımcıcısı."""
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt,
                info=info).derive(secret)


def derive_session_key(shared_secret: bytes) -> bytes:
    """ECDH sırrından 1-1 oturum AES-256 anahtarı."""
    return _hkdf(shared_secret, b"", HKDF_INFO_S)


def derive_broadcast_key(shared_secret: bytes) -> bytes:
    """Grup (yayın) anahtarını türet."""
    return _hkdf(shared_secret, b"", HKDF_INFO_B)


def derive_nonce_salt(shared_secret: bytes) -> bytes:
    """Nonce tuzu: client nonce'u tuzla, host rastgeleliğini kontrol etsin."""
    return _hkdf(shared_secret, b"", HKDF_INFO_N)


def derive_room_key(code: str) -> bytes:
    """[GÜVENLİK UYARISI] Oda kodundan deterministik oda anahtarı.

    DEPRECATED — artık KULLANILMIYOR. Oda kodu, MQTT topic adında broker'a
    açık olduğu için koddan türetilen herhangi bir anahtar E2EE'yi bypass
    ederdi (broker tüm grup trafiğini çözebilir). Oda anahtarları
    `room.Host` içinde `secrets.token_bytes(32)` ile rastgele üretilir;
    yalnızca ECIES ile üyelere dağıtılır. İşlev yalnızca geri uyumluluk
    için tutulur.
    """
    digest = hashlib.sha256(HKDF_INFO_R + b":" + code.encode("ascii")).digest()
    return digest


# ---------------------------------------------------------------- AES-GCM


def aesgcm_encrypt(key: bytes, plaintext: bytes) -> bytes:
    """AES-256-GCM şifrele; dönen blob = nonce(12) || ciphertext+tag."""
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def aesgcm_decrypt(key: bytes, blob: bytes) -> bytes:
    """AES-256-GCM çöz; blob'un ilk 12 byte'ı nonce'tur."""
    if len(blob) < 12 + 16:
        raise ValueError("şifreli veri çok kısa")
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ct, None)


# ---------------------------------------------------------------- Ed25519 <-> X25519


def ed25519_pub_to_x25519(ed25519_pub: bytes) -> bytes:
    """Ed25519 açık anahtarını X25519 açık anahtarına dönüştür."""
    vk = VerifyKey(ed25519_pub)
    return bytes(vk.to_curve25519_public_key())


def ed25519_priv_to_x25519(ed25519_priv: bytes) -> bytes:
    """Ed25519 gizli anahtarını X25519 gizli anahtarına dönüştür."""
    sk = SigningKey(ed25519_priv)
    return bytes(sk.to_curve25519_private_key())


# ---------------------------------------------------------------- ECIES
# Akış: geçici (ephemeral) X25519 anahtarı üret -> alıcının pub'ı ile ECDH ->
# HKDF ile AES anahtarı türet -> AES-GCM ile şifrele.
# Zarf: ephemeral_pub(32) || nonce(12) || ct+tag


def ecies_encrypt(recipient_x25519_pub: bytes, plaintext: bytes) -> bytes:
    """Alıcının X25519 açık anahtarıyla şifrele (ECIES)."""
    eph_priv, eph_pub = generate_ecdh_keypair()
    shared = derive_shared_secret(eph_priv, recipient_x25519_pub)
    key = _hkdf(shared, eph_pub, b"secretchat-ecies-v1")
    nonce = os.urandom(ECIES_NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return eph_pub + nonce + ct


def ecies_decrypt(recipient_x25519_priv: bytes, blob: bytes) -> bytes:
    """ECIES zarfını alıcının X25519 gizli anahtarıyla çöz."""
    eph_pub = blob[:32]
    nonce = blob[32:32 + ECIES_NONCE_LEN]
    ct = blob[32 + ECIES_NONCE_LEN:]
    shared = derive_shared_secret(recipient_x25519_priv, eph_pub)
    key = _hkdf(shared, eph_pub, b"secretchat-ecies-v1")
    return AESGCM(key).decrypt(nonce, ct, None)


# ---------------------------------------------------------------- Ed25519 imza


def generate_signing_keypair() -> Tuple[bytes, bytes]:
    """Ed25519 anahtar çifti üret: (priv, pub)."""
    sk = SigningKey.generate()
    return bytes(sk), bytes(sk.verify_key)


def sign(priv: bytes, data: bytes) -> bytes:
    """Ed25519 imzala."""
    return bytes(SigningKey(priv).sign(data).signature)


def verify(pub: bytes, data: bytes, signature: bytes) -> bool:
    """Ed25519 imza doğrula."""
    try:
        VerifyKey(pub).verify(data, signature)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- SAS


def compute_sas(local_id_pub: bytes, remote_id_pub: bytes) -> str:
    """Kısa doğrulama kodu (SAS): iki taraf aynı 6 haneli sayıyı görür."""
    lo, hi = sorted((local_id_pub, remote_id_pub))
    digest = hashlib.sha256(b"secretchat-sas-v1" + lo + hi).digest()
    return f"{int.from_bytes(digest[:4], 'big') % 1_000_000:06d}"


# ---------------------------------------------------------------- Kodlama


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


# ---------------------------------------------------------------- Şifreli kayıt


def derive_log_key(password: str, salt: bytes) -> bytes:
    """Kayıt dosyası şifresinden AES anahtarı türet (PBKDF2)."""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=PBKDF2_ITERATIONS)
    return kdf.derive(password.encode("utf-8"))


def new_salt() -> bytes:
    """PBKDF2 için yeni tuz."""
    return secrets.token_bytes(16)


def constant_time_eq(a: bytes, b: bytes) -> bool:
    """Zaman saldırısına dayanıklı bayt karşılaştırma."""
    return hmac.compare_digest(a, b)
