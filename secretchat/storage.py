"""İsteğe bağlı sohbet kaydı: RAM modu (varsayılan) veya yerel dosya.

RAM modunda hiçbir bayt diske yazılmaz; uygulama kapanınca her şey silinir.
Kayıt açıksa şifresi çözülmüş metin, kullanıcının seçtiği .txt/.log dosyasına
UTF-8 olarak eklenir. Alternatif olarak parola ile şifreli .log da yapılabilir.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import List, Optional

from . import config

logger = logging.getLogger("secretchat.storage")


class ChatStore:
    """Mesaj arşivi. Varsayılan: yalnızca RAM."""

    def __init__(self, max_in_memory: int = 5000):
        self._lock = threading.Lock()
        self._memory: List[str] = []
        self._max = max_in_memory
        self.file_path: Optional[str] = None  # None => kayıt kapalı

    # ------------------------------------------------------------- kayıt modu

    @property
    def recording(self) -> bool:
        return self.file_path is not None

    def set_recording(self, path: Optional[str]) -> None:
        """Kayıt hedefini ayarla (None = RAM modu)."""
        with self._lock:
            if path:
                # Yol temizliği ve mutlak yola dönüştürme
                clean_path = os.path.abspath(path)
                parent_dir = os.path.dirname(clean_path)
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)
                self.file_path = clean_path
                if self._memory:
                    # Daha önce tutulan mesajları da dosyaya boşalt.
                    try:
                        with open(self.file_path, "a", encoding="utf-8") as fh:
                            fh.write("\n".join(self._memory) + "\n")
                        self._memory = []
                    except OSError as exc:
                        logger.error("Kayıt dosyasına boşaltma hatası (%s): %s", self.file_path, exc)
            else:
                self.file_path = None

    # ------------------------------------------------------------- mesaj akışı

    def append(self, line: str) -> None:
        """Mesajı sakla: kayıt açıksa dosyaya, değilse RAM'e."""
        stamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{stamp}] {line}"
        with self._lock:
            self._memory.append(entry)
            if len(self._memory) > self._max:
                self._memory = self._memory[-self._max // 2:]
        if self.file_path:
            self._flush_to_disk(entry)

    def _flush_to_disk(self, entry: str) -> None:
        try:
            with open(self.file_path, "a", encoding="utf-8") as fh:
                fh.write(entry + "\n")
        except OSError as exc:
            logger.error("Kayıt diske yazılamadı: %s", exc)

    # ------------------------------------------------------------- temizlik

    def wipe(self) -> None:
        """RAM'deki her şeyi sil (oda feshi / çıkış)."""
        with self._lock:
            self._memory.clear()

    def dump_memory(self) -> List[str]:
        """RAM'deki kopyayı döndür (test/ekran amaçlı)."""
        with self._lock:
            return list(self._memory)

    def default_log_path(self) -> str:
        """Varsayılan log dosyası yolu."""
        os.makedirs(config.LOG_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return os.path.join(config.LOG_DIR, f"sohbet-{stamp}.log")
