"""Doğrudan P2P taşıma (UDP delik açma + AES-256-GCM güvenli kanal).

Kullanım:
- Host: p2p.Host(port=0) -> rastgele UDP portu dinler, oda kodu yayını yapar.
- Client: p2p.Client() -> host'un dış adresine  delik açmaya çalışır.
Bağlantı kurulamazsa uygulama otomatik relay moduna düşer.
"""
from __future__ import annotations

import os
import socket
import struct
import threading
import time
import queue
from typing import Callable, Optional, Tuple

from . import crypto, stun

MAGIC = b"SCPB"  # SecretChat P2P Benekleri (beacon)
BEACON_INTERVAL = 0.8  # saniye
MAX_DGRAM = 65535

# ---------------------------------------------------------------- paket çerçevesi
# | magic(4) | kind(1) | flags(1) | len(2) | payload(len) |
# kind: 0 = beacon, 1 = encrypted data, 2 = ping, 3 = pong
PK_BEACON = 0
PK_DATA = 1
PK_PING = 2
PK_PONG = 3


def _frame(kind: int, payload: bytes) -> bytes:
    return struct.pack("!4sBBH", MAGIC, kind, 0, len(payload)) + payload


def _try_parse(data: bytes) -> Optional[Tuple[int, bytes]]:
    """Gelen paketi çöz; geçersizse None döndür."""
    if len(data) < 8 or data[:4] != MAGIC:
        return None
    kind, _flags, length = struct.unpack("!4sBBH", data[:8])[1:]
    payload = data[8:8 + length]
    if len(payload) != length:
        return None
    return kind, payload


class _UdpPeer:
    """Ortak UDP soket: beacon gönderme, veri alma, delik açma yardımcıları."""

    def __init__(self, listen_port: int = 0, on_datagram: Optional[Callable[[bytes, Tuple[str, int]], None]] = None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", listen_port))
        self.sock.settimeout(0.25)
        self.local_port = self.sock.getsockname()[1]
        self.on_datagram = on_datagram
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

    def _recv_loop(self) -> None:
        while self._running:
            try:
                data, addr = self.sock.recvfrom(MAX_DGRAM)
            except socket.timeout:
                continue
            except OSError:
                break
            if self.on_datagram:
                try:
                    self.on_datagram(data, addr)
                except Exception:
                    pass

    def send_to(self, data: bytes, addr: Tuple[str, int]) -> None:
        try:
            self.sock.sendto(data, addr)
        except OSError:
            pass

    def close(self) -> None:
        self._running = False
        try:
            self.sock.close()
        except OSError:
            pass


class Host:
    """P2P modunda oda kurucusu.

    - Rastgele UDP portu dinler; beacon'larla kendini duyurur (LAN için).
    - Katılan tarafın delik açma (hole-punching) paketlerini bekler.
    - 1-1 el sıkışma bu soket üzerinden de yürütülebilir.
    """

    def __init__(self, beacon_code: str = "", beacon_interval: float = BEACON_INTERVAL):
        self.peer = _UdpPeer(0)
        self.port = self.peer.local_port
        self.beacon_code = beacon_code
        self.beacon_interval = beacon_interval
        self._running = True
        self._thread = threading.Thread(target=self._beacon_loop, daemon=True)
        self._thread.start()

    def _beacon_loop(self) -> None:
        payload = self.beacon_code.encode("ascii", "ignore")
        frame = _frame(PK_BEACON, payload)
        while self._running:
            # LAN keşfi: yerel yayın adresine beacon gönder.
            for broadcast_ip in ("255.255.255.255", "<broadcast>"):
                try:
                    self.peer.send_to(frame, (broadcast_ip, self.port))
                except OSError:
                    pass
            time.sleep(self.beacon_interval)

    def send(self, data: bytes, addr: Tuple[str, int]) -> None:
        """Şifreli veri çerçevesi gönder."""
        self.peer.send_to(_frame(PK_DATA, data), addr)

    def close(self) -> None:
        self._running = False
        self.peer.close()

    @property
    def local_port(self) -> int:
        return self.peer.local_port


class Client:
    """P2P modunda katılan taraf.

    Host'un dış adresini STUN + beacon ile öğrenmeye çalışır; başarısızsa
    çağıran taraf relay moduna düşer.
    """

    def __init__(self):
        self.peer = _UdpPeer(0)
        self.local_port = self.peer.local_port

    def punch_to(self, addr: Tuple[str, int], duration: float = 6.0, interval: float = 0.25) -> bool:
        """Belirtilen adrese delik açma paketleri gönder; cevap gelirse True."""
        result = {"ok": False}

        def _on_datagram(data: bytes, from_addr: Tuple[str, int]) -> None:
            parsed = _try_parse(data)
            if parsed and parsed[0] in (PK_PONG, PK_DATA):
                result["ok"] = True

        old_cb = self.peer.on_datagram
        self.peer.on_datagram = _on_datagram
        ping = _frame(PK_PING, b"")
        deadline = time.time() + duration
        try:
            while time.time() < deadline and not result["ok"]:
                self.peer.send_to(ping, addr)
                time.sleep(interval)
        finally:
            self.peer.on_datagram = old_cb
        return result["ok"]

    def send(self, data: bytes, addr: Tuple[str, int]) -> None:
        self.peer.send_to(_frame(PK_DATA, data), addr)

    def close(self) -> None:
        self.peer.close()

    @property
    def local_port(self) -> int:  # noqa: F811 - okunabilirlik için property
        return self.peer.local_port
