"""Google Fonts ayrıştırma ve yazı tipi kalıcılık testleri (ağ yok)."""
from __future__ import annotations

import os

import pytest

from secretchat import fonts, theme


def test_parse_specimen_url():
    assert fonts.parse_family("https://fonts.google.com/specimen/Caveat") == "Caveat"
    assert fonts.parse_family("https://fonts.google.com/specimen/Roboto+Mono") == "Roboto Mono"


def test_parse_css2_url():
    url = "https://fonts.googleapis.com/css2?family=Caveat:wght@400..700&display=swap"
    assert fonts.parse_family(url) == "Caveat"
    multi = "https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@400&family=Inter&display=swap"
    assert fonts.parse_family(multi) == "Roboto Mono"


def test_parse_plain_name():
    assert fonts.parse_family("Caveat") == "Caveat"
    assert fonts.parse_family("  Playfair Display  ") == "Playfair Display"


def test_parse_rejects_bad_input():
    for bad in ("", "   ", "javascript:alert(1)", "<script>", "a" * 65,
                "https://example.com/some/very/long/path/that/is/not/a/font/specimen/at/all/xyz"):
        with pytest.raises(ValueError):
            fonts.parse_family(bad)


def test_font_persistence_roundtrip(tmp_path, monkeypatch):
    test_settings = os.path.join(tmp_path, "settings.json")
    monkeypatch.setattr(theme, "SETTINGS_FILE", test_settings)
    monkeypatch.setattr(theme, "CONFIG_DIR", str(tmp_path))

    assert theme.load_saved_font() is None
    theme.save_font_preference("Caveat")
    assert theme.load_saved_font() == "Caveat"
    # tema kaydı font kaydını ezmemeli
    theme.save_theme_preference("light")
    assert theme.load_saved_theme() == "light"
    assert theme.load_saved_font() == "Caveat"
    theme.save_font_preference(None)
    assert theme.load_saved_font() is None


def test_font_size_persistence_roundtrip(tmp_path, monkeypatch):
    test_settings = os.path.join(tmp_path, "settings.json")
    monkeypatch.setattr(theme, "SETTINGS_FILE", test_settings)
    monkeypatch.setattr(theme, "CONFIG_DIR", str(tmp_path))

    assert theme.load_saved_font_size() == 12
    theme.save_font_size_preference(15)
    assert theme.load_saved_font_size() == 15
    # tema ve tip kayıtları boyutu ezmemeli
    theme.save_theme_preference("dark")
    theme.save_font_preference("Caveat")
    assert theme.load_saved_font_size() == 15
    # sınırlar kelepçelenir, buçuk adımlar korunur
    theme.save_font_size_preference(99)
    assert theme.load_saved_font_size() == 18
    theme.save_font_size_preference(1)
    assert theme.load_saved_font_size() == 9
    theme.save_font_size_preference(14.5)
    assert theme.load_saved_font_size() == 14.5
    theme.save_font_size_preference(14.7)
    assert theme.load_saved_font_size() == 14.5


def test_split_font_spec():
    from secretchat.ui import ChatApp
    assert ChatApp._split_font_spec(("Segoe UI", 12, "bold")) == ("Segoe UI", 12, ["bold"])
    assert ChatApp._split_font_spec("{Segoe UI} 12 bold") == ("Segoe UI", 12, ["bold"])
    assert ChatApp._split_font_spec("TkDefaultFont") == ("TkDefaultFont", None, [])
    assert ChatApp._split_font_spec("") is None
    assert ChatApp._split_font_spec(()) is None


def test_pick_ttf_prefers_latin():
    css = ("/* cyrillic */ @font-face { src: url(https://a/cy.ttf); } "
           "/* latin */ @font-face { src: url(https://a/la.ttf); }")
    assert fonts._pick_ttf_url(css) == "https://a/la.ttf"
    with pytest.raises(RuntimeError):
        fonts._pick_ttf_url("no urls here")
