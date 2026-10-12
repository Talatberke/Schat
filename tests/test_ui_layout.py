"""Sohbet ekranı yerleşim regresyon testleri (ui.py).

Regresyon özeti: tk.Text'in varsayılan height=24 (~870px) talebi pack
sırasını ezip alt barı mapped=0 (görünmez) yapıyordu. Düzeltme:
chat_top TOP -> chat_bottom BOTTOM (pack_propagate(False), 72px) -> chat_mid
fill=BOTH, expand=True. Bu testler sabit alt barı, esnek mesaj alanını ve
çakışma olmadığını kilitler.
"""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter", reason="tkinter yok")


class _FakeRoom:
    room_code = "3K7QX"
    nickname = "sen"
    members = {"sen": 1, "ada": 2}

    def send_chat(self, t):
        return True

    def leave(self):
        pass


def _open_chat(geometry: str = "880x620"):
    """ChatApp'i sahte odayla aç; (root, app) döndür, test bitiminde destroy."""
    from secretchat import theme, ui

    theme.set_theme("dark")
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # başsız ortamda display yok
        pytest.skip(f"Tk display yok: {exc}")
    app = ui.ChatApp(root)
    root.geometry(geometry)
    app.room = _FakeRoom()
    app.room_code = "3K7QX"
    app._enter_chat(is_host=False)
    for i in range(25):
        app._append_message("ada", f"Mesaj {i} — şifreli deneme metni.", False)
    root.update_idletasks()
    root.update()
    return root, app


@pytest.mark.parametrize("geometry", ["880x620", "720x500"])
def test_bottom_bar_is_visible_and_fixed(geometry):
    """Alt bar görünür, 60-80px (spec) ve pencerenin tam altında."""
    root, app = _open_chat(geometry)
    try:
        bar = app.chat_bottom
        assert bar.winfo_ismapped(), "alt bar mapped değil (görünmez)"
        h = bar.winfo_height()
        assert 60 <= h <= 80, f"alt bar yüksekliği {h}, spec 60-80px"
        # alt bar pencerenin DIŞINA taşmamalı ve tam altında bitmeli
        win_h = root.winfo_height()
        bar_bottom = bar.winfo_y() + h
        assert bar_bottom <= win_h + 2, f"bar pencere dışı: {bar_bottom} > {win_h}"
        assert bar_bottom >= win_h - 8, f"bar dibe yapışık değil: {bar_bottom} < {win_h}"
    finally:
        root.destroy()


def test_message_area_expands_and_does_not_overlap_bar():
    """Mesaj alanı (expand=True) üst barla alt bar arasında kalanı tam kaplar;
    chat_mid ile chat_bottom çakışmaz."""
    root, app = _open_chat("880x620")
    try:
        mid = app.chat_mid
        top = app.chat_top
        bar = app.chat_bottom
        assert mid.winfo_ismapped()

        mid_y, mid_h = mid.winfo_y(), mid.winfo_height()
        top_bottom = top.winfo_y() + top.winfo_height()
        bar_y = bar.winfo_y()

        # mesaj alanı üst barın hemen altında başlar
        assert abs(mid_y - top_bottom) <= 2, f"mesaj alanı üst barla çakışıyor: {mid_y} vs {top_bottom}"
        # mesaj alanı alt barla ÇAKIŞMAZ (scroll izolasyonu)
        assert mid_y + mid_h <= bar_y + 2, \
            f"mesaj alanı alt barı eziyor: {mid_y + mid_h} > {bar_y}"
        # mesaj alanı esnektir: pencerenin makul bir kısmını kaplar
        assert mid_h >= root.winfo_height() // 3, "mesaj alanı expand=True ile büyümemiş"

        # giriş ve gönder butonu görünür ve pencere içinde
        for name in ("msg_entry", "btn_send"):
            w = getattr(app, name)
            assert w.winfo_ismapped(), f"{name} görünmez"
            bottom = w.winfo_y() + w.winfo_height()
            assert bottom <= root.winfo_height() + 2, f"{name} pencere dışı"
    finally:
        root.destroy()


def test_input_bar_colors_match_theme():
    """Alt bar #151B26 (BG_PANEL/surface), input #1E293B kenarlık, buton #7B2CBF."""
    from secretchat import theme

    theme.set_theme("dark")
    root, app = _open_chat("880x620")
    try:
        assert app.chat_bottom.cget("bg") == theme.SURFACE
        # input çerçevesi kenarlığı surface_alt (#1E293B)
        assert app.msg_entry_frame.cget("bg") == theme.SURFACE_ALT
        # gönder butonu secondary (#7B2CBF); hover'da primary
        assert app.btn_send.cget("bg") == theme.SECONDARY
    finally:
        root.destroy()
