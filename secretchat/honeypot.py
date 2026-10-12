"""Honeypot (siber tuzak) katmanı.

Savunma odaklı mimarinin tuzak bileşeni:

1. **Tuzak odalar / kodlar:** `config.HONEYPOT_TRAP_ROOMS` (admin-secrets,
   global-config, vault, ...) cazip oda adlarıdır; `config.HONEYPOT_TRAP_CODES`
   oda kodu alfabesine uyan yem kodlardır. `spawn_decoy_host()` bunlarla sahte
   bir oda kurar — tuzak odaya HELLO gönderen herkes yetkisiz giriş denemesi
   sayılır ve anında reddedilip kara listeye alınır.

2. **Saldırgan tespiti & otomatik ban:** `alert()` bir olayı hem yönetici
   günlüğüne (`~/Documents/SecretChat/admin-security.log`) yazar, hem RAM'deki
   son alarm listesine ekler, hem de istenirse oturumu (session kimliği =
   Ed25519 id_pub) `HONEYPOT_BAN_TTL` süresince kara listeye alır.
   Host, kara listeye alınmış oturumlardan gelen HELLO'ları işlemekten
   tamamen vazgeçer (bağlantı isteği anında kesilir).

3. **Gizli girdi tuzağı (hidden input):** Arayüzde ekran dışı yerleştirilen
   (`place(x=-9000, y=-9000)`) gizli bir Entry, normal kullanıcı tarafından
   görülemez/dokunulamaz. Bot veya otomasyon aracı tüm formları doldurmaya
   kalkışınca bu alana yazar → izleyici (trace) alarmı tetikler ve oturum
   kilitlenir.

Not: MQTT broker'ı istemci IP'lerini gizler (biz de görmeyiz); bu yüzden
"kara liste" oturum kimliği (id_pub) / takma ad / yerel oturum bazlıdır.
Ağ katmanında IP ban'ı yalnızca kendi broker'ınızla mümkündür.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

from . import config

logger = logging.getLogger("secretchat.honeypot")

# ---------------------------------------------------------------- normalize


def _normalize(text: str) -> str:
    """Tuzak eşleşmesi için normalizasyon: küçük harf + ayraç temizliği."""
    return re.sub(r"[-_\s.]", "", str(text).strip().lower())


_TRAP_ROOMS = frozenset(_normalize(r) for r in config.HONEYPOT_TRAP_ROOMS)
_TRAP_NICKS = frozenset(_normalize(n) for n in config.HONEYPOT_TRAP_NICKS)
_TRAP_CODES = frozenset(c.strip().upper() for c in config.HONEYPOT_TRAP_CODES)


def is_trap_room(code: str) -> bool:
    """Girdi tuzak oda adı/kodundan mı? (admin-secrets, vault, S3CR7, ...)"""
    if not code:
        return False
    raw = str(code).strip()
    return _normalize(raw) in _TRAP_ROOMS or raw.upper() in _TRAP_CODES


def is_trap_nick(nick: str) -> bool:
    """Katılım takma adı tuzak adlardan mı? (vault-admin, sysadmin, ...)"""
    if not nick:
        return False
    return _normalize(nick) in _TRAP_NICKS


def trap_rooms() -> Tuple[str, ...]:
    """Tanımlı tuzak oda adları (rapor/monitoring için)."""
    return config.HONEYPOT_TRAP_ROOMS


# ---------------------------------------------------------------- kara liste


class Blacklist:
    """Thread-safe, TTL'li oturum kara listesi."""

    def __init__(self, ttl: float = config.HONEYPOT_BAN_TTL):
        self.ttl = float(ttl)
        self._entries: Dict[str, Tuple[float, str]] = {}
        self._lock = threading.Lock()

    def ban(self, key: str, reason: str = "") -> None:
        if not key:
            return
        with self._lock:
            self._entries[key] = (time.time() + self.ttl, reason)

    def is_banned(self, key: str) -> bool:
        if not key:
            return False
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            expires, _reason = entry
            if expires < time.time():
                del self._entries[key]
                return False
            return True

    def reason(self, key: str) -> str:
        with self._lock:
            entry = self._entries.get(key)
            return entry[1] if entry else ""

    def sweep(self) -> None:
        """Süresi dolan kayıtları temizle (bellek hijyeni)."""
        now = time.time()
        with self._lock:
            for k in [k for k, (exp, _) in self._entries.items() if exp < now]:
                del self._entries[k]

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_blacklist = Blacklist()
_alerts: Deque[Dict[str, Any]] = deque(maxlen=config.HONEYPOT_MAX_ALERTS)
_alert_lock = threading.Lock()

