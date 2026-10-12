"""Kayıt katmanı testleri: RAM modu ve dosyaya yazma."""
from __future__ import annotations

import os

from secretchat.storage import ChatStore


def test_ram_only_mode(tmp_path):
    store = ChatStore()
    store.append("merhaba")
    assert store.dump_memory() and not store.recording
    store.wipe()
    assert store.dump_memory() == []


def test_file_recording(tmp_path):
    path = os.path.join(tmp_path, "sohbet.log")
    store = ChatStore()
    store.set_recording(path)
    store.append("satır-1")
    store.append("satır-2")
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    assert "satır-1" in content and "satır-2" in content


def test_set_recording_flushes_memory(tmp_path):
    store = ChatStore()
    store.append("önceden")
    path = os.path.join(tmp_path, "gec.log")
    store.set_recording(path)
    with open(path, encoding="utf-8") as fh:
        assert "önceden" in fh.read()


def test_wipe_clears_everything(tmp_path):
    store = ChatStore()
    store.append("gizli")
    store.wipe()
    assert store.dump_memory() == []
