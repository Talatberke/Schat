"""Duyarlı düzen (responsive) + yeniden akış (reflow) regresyon testleri.

Kapsar:
  * Karşılama kartı her pencere/puntoda kırpılmaz (gerekirse kaydırma).
  * Üst bar dar pencerede sadeleşir, bileşenler örtüşmez; genişleyince döner.
  * Punto değişiminde balon sarımları tazelenir, alt bar kesmez, kaydırma
    konumu korunur (sabit bayrağı).
"""
from __future__ import annotations

import time

import pytest

tk = pytest.importorskip("tkinter", reason="tkinter yok")


def _make_app():
    from secretchat import theme, ui
    theme.set_theme("dark")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display yok: {exc}")
    app = ui.ChatApp(root)
    return root, app


class _FakeRoom:
    room_code = "3K7QX"
    nickname = "sen"
    members = {"a": 1}

    def send_chat(self, t):
        return "m1"

    def leave(self):
        pass


def _enter_chat(app, root):
    app.room = _FakeRoom()
    app.room_code = "3K7QX"
    app._enter_chat(is_host=False)
    root.update_idletasks()
    root.update()


def _pump(root, secs=0.15):
    root.update_idletasks()
    root.update()
    time.sleep(secs)
    root.update()


def test_welcome_card_never_clipped():
    """Kart her boyutta kaydırma bölgesi içinde kalır (kırpma yok)."""
    from secretchat import theme
    root, app = _make_app()
    old_fam, old_size = theme.FONT_FAMILY, theme.load_saved_font_size()
    try:
        for geo, size in (("880x620", 12), ("720x500", 18)):
            root.geometry(geo)
            root.update_idletasks()
            root.update()
            app._refont_all(new_size_base=size)
            _pump(root)
            cv, box = app.welcome_canvas, app._welcome_box
            cx, cy = cv.coords(app._welcome_win)
            bw, bh = box.winfo_width(), box.winfo_height()
            sr = tuple(map(float, cv.cget("scrollregion").split()))
            assert sr[0] <= cx - bw / 2 and sr[2] >= cx + bw / 2
            assert sr[1] <= cy - bh / 2 and sr[3] >= cy + bh / 2
    finally:
        app._refont_all(new_family=old_fam, new_size_base=old_size)
        root.destroy()


def test_topbar_compacts_and_restores_without_overlap():
    """Dar pencerede sadeleşme + örtüşmesizlik; genişleyince geri dönüş."""
    root, app = _make_app()
    try:
        _enter_chat(app, root)

        def bar_rects():
            out = []
            for ch in app.chat_top.winfo_children():
                if ch.winfo_ismapped():
                    out.append((ch.winfo_x(), ch.winfo_x() + ch.winfo_width()))
            return sorted(out)

        root.geometry("880x620")
        _pump(root)
        assert app._top_compact is False
        assert app.members_lbl.winfo_ismapped()

        root.geometry("720x500")
        _pump(root)
        assert app._top_compact is True
        assert not app.members_lbl.winfo_ismapped()
        assert app.btn_leave.cget("text") == "🚪"
        for (_a1, b1), (a2, _b2) in zip(bar_rects(), bar_rects()[1:]):
            assert a2 >= b1 - 1, "üst bar bileşenleri örtüşüyor"

        root.geometry("880x620")
        _pump(root)
        assert app._top_compact is False
        assert app.members_lbl.winfo_ismapped()
        assert app.btn_leave.cget("text") == "🚪 Odadan Ayrıl"
    finally:
        root.destroy()


def test_reflow_keeps_wrap_bar_and_scroll():
    """Punto/değişimde sarım tazelenir, alt bar kesmez, konum korunur."""
    from secretchat import theme
    root, app = _make_app()
    old_size = theme.load_saved_font_size()
    try:
        _enter_chat(app, root)
        root.geometry("880x620")
        root.update_idletasks()
        root.update()
        long_text = "uzun ileti. " * 40
        app._append_message("sen", long_text, False, mine=True, msg_id="m1")
        root.update()

        app._refont_all(new_size_base=18)
        root.update_idletasks()
        root.update()
        assert app.chat_bottom.winfo_height() >= 72
        assert app.chat_text.yview()[1] >= 0.999  # sabit: sonda

        # kullanıcı yukarı kaydırınca reflow konumu korur
        app.chat_text.yview_moveto(0.0)
        app._on_chat_user_scroll()
        root.update()
        app._reflow_chat()
        root.update()
        assert app.chat_text.yview()[0] < 0.05

        # dar pencerede sarım daralır, balon akışı aşmaz
        root.geometry("720x500")
        _pump(root)
        cw = app.chat_text.winfo_width()
        for reg in app._msg_registry.values():
            assert reg["bubble"].winfo_width() <= cw
    finally:
        try:
            app._refont_all(new_size_base=old_size)
        except Exception:
            pass
        root.destroy()
