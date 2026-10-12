"""Siber güvenlik ve savunma katmanı: Rate Limiting, Anti-Spam ve Oturum Denetimi.

Token bucket algoritması ile istemci ve sunucu tarafı spam/DoS girişimlerini
engeller, aşırı istek gönderimlerini sınırlandırır.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict

from . import config

logger = logging.getLogger("secretchat.security")


class RateLimiter:
    """Thread-safe Token Bucket Rate Limiter."""

    def __init__(self, capacity: float = config.RATE_LIMIT_BURST,
                 fill_rate: float = config.RATE_LIMIT_RATE):
        self.capacity = float(capacity)
        self.fill_rate = float(fill_rate)
        self.tokens = float(capacity)
        self.last_update = time.monotonic()
        self._lock = threading.Lock()

    def allow(self, cost: float = 1.0) -> bool:
        """Belirtilen maliyet için kota müsait mi kontrol et."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now

            # Yeni token'ları ekle
            self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)

            if self.tokens >= cost:
                self.tokens -= cost
                return True
            logger.warning("Rate limit aşıldı! Mevcut token: %.2f, İstenen: %.2f", self.tokens, cost)
            return False

    def time_until_available(self, cost: float = 1.0) -> float:
        """Gereken token için beklenmesi gereken tahmini süre (saniye)."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            cur_tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)
            if cur_tokens >= cost:
                return 0.0
            deficit = cost - cur_tokens
            return deficit / self.fill_rate


class KeyedRateLimiter:
    """Peer / IP / Kullanıcı bazlı çoklu Token Bucket yöneticisi."""

    def __init__(self, capacity: float = config.RATE_LIMIT_BURST,
                 fill_rate: float = config.RATE_LIMIT_RATE,
                 max_keys: int = 500):
        self.capacity = capacity
        self.fill_rate = fill_rate
        self.max_keys = max_keys
        self._limiters: Dict[str, RateLimiter] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, cost: float = 1.0) -> bool:
        with self._lock:
            if key not in self._limiters:
                # Bellek sızıntısını önlemek için anahtar sınırını koru
                if len(self._limiters) >= self.max_keys:
                    self._limiters.clear()
                self._limiters[key] = RateLimiter(self.capacity, self.fill_rate)
            limiter = self._limiters[key]
        return limiter.allow(cost)

    def remove(self, key: str) -> None:
        with self._lock:
            self._limiters.pop(key, None)
