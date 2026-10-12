"""Uçtan uca entegrasyon testi: gerçek broker üzerinden iki oturum.

Yavaş olabilir (ağ I/O); sadece internet varken anlamlıdır.
Çalıştırma:  python -m pytest tests/test_integration.py -q -s
"""
from __future__ import annotations

import threading
import time

import pytest

from secretchat.room import Client, Host

pytestmark = pytest.mark.skipif(
    __import__("os").environ.get("SKIP_NET") == "1",
    reason="SKIP_NET=1 ile ağ testleri atlandı")


def _wait_chat(side, expected_text, timeout=30.0):
    """Beklenen metin gelene kadar gelen mesajları topla."""
    got = threading.Event()
    box = {"messages": []}

    def cb(sender, text, system):
        box["messages"].append((sender, text, system))
        if text == expected_text:
            got.set()

    side.on_message = cb
    return got, box


@pytest.mark.timeout(90)
def test_host_client_chat_roundtrip():
    host = Host("kurucu")
    assert host.start(), "host broker'a bağlanamadı"

    client = Client("katilan", host.room_code)
    assert client.start(), "client broker'a bağlanamadı"
    assert client.wait_joined(30), "el sıkışma/grup anahtarı tamamlanmadı"

    got_at_host, at_host = _wait_chat(host, "selam kurucu")
    got_at_client, at_client = _wait_chat(client, "selam katilan")

    # client -> host
    client.send_chat("selam kurucu")
    # host -> client
    host.send_chat("selam katilan")

    assert got_at_host.wait(30), f"host mesajı alamadı: {at_host['messages']}"
    sender, text, system = next(m for m in at_host["messages"]
                                if m[1] == "selam kurucu")
    assert sender == "katilan" and not system

    assert got_at_client.wait(30), f"client mesajı alamadı: {at_client['messages']}"
    sender, text, system = next(m for m in at_client["messages"]
                                if m[1] == "selam katilan")
    assert sender == "kurucu" and not system

    # SAS iki tarafta aynı olmalı
    assert host.pending_sas.get("katilan") == client.sas

    client.leave()
    host.stop()


@pytest.mark.timeout(60)
def test_wrong_code_fails_cleanly():
    client = Client("ghost", "ZZZZZ")
    assert client.start()
    assert not client.wait_joined(15), "yanlış kodla oda bulunmamalıydı"
    client.stop()
