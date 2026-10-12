"""Uygulama genelinde sabitler ve varsayılan ayarlar."""
from __future__ import annotations

import os

# ---------------------------------------------------------------- Ağ / Relay
# Herkese açık test broker'ı; TLS (8883) üzerinden çalışır.
DEFAULT_BROKER = "broker.emqx.io"
DEFAULT_PORT = 8883
WS_BROKER = "broker.emqx.io"
WS_PORT = 8084  # TLS-over-WebSocket

# Sinyalleşme topic'leri (relay mesajları da buradan geçer).
SIGNAL_PREFIX = "sc/v3/"

# Relay modu: birkaç kB/sn'lik sohbet trafiği için broker'ın kendisi aktarıcı
# olur. Mesaj içeriği zaten uçtan uca şifreli olduğu için broker düz metni
# asla göremez.
RELAY_TICK = 0.10  # saniye

# ---------------------------------------------------------------- Oda kodu
ROOM_CODE_LENGTH = 5  # örn. "3K7QX"
ROOM_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # okunaklı set

# ---------------------------------------------------------------- Kripto
PBKDF2_ITERATIONS = 600_000  # şifreli kayıt dosyası için
ECIES_NONCE_LEN = 12
HKDF_INFO_B = b"secretchat-broadcast-key-v1"
HKDF_INFO_S = b"secretchat-session-key-v1"
HKDF_INFO_N = b"secretchat-nonce-salt-v1"
HKDF_INFO_R = b"secretchat-room-key-v1"

# ---------------------------------------------------------------- Zaman aşımları
ANNOUNCE_POLL = 1.0  # saniye - oda listeleme yoklaması
HANDSHAKE_TIMEOUT = 12.0  # saniye
CONNECT_TIMEOUT = 12.0  # saniye
JOIN_ACK_WINDOW = 15.0  # saniye - katılanın ACK bekleme penceresi
HOST_ACK_TIMEOUT = 120.0  # saniye - kurucunun ACK bekleme penceresi

# ---------------------------------------------------------------- Kayıt
LOG_DIR = os.path.join(os.path.expanduser("~"), "Documents", "SecretChat")
REDACT_NOTE = "  (sansürlü)"

# ---------------------------------------------------------------- Güvenlik ve Doğrulama
MAX_MESSAGE_LENGTH = 4000      # Mesaj başı maksimum karakter
NICKNAME_MIN_LEN = 2           # Minimum takma ad uzunluğu
NICKNAME_MAX_LEN = 24          # Maksimum takma ad uzunluğu
RATE_LIMIT_BURST = 5           # Ani gönderim tavanı (token bucket)
RATE_LIMIT_RATE = 2.0          # Saniyede yenilenen token miktarı
MAX_INBOX_SIZE = 1000          # MQTT gelen mesaj kuyruğu üst sınırı
MAX_CLOCK_SKEW = 180.0         # Tekrar saldırılarına karşı zaman damgası penceresi (saniye)

# ---------------------------------------------------------------- Honeypot (siber tuzak)
# Cazip görünümlü sahte oda adları / takma adlar / oda kodları: bu değerlerle
# giriş denemesi yapan oturumlar saldırgan kabul edilip kara listeye alınır.
HONEYPOT_TRAP_ROOMS = ("admin-secrets", "global-config", "vault",
                       "root-panel", "passwords", "secrets")
HONEYPOT_TRAP_NICKS = ("vault-admin", "sysadmin", "security-team", "root-access")
# Dekoy (yem) oda kodları: oda kodu alfabesine uyan cazip 5-haneli kodlar
HONEYPOT_TRAP_CODES = ("S3CR7", "P4SSW", "K3YS3", "B4NK3")
HONEYPOT_BAN_TTL = 3600.0      # kara liste süresi (saniye)
HONEYPOT_LOG_NAME = "admin-security.log"  # yönetici alarm günlüğü
HONEYPOT_MAX_ALERTS = 500      # RAM'de tutulan alarm kaydı üst sınırı

# Gelen trafik denetimi (inbound flood / DoS koruması)
INBOUND_BURST = 15.0           # HELLO gibi kritik zarflarda ani sel sınırı
INBOUND_RATE = 3.0             # Saniyede yenilenen gelen-kota
MAX_SEEN_TOKENS = 4096         # Tekrar-savunması önbelleği (mid/nonce) üst sınırı
MAX_UI_TEXT_LINES = 3000       # Arayüz metin tamponu (satır) — bellek tavanı
