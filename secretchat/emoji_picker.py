"""Emoji seçici: mesaj girişine tek tıkla emoji ekleme.

Kullanım (ui.py)::

    from .emoji_picker import show_emoji_picker
    show_emoji_picker(self.msg_entry, on_pick=self._insert_emoji)

Tasarım: küçük, modüler ``tk.Toplevel``; kategori sekmeleri + ızgara.
Bağımlılık yok, tema renklerini ``theme`` modülünden alır.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable, Dict, List, Optional

EMOJI_GROUPS: Dict[str, List[str]] = {
    "Sık": ["😀", "😂", "😍", "🤣", "😊", "😉", "😎", "🥳",
            "👍", "👏", "🙏", "🔥", "🎉", "❤️"],
    "Yüzler": ["😀", "😁", "😅", "🤣", "😊", "😍", "😘", "😎",
               "🤔", "😐", "🙄", "😴", "😷", "🤯",
               "🥺", "😢", "😭", "😡", "🥶", "🤖"],
    "Eller": ["👍", "👎", "👏", "🙌", "👋", "✌️", "🤝", "💪",
              "✍️", "👀", "🙏", "💅", "🤙", "🫶"],
    "Kalpler": ["❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍",
                "💔", "💯", "💥", "✨", "⭐", "🌟"],
    "Nesneler": ["🔥", "🎉", "🎁", "⚽", "🚗", "✈️", "💡", "📷",
                 "🎵", "☕", "🍕", "🌹", "🔑", "🔒"],
}

ALL_EMOJIS: List[str] = [e for grp in EMOJI_GROUPS.values() for e in grp]


class EmojiPicker(tk.Toplevel):
    """Emoji ızgarası açılır penceresi (açık/koyu tema uyumlu)."""

    def __init__(self, master, on_pick: Callable[[str], None]):
        super().__init__(master)
        self._on_pick = on_pick
        self.title("Emoji seç")
        self.resizable(False, False)
        self.transient(master)
        try:
            from . import theme
            bg = theme.BG_PANEL        # panel zemini
            hover = theme.BG_HOVER     # hover zemini
            fg = theme.FG              # ana metin
            dim = theme.FG_DIM         # pasif kategori metni
            accent = theme.ACCENT      # aktif kategori zemini
            on_accent = theme.ON_ACCENT
            border = theme.BORDER      # dış çerçeve
        except Exception:
            bg, hover = "#151B26", "#24304a"
            fg, dim = "#E6EAF2", "#64748B"
            accent, on_accent, border = "#00F5D4", "#0B0E14", "#1F2A3A"

        self._bg, self._hover = bg, hover
        self._fg, self._dim = fg, dim
        self._accent, self._on_accent = accent, on_accent

        # 1px tema çerçevesi: dış Toplevel border renginde, iç içerik panel renginde
        self.configure(bg=border)
        inner = tk.Frame(self, bg=bg, padx=2, pady=2)
        inner.pack(fill=tk.BOTH, expand=True)

        # Kategori şeridi
        bar = tk.Frame(inner, bg=bg)
        bar.pack(fill=tk.X, padx=8, pady=(8, 4))
        self._grid_frame = tk.Frame(inner, bg=bg)
        self._grid_frame.pack(padx=8, pady=(0, 8))

        self._cat_buttons: Dict[str, tk.Button] = {}
        for name in EMOJI_GROUPS:
            b = tk.Button(
                bar, text=name, font=("Segoe UI", 9, "bold"),
                bg=bg, fg=dim, relief=tk.FLAT, bd=0,
                activebackground=hover, activeforeground=fg,
                cursor="hand2", padx=8, pady=4,
                command=lambda n=name: self._show_category(n),
            )
            b.pack(side=tk.LEFT, padx=2)
            self._cat_buttons[name] = b

        self._active_cat: Optional[str] = None
        self._show_category("Sık")
        self._place_near(master)
        self.focus_set()
        self.bind("<Escape>", lambda _e: self.destroy())
        # Odak kaybedince kapat (yerleşik UX)
        self.bind("<FocusOut>", self._auto_close)

    def _place_near(self, anchor_widget) -> None:
        try:
            x = anchor_widget.winfo_rootx()
            y = anchor_widget.winfo_rooty() - 320
            if y < 0:
                y = anchor_widget.winfo_rooty() + anchor_widget.winfo_height() + 8
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _show_category(self, name: str) -> None:
        # Aktif kategori vurgusu: neon zemin + koyu metin, pasifler soluk
        for cat, btn in self._cat_buttons.items():
            try:
                if cat == name:
                    btn.configure(bg=self._accent, fg=self._on_accent,
                                  activebackground=self._accent,
                                  activeforeground=self._on_accent)
                else:
                    btn.configure(bg=self._bg, fg=self._dim,
                                  activebackground=self._hover,
                                  activeforeground=self._fg)
            except tk.TclError:
                pass
        self._active_cat = name
        for child in self._grid_frame.winfo_children():
            child.destroy()
        emojis = EMOJI_GROUPS.get(name, ALL_EMOJIS)
        cols = 7
        for i, emo in enumerate(emojis):
            b = tk.Button(
                self._grid_frame, text=emo, font=("Segoe UI Emoji", 16),
                width=3, relief=tk.FLAT, bd=0, cursor="hand2",
                bg=self._bg, fg=self._fg,
                activebackground=self._hover, activeforeground=self._fg,
                command=lambda e=emo: self._pick(e),
            )
            b.grid(row=i // cols, column=i % cols, padx=1, pady=1)
            # Hover'da kart hissi: zemin yumuşakça aydınlanır
            b.bind("<Enter>", lambda e, w=b: self._emo_hover(w, True))
            b.bind("<Leave>", lambda e, w=b: self._emo_hover(w, False))

    def _emo_hover(self, widget: tk.Button, inside: bool) -> None:
        try:
            widget.configure(bg=self._hover if inside else self._bg)
        except tk.TclError:
            pass

    def _pick(self, emo: str) -> None:
        try:
            self._on_pick(emo)
        finally:
            self.destroy()

    def _auto_close(self, _event=None) -> None:
        # Tıklama başka pencereye geçtiyse kapat; emoji tıklaması _pick ile
        # zaten kapanır. after_idle ile yarış durumunu önle.
        try:
            self.after(150, self._close_if_unfocused)
        except Exception:
            pass

    def _close_if_unfocused(self) -> None:
        try:
            if self.winfo_exists() and self.focus_get() is None:
                self.destroy()
        except Exception:
            pass


_open_picker: Optional[EmojiPicker] = None


def show_emoji_picker(anchor, on_pick: Callable[[str], None]):
    """Tek örnek açılır emoji paneli göster (varsa öne getir)."""
    global _open_picker
    try:
        if _open_picker is not None and _open_picker.winfo_exists():
            _open_picker.lift()
            _open_picker.focus_set()
            return _open_picker
    except Exception:
        pass
    _open_picker = EmojiPicker(anchor, on_pick)
    return _open_picker
