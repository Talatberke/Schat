"""STUN istemcisi: dış IP/port keşfi ve NAT tipi tespiti (RFC 5389).

P2P modunda hole-punching öncesi dış adres öğrenmek için kullanılır;
relay modunda gerek yoktur.
"""
from __future__ import annotations

import os
import socket
import struct
from typing import Optional, Tuple

# --------------------------------------------------------------- RFC 5389

MAGIC_COOKIE = b"\x21\x12\xa4\x42"

# STUN mesaj türleri
BINDING_REQUEST = 0x0001
BINDING_RESPONSE = 0x0101

# Öznitelikler
ATTR_XOR_MAPPED_ADDRESS = 0x0020
ATTR_MAPPED_ADDRESS = 0x0001

PUBLIC_STUN_SERVERS = [
    "stun.l.google.com:19302",
    "stun1.l.google.com:19302",
    "stun.cloudflare.com:3478",
]


def _txn_id() -> bytes:
    return os.urandom(12)


def build_binding_request() -> bytes:
    """STUN Binding Request paketi üret (20 byte başlık)."""
    return struct.pack("!HH", BINDING_REQUEST, 0) + MAGIC_COOKIE + _txn_id()


def _parse_xor_address(value: bytes, txn_id: bytes) -> Tuple[str, int]:
    """XOR-MAPPED-ADDRESS özniteliğini çöz."""
    family = value[1]
    port = struct.unpack("!H", value[2:4])[0] ^ struct.unpack("!H", MAGIC_COOKIE[:2])[0]
    if family == 0x01:  # IPv4
        addr = bytes(b ^ m for b, m in zip(value[4:8], MAGIC_COOKIE))
        return socket.inet_ntoa(addr), port
    if family == 0x02:  # IPv6
        addr = bytes(b ^ m for b, m in zip(value[4:20], MAGIC_COOKIE + txn_id))
        return socket.inet_ntop(socket.AF_INET6, addr), port
    raise ValueError("bilinmeyen adres ailesi")


def parse_binding_response(data: bytes, txn_id: bytes) -> Optional[Tuple[str, int]]:
    """Binding Response içinden xor-mapped (yoksa mapped) adresi çıkar."""
    if len(data) < 20:
        return None
    msg_type, msg_len, magic = struct.unpack("!HHI", data[:8])
    if msg_type != BINDING_RESPONSE or data[4:8] != MAGIC_COOKIE[:4]:
        return None
    if data[8:20] != txn_id:
        return None
    offset = 20
    end = 20 + msg_len
    while offset + 4 <= end:
        attr_type, attr_len = struct.unpack("!HH", data[offset:offset + 4])
        value = data[offset + 4:offset + 4 + attr_len]
        if attr_type == ATTR_XOR_MAPPED_ADDRESS:
            return _parse_xor_address(value, txn_id)
        if attr_type == ATTR_MAPPED_ADDRESS and len(value) >= 8:
            family = value[1]
            port = struct.unpack("!H", value[2:4])[0]
            if family == 0x01:
                return socket.inet_ntoa(value[4:8]), port
        offset += 4 + attr_len + ((4 - attr_len % 4) % 4)
    return None


def discover_external_address(timeout: float = 2.5) -> Optional[Tuple[str, int]]:
    """Genel STUN sunucularından sırayla dış IP:port öğrenmeye çalış."""
    req = build_binding_request()
    txn = req[8:20]
    for server in PUBLIC_STUN_SERVERS:
        host, _, port_s = server.partition(":")
        port = int(port_s or 3478)
        sock = None
        try:
            # STUN paketi hangi yerel adresle gittiyse cevap ona gider;
            # o yüzden çözümlemeyi sıfır adresle yapıp varsayılan yolu kullan.
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.sendto(req, (socket.gethostbyname(host), port))
            data, _ = sock.recvfrom(2048)
            result = parse_binding_response(data, txn)
            if result:
                return result
        except Exception:
            continue
        finally:
            if sock is not None:
                sock.close()
    return None
