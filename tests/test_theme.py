"""Tema sistemi, Açık/Koyu mod geçişi ve kalıcılık birim testleri."""
from __future__ import annotations

import os
from secretchat import theme


def test_theme_toggle():
    initial_mode = theme.CURRENT_MODE
    new_mode = theme.toggle_theme()
    assert new_mode != initial_mode

    # Tekrar toggle edince eski moda dönmeli
    reverted_mode = theme.toggle_theme()
    assert reverted_mode == initial_mode


def test_set_theme_colors():
    theme.set_theme("dark")
    assert theme.is_dark()
    assert theme.BG == theme.DARK_PALETTE["BG"]
    assert theme.FG == theme.DARK_PALETTE["FG"]
    assert theme.BG != theme.FG

    theme.set_theme("light")
    assert not theme.is_dark()
    assert theme.BG == theme.LIGHT_PALETTE["BG"]
    assert theme.FG == theme.LIGHT_PALETTE["FG"]
    assert theme.BG != theme.FG


def test_theme_persistence(tmp_path, monkeypatch):
    test_settings_file = os.path.join(tmp_path, "settings.json")
    monkeypatch.setattr(theme, "SETTINGS_FILE", test_settings_file)
    monkeypatch.setattr(theme, "CONFIG_DIR", str(tmp_path))

    theme.save_theme_preference("light")
    assert os.path.exists(test_settings_file)
    loaded = theme.load_saved_theme()
    assert loaded == "light"

    theme.save_theme_preference("dark")
    loaded = theme.load_saved_theme()
    assert loaded == "dark"


def test_contrast_ratios_and_inputs():
    for mode in ("dark", "light"):
        palette = theme.LIGHT_PALETTE if mode == "light" else theme.DARK_PALETTE
        # Girdi ve ana arka plan birbirinden belirgin olmalı
        assert palette["BG"] != palette["BG_INPUT"]
        # Metin ve girdi arka planı birbirinden farklı olmalı
        assert palette["FG"] != palette["BG_INPUT"]
        # Kart ve ana arka plan ayrışmalı
        assert palette["BG"] != palette["BORDER"]