# Ela kareleden tek uyarı (UI trace'i tuş başına tetiklemesin)
_last_alert_key: Optional[str] = None
_last_alert_lock = threading.Lock()


# ---------------------------------------------------------------- alarm


def _admin_log(event: str, detail: str) -> None:
    """Yönetici günlüğüne yaz (dönen sistemlerde sessizce geç)."""
    logger.warning("[HONEYPOT] %s | %s", event, detail)
    try:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        path = os.path.join(config.LOG_DIR, config.HONEYPOT_LOG_NAME)
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".1")  # basit rotasyon
        with open(path, "a", encoding="utf-8") as fh:
            stamp = datetime.now().isoformat(timespec="seconds")
            fh.write(f"{stamp} | {event} | {detail}\n")
    except OSError:
        pass


def alert(event: str, detail: str, ban_key: str = "",
          dedupe: bool = False) -> None:
    """Tespit kaydı: yönetici günlüğü + RAM listesi + isteğe bağlı ban.

    `dedupe=True` arka arkaya aynı anahtarla tetiklenen trace alarmlarını
    tekilleştirir (tuş başına kopya kayıt önlenir).
    """
    global _last_alert_key
    if dedupe:
        key = f"{event}:{detail}"
        with _last_alert_lock:
            if key == _last_alert_key:
                return
            _last_alert_key = key

    record = {"ts": time.time(), "event": event, "detail": detail,
              "ban_key": ban_key}
    with _alert_lock:
        _alerts.append(record)
    _admin_log(event, detail)
    if ban_key:
        _blacklist.ban(ban_key, reason=event)


def is_banned(session_key: str) -> bool:
    """Oda kurucusu tarafı: bu oturum kara listede mi?"""
    return _blacklist.is_banned(session_key)


def recent_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    """Son alarmlar (yönetici paneli / test için)."""
    with _alert_lock:
        items = list(_alerts)
    return items[-limit:]


def reset() -> None:
    """Test yardımcı: kara liste ve alarmları sıfırla."""
    global _last_alert_key
    _blacklist._entries.clear()
    with _alert_lock:
        _alerts.clear()
    with _last_alert_lock:
        _last_alert_key = None


def blacklist() -> Blacklist:
    """Ana kara liste nesnesi (housekeeping/test erişimi)."""
    return _blacklist


# ---------------------------------------------------------------- dekoy oda


def spawn_decoy_host(nickname: str = "sistemci", **kwargs):  # -> room.Host
    """Tuzak kodlu sahte bir oda (decoy) kur.

    `config.HONEYPOT_TRAP_CODES` içinden rastgele geçerli bir oda koduyla
    Host oluşturur ve `is_honeypot=True` işaretler. Bu odaya katılım
    denemesi yapan herkes (oda dizini/brute-force tarayıcıları dahil)
    yetkisiz giriş sayılır: REJECT + kara liste + yönetici alarmı.
    """
    from .room import Host  # yerel import: room -> honeypot döngüsünü önler

    code = secrets.choice(config.HONEYPOT_TRAP_CODES)
    host = Host(nickname, room_code=code, **kwargs)
    host.is_honeypot = True
    _admin_log("decoy-room-created", f"tuzak oda kuruldu: {code} (host={nickname})")
    return host
