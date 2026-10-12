"""Cyber-Incognito — hazır tema arayüz şablonu (reference component).

`theme.py` token'larının gerçekten nasıl göründüğünü gösteren çalışan şablon.
İçerir:

  * StatusBar    — durum çubuğu (çevrimiçi noktası, E2EE rozeti, oda kodu)
  * Bubble       — yuvarlak köşeli (12/12/12/2), gradyanlı mesaj balonu
  * MessageList  — kaydırılabilir mesaj listesi + "yazıyor..." göstergesi
  * NeonEntry    — odakta neon parıltılı giriş alanı + gönder butonu
  * ChatTemplate — hepsini birleştiren hazır ekran

Doğrudan çalıştırın:
    python -m secretchat.components
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable, Dict, List, Optional, Tuple

from . import theme


# ==========================================================================
# Renk yardımcıları
# ==========================================================================
def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lerp(c1: str, c2: str, t: float) -> str:
    """İki hex rengi arasında doğrusal geçiş."""
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    r = int(round(r1 + (r2 - r1) * t))
    g = int(round(g1 + (g2 - g1) * t))
    b = int(round(b1 + (b2 - b1) * t))
    return f"#{r:02x}{g:02x}{b:02x}"


def _blend(c1: str, c2: str, t: float) -> str:
    """_lerp ile aynı; niyeti açık kılmak için takma ad."""
    return _lerp(c1, c2, t)


def _available_width(widget, default: int = 1024) -> int:
    """Widget henüz çizilmediyse ({w:1} döner) yukarı çıkarak gerçek
    genişliği bul; hiçbiri hazır değilse `default`."""
    try:
        w = widget.winfo_width()
    except tk.TclError:
        w = 0
    if w and w > 100:
        return w
    p = widget
    for _ in range(8):
        try:
            p = p.master
        except tk.TclError:
            break
        if p is None:
            break
        try:
            w = p.winfo_width()
        except tk.TclError:
            break
        if w and w > 100:
            return w
    return default


class _GradientBubbleCanvas(tk.Canvas):
    """Gradyanlı, yuvarlak köşeli balon için özel Canvas.

    Tkinter Canvas'ta gerçek kırpma (clip) olmadığından balonu
    yatay dilimler (slice) halinde çizeriz; her dilimin kenarı o y'deki
    köşe eğrisine uyar — maske/artık gerekmeden net köşeler.
    """

    def __init__(self, master, bg: str, **kw):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, **kw)

    def paint(self, w: int, h: int, radius: Tuple[int, int, int, int],
              c_from: str, c_to: str, outline: str = ""):
        """Yuvarlak köşeli, gradyanlı balonu temiz çiz.

        Gradyan, balonun yatay dilimlerini (slice) tek tek poligon
        olarak çizeriz; her dilimin sol/sağ kenarı o y'deki yuvarlak
        köşe eğrisindedir. Böylece maske/artık gerekmeden köşeler
        net çıkar (Canvas'ta gerçek kırpma/clip yoktur).
        """
        self.delete("all")
        self.configure(width=w, height=h)
        x0, y0 = 1, 1
        x1, y1 = max(3, w - 1), max(3, h - 1)
        bw, bh = x1 - x0, y1 - y0
        lim = max(1, min(bw, bh) // 2)
        r_tl, r_tr, r_br, r_bl = [min(max(0, int(r)), lim) for r in radius]

        def left(y: float) -> float:
            if r_tl and y < y0 + r_tl:
                dy = (y0 + r_tl) - y
                return x0 + r_tl - math.sqrt(max(0.0, r_tl * r_tl - dy * dy))
            if r_bl and y > y1 - r_bl:
                dy = y - (y1 - r_bl)
                return x0 + r_bl - math.sqrt(max(0.0, r_bl * r_bl - dy * dy))
            return float(x0)

        def right(y: float) -> float:
            if r_tr and y < y0 + r_tr:
                dy = (y0 + r_tr) - y
                return x1 - r_tr + math.sqrt(max(0.0, r_tr * r_tr - dy * dy))
            if r_br and y > y1 - r_br:
                dy = y - (y1 - r_br)
                return x1 - r_br + math.sqrt(max(0.0, r_br * r_br - dy * dy))
            return float(x1)

        # kenar yolu: düz dolgu ve kontur için ortak
        path: List[float] = []
        steps = 16

        def arc(cx, cy, r, a0, a1):
            n = max(4, int(steps * (abs(a1 - a0) / 90.0)))
            for i in range(n + 1):
                a = math.radians(a0 + (a1 - a0) * i / n)
                path.append(cx + r * math.cos(a))
                path.append(cy + r * math.sin(a))

        if r_tl:
            arc(x0 + r_tl, y0 + r_tl, r_tl, 180, 270)
        else:
            path += [x0, y0]
        if r_tr:
            arc(x1 - r_tr, y0 + r_tr, r_tr, 270, 360)
        else:
            path += [x1, y0]
        if r_br:
            arc(x1 - r_br, y1 - r_br, r_br, 0, 90)
        else:
            path += [x1, y1]
        if r_bl:
            arc(x0 + r_bl, y1 - r_bl, r_bl, 90, 180)
        else:
            path += [x0, y1]

        if c_from == c_to:
            # düz dolgu (gelen balon): tek poligon + kontur
            self.create_polygon(path, fill=c_from, outline=outline or "",
                                width=1, smooth=True, splinesteps=24)
            return

        # gradyan: yatay dilimler; komşu dilimler kenarları paylaşır → dikiş yok
        n = max(4, min(72, int(bh)))
        for i in range(n):
            ya = y0 + bh * i / n
            yb = y0 + bh * (i + 1) / n
            col = _lerp(c_from, c_to, (i + 0.5) / n)
            self.create_polygon([left(ya), ya, right(ya), ya,
                                 right(yb), yb, left(yb), yb],
                                fill=col, outline="")
        # kontur en üstte: dilim kenarını örter, köşeleri netleştirir
        if outline:
            self.create_polygon(path, fill="", outline=outline, width=1,
                                smooth=True, splinesteps=24)


# ==========================================================================
# Durum çubuğu
# ==========================================================================
class StatusBar(tk.Frame):
    """Üst durum çubuğu: durum noktası + E2EE rozeti + oda kodu."""

    def __init__(self, master, room_code: str = "-----",
                 title: str = "Cyber-Incognito",
                 on_theme_toggle: Optional[Callable[[], None]] = None):
        bg = theme.SURFACE
        sp = theme.SPACING["desktop"]
        super().__init__(master, bg=bg, height=sp["bar_h"])
        self.pack_propagate(False)
        self._on_toggle = on_theme_toggle

        padx = sp["gutter"]
        self.configure(padx=padx, pady=0)

        # -- sol: durum noktası + başlık
        left = tk.Frame(self, bg=bg)
        left.pack(side=tk.LEFT, fill=tk.Y)
        self.dot = tk.Label(left, text="●", font=(theme.FONT_CODE, 11),
                            bg=bg, fg=theme.SUCCESS)
        self.dot.pack(side=tk.LEFT, pady=(sp["bar_h"] // 2 - 8, 0))
        self.title_lbl = tk.Label(left, text=title, bg=bg, fg=theme.TEXT,
                                  font=(theme.FONT_FAMILY, 12, "bold"))
        self.title_lbl.pack(side=tk.LEFT, padx=(6, 0),
                            pady=(sp["bar_h"] // 2 - 8, 0))

        # -- orta: E2EE rozeti (gizli/mor)
        self.badge = tk.Frame(left, bg=theme.SECONDARY, padx=8, pady=2)
        self.badge.pack(side=tk.LEFT, padx=(14, 0),
                        pady=(sp["bar_h"] // 2 - 10, 0))
        tk.Label(self.badge, text="🔒 E2EE", font=(theme.FONT_CODE, 9, "bold"),
                 bg=theme.SECONDARY, fg=theme.ON_SECONDARY).pack()

        # -- sağ: oda kodu + tema düğmesi
        right = tk.Frame(self, bg=bg)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        self.code_box = tk.Frame(right, bg=theme.BG_CARD,
                                 highlightbackground=theme.BORDER,
                                 highlightthickness=1, padx=10, pady=3)
        self.code_box.pack(side=tk.RIGHT, pady=(sp["bar_h"] // 2 - 12, 0))
        tk.Label(self.code_box, text="ODA", font=(theme.FONT_CODE, 8),
                 bg=theme.BG_CARD, fg=theme.MUTED).pack(side=tk.LEFT)
        tk.Label(self.code_box, text=room_code,
                 font=(theme.FONT_CODE, 13, "bold"),
                 bg=theme.BG_CARD, fg=theme.PRIMARY).pack(side=tk.LEFT,
                                                          padx=(6, 0))

        self.btn_theme = tk.Button(
            right, text="◐ Tema", font=(theme.FONT_FAMILY, 9),
            bg=theme.SURFACE_ALT, fg=theme.MUTED, relief=tk.FLAT,
            activebackground=theme.BORDER, activeforeground=theme.PRIMARY,
            padx=8, pady=2, cursor="hand2",
            command=self._on_toggle or (lambda: None))
        self.btn_theme.pack(side=tk.RIGHT, padx=(0, 8),
                            pady=(sp["bar_h"] // 2 - 11, 0))
        self._hoverable(self.btn_theme, theme.SURFACE_ALT, theme.BORDER,
                        theme.MUTED, theme.PRIMARY)

        self.sep = tk.Frame(self, bg=theme.BORDER, height=1)
        self.sep.place(relx=0, rely=1, relwidth=1, anchor="sw")

    @staticmethod
    def _hoverable(btn: tk.Button, bg: str, hbg: str, fg: str, hfg: str):
        """Mikro-etkileşim: üzerine gelme (hover) efekti — 150ms hissi."""
        btn.bind("<Enter>", lambda e: btn.configure(bg=hbg, fg=hfg))
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg, fg=fg))

    def set_status(self, online: bool = True, text: str = ""):
        self.dot.configure(fg=theme.SUCCESS if online else theme.ERROR)
        if text:
            self.title_lbl.configure(text=text)


# ==========================================================================
# Mesaj balonu
# ==========================================================================
class Bubble(tk.Frame):
    """Tek mesaj balonu. `mine=True` -> sağ, gradyan mor; yoksa sol, düz."""

    PAD_X = 14
    PAD_Y = 10
    META_H = 16

    def __init__(self, master, sender: str, text: str, stamp: str,
                 mine: bool, fonts: Dict[str, tuple], bg: str):
        super().__init__(master, bg=bg)
        self.mine = mine
        avail = _available_width(master)
        sp = theme.spacing_for(avail)
        self.pad = sp["bubble_pad"]

        # pack tarafı (left/right) ile widget çapası (w/e) farklıdır
        side = tk.RIGHT if mine else tk.LEFT
        anchor = "e" if mine else "w"
        self.pack(fill=tk.X, padx=(0 if mine else sp["gutter"],
                                   sp["gutter"] if mine else 0),
                  pady=(0, sp["gap"]), anchor=anchor)

        # -- meta satırı (gönderen + saat): mono, soluk
        meta_fg = theme.MUTED
        who = "sen" if mine else sender
        meta = tk.Label(self, text=f"{who}  ·  {stamp}",
                        font=fonts["meta"], bg=bg, fg=meta_fg)
        meta.pack(anchor=anchor)

        # -- balon canvas
        body_font = tkfont.Font(font=fonts["body"])
        # hazır olmayan widget winfo_width=1 döndürür → atalarından gerçek
        # genişliği bul; hiçbiri hazır değilse masaüstü varsayılanı (1024).
        max_w = max(200, int(avail * 0.62))
        self._wrap = self._wrap_text(body_font, text, max_w)
        line_h = body_font.metrics("linespace")
        widest = max(body_font.measure(l) for l in self._wrap) if self._wrap else 0

        w = min(widest + self.PAD_X * 2, max_w + self.PAD_X * 2)
        h = line_h * len(self._wrap) + self.PAD_Y * 2

        lg, tail = theme.RADIUS["lg"], theme.RADIUS["bubble_tail"]
        # CSS sırası (TL TR BR BL): gelen 12 12 12 2 · giden 12 12 2 12
        radius = (lg, lg, tail, lg) if mine else (lg, lg, lg, tail)

        if mine:
            # gradyan aşağı doğru koyulaşır: üst secondary, alt secondary_deep
            c_from = theme.token("secondary")
            c_to = theme.token("secondary_deep")
            outline = theme.token("secondary")
        else:
            c_from = c_to = theme.token("surface_alt")
            outline = theme.BORDER

        self.cv = _GradientBubbleCanvas(self, bg=bg)
        self.cv.pack(anchor=anchor)
        self.cv.paint(w, h, radius, c_from, c_to, outline=outline)

        # -- metin katmanı
        fg = theme.ON_SECONDARY if mine else theme.TEXT
        y = self.PAD_Y + line_h // 2
        for line in self._wrap:
            x = self.PAD_X if not mine else self.PAD_X
            # Canvas metni soldan hizalı; sağ balonda da soldan okunur
            self.cv.create_text(self.PAD_X, y, text=line, anchor="w",
                                font=fonts["body"], fill=fg)
            y += line_h

        # -- hover mikro-etkileşim: kopyala / çöz / sil butonları
        self.actions = tk.Frame(self, bg=bg)
        self._act_btns = []
        for label, tip in (("⎘", "Kopyala"), ("🔑", "Çöz"), ("✕", "Sil")):
            b = tk.Label(self.actions, text=label, font=(theme.FONT_CODE, 10),
                         bg=bg, fg=theme.MUTED, cursor="hand2")
            b.pack(side=tk.LEFT, padx=(0, 6))
            self._act_btns.append((b, tip))
        self.actions.pack(anchor=anchor, pady=(2, 0))
        self.actions.pack_forget()  # gizli; hover'da açılır

        self.bind("<Enter>", self._show_actions)
        self.cv.bind("<Enter>", self._show_actions)
        self.bind("<Leave>", self._hide_actions)
        self.cv.bind("<Leave>", self._hide_actions)
        for b, _ in self._act_btns:
            b.bind("<Enter>", lambda e, bb=b: bb.configure(fg=theme.PRIMARY))
            b.bind("<Leave>", lambda e, bb=b: bb.configure(fg=theme.MUTED))

    @staticmethod
    def _wrap_text(f: tkfont.Font, text: str, max_w: int) -> List[str]:
        words = text.split()
        if not words:
            return [text]
        lines: List[str] = []
        cur = ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if f.measure(trial) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
        return lines

    def _show_actions(self, _e=None):
        self.actions.pack(anchor="e" if self.mine else "w", pady=(2, 0))

    def _hide_actions(self, _e=None):
        self.actions.pack_forget()

    def fade_out(self, done: Optional[Callable[[], None]] = None):
        """Kaybolan mesaj animasyonu — yumuşak geçiş (opacity)."""
        steps = theme.MOTION["slow"] // 30
        colors = [_blend(self.cget("bg"), theme.BG, i / steps)
                  for i in range(steps + 1)]

        def step(i=0):
            if i >= len(colors):
                self.destroy()
                if done:
                    done()
                return
            c = colors[i]
            self.configure(bg=c)
            for w in self.winfo_children():
                try:
                    w.configure(bg=c)
                except tk.TclError:
                    pass
            self.after(30, lambda: step(i + 1))

        step()


# ==========================================================================
# Mesaj listesi
# ==========================================================================
class MessageList(tk.Frame):
    """Kaydırılabilir mesaj listesi + yazıyor göstergesi."""

    def __init__(self, master, fonts: Dict[str, tuple]):
        super().__init__(master, bg=theme.BG)
        self.fonts = fonts

        self.canvas = tk.Canvas(self, bg=theme.BG, highlightthickness=0,
                                bd=0)
        self.scroll = tk.Scrollbar(self, orient=tk.VERTICAL,
                                   command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=theme.BG)

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw",
                                  tags="inner")
        self.canvas.configure(yscrollcommand=self.scroll.set)

        # DÜZELTME: içerik akışının en altında 80px pay (padding-bottom:80px).
        # side=BOTTOM → son mesaj + "yazıyor..." göstergesi her zaman görünür
        # kalır, alt yazma çubuğunun altında kaybolmaz.
        self._bottom_pad = tk.Frame(self.inner, bg=theme.BG, height=80)
        self._bottom_pad.pack(side=tk.BOTTOM, fill=tk.X)
        self._bottom_pad.pack_propagate(False)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.typing_lbl: Optional[tk.Label] = None

    def _on_inner_configure(self, _e):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def width(self) -> int:
        return _available_width(self.canvas)

    def add(self, sender: str, text: str, stamp: str, mine: bool):
        Bubble(self.inner, sender, text, stamp, mine, self.fonts,
               theme.BG)
        self.after(10, lambda: self.canvas.yview_moveto(1.0))

    def add_system(self, text: str, stamp: str):
        sp = theme.spacing_for(self.width())
        row = tk.Frame(self.inner, bg=theme.BG)
        row.pack(fill=tk.X, padx=sp["gutter"], pady=(0, sp["gap"]))
        lbl = tk.Label(row, text=f"⟨ {stamp}  ·  {text} ⟩",
                       font=self.fonts["meta"], bg=theme.SURFACE,
                       fg=theme.MUTED, padx=10, pady=4)
        lbl.pack(anchor="center")

    def show_typing(self, name: str):
        if self.typing_lbl is None:
            self.typing_lbl = tk.Label(self.inner, text="",
                                       font=self.fonts["meta"],
                                       bg=theme.BG, fg=theme.PRIMARY)
            self.typing_lbl.pack(anchor="w", padx=12, pady=(0, 6))
        self._typing_name = name
        self._typing_dots(name, 0)

    def _typing_dots(self, name: str, n: int):
        if self.typing_lbl is None or not self.typing_lbl.winfo_exists():
            return
        self.typing_lbl.configure(text=f"{name} yazıyor" + "." * (n % 4))
        self.after(theme.MOTION["normal"], lambda: self._typing_dots(
            name, n + 1))

    def hide_typing(self):
        if self.typing_lbl is not None and self.typing_lbl.winfo_exists():
            self.typing_lbl.destroy()
        self.typing_lbl = None


# ==========================================================================
# Neon giriş alanı
# ==========================================================================
class NeonEntry(tk.Frame):
    """Giriş alanı: odakta `#00F5D4` neon parıltısı + gönder butonu."""

    def __init__(self, master, on_send: Optional[Callable[[str], None]] = None):
        bg = theme.SURFACE
        sp = theme.spacing_for(_available_width(master))
        # DÜZELTME: sabit 72px alt yazma çubuğu (spec 60-80px); alt kenara
        # side=BOTTOM pack edildiği için mesaj listesi bunu asla ezemez.
        super().__init__(master, bg=bg, padx=sp["gutter"], pady=sp["gap"],
                         height=72)
        self.pack_propagate(False)
        self._on_send = on_send

        # DÜZELTME: kenarlık #1E293B (surface_alt) — odakta neon parıltı
        self.wrap = tk.Frame(self, bg=theme.SURFACE_ALT, padx=1, pady=1)
        self.wrap.pack(fill=tk.BOTH, expand=True)

        self.entry = tk.Entry(self.wrap, font=(theme.FONT_FAMILY, 12),
                              bg=theme.token("surface_input"),
                              fg=theme.TEXT, insertbackground=theme.TEXT,
                              relief=tk.FLAT, bd=0,
                              selectbackground=theme.PRIMARY,
                              selectforeground=theme.token("on_primary"))
        # entry, buton paketlendikten sonra paketlenir (yan yana dursun)
        self.entry.insert(0, "")
        self.entry.configure(fg=theme.MUTED)
        self._placeholder = "Şifreli mesajını yaz..."
        self._has_placeholder = True
        self.entry.insert(0, self._placeholder)
        self.entry.configure(fg=theme.MUTED)

        self.entry.bind("<FocusIn>", self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)
        self.entry.bind("<Return>", self._submit)

        # DÜZELTME: Gönder #7B2CBF (secondary) → hover #00F5D4 (primary),
        # metin rengi eşlik eder ki kontrast her iki durumda da AA olsun.
        self.btn_send = tk.Button(self.wrap, text="Gönder ➤",
                                  font=(theme.FONT_FAMILY, 11, "bold"),
                                  bg=theme.SECONDARY,
                                  fg=theme.ON_SECONDARY,
                                  activebackground=theme.PRIMARY,
                                  activeforeground=theme.ON_ACCENT,
                                  relief=tk.FLAT, padx=16, pady=6,
                                  cursor="hand2", command=self._submit_btn)
        # sıra önemli: buton önce SAĞ kenarı kaplar, entry soldan dolar
        self.btn_send.pack(side=tk.RIGHT, padx=2, pady=2, fill=tk.Y)
        self.entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                        ipady=9, padx=(2, 6), pady=2)
        self._base_btn_bg = theme.SECONDARY
        self.btn_send.bind("<Enter>", self._btn_enter)
        self.btn_send.bind("<Leave>", self._btn_leave)

    # -- odak: neon parıltı ------------------------------------------------
    def _focus_in(self, _e=None):
        if self._has_placeholder:
            self.entry.delete(0, tk.END)
            self.entry.configure(fg=theme.TEXT)
            self._has_placeholder = False
        # dış çerçeve: neon + box-shadow: 0 0 10px rgba(0,245,212,.3) hissi
        self.wrap.configure(bg=theme.PRIMARY)
        self.entry.configure(bg=theme.token("surface_input"))
        self._glow = True
        self._pulse_glow(0)

    def _pulse_glow(self, i: int):
        """Parıltıyı yumuşakça nefes aldır (mikro-animasyon)."""
        if not getattr(self, "_glow", False):
            return
        # PRIMARY -> blend(BG, PRIMARY, 0.55) arasında salın
        t = (math.sin(i / 6.0) + 1) / 2
        col = _blend(theme.BG, theme.PRIMARY, 0.45 + 0.35 * t)
        try:
            self.wrap.configure(bg=col)
        except tk.TclError:
            return
        if i < 1000:
            self.after(90, lambda: self._pulse_glow(i + 1))

    def _focus_out(self, _e=None):
        self._glow = False
        self.wrap.configure(bg=theme.SURFACE_ALT)
        if not self.entry.get():
            self._has_placeholder = True
            self.entry.delete(0, tk.END)
            self.entry.insert(0, self._placeholder)
            self.entry.configure(fg=theme.MUTED)

    # -- gönder ------------------------------------------------------------
    def _submit(self, _e=None):
        txt = self.entry.get()
        if self._has_placeholder or not txt.strip():
            return
        if self._on_send:
            self._on_send(txt.strip())
        self.entry.delete(0, tk.END)

    def _submit_btn(self):
        self._submit()

    def _btn_enter(self, _e=None):
        self.btn_send.configure(bg=theme.PRIMARY, fg=theme.ON_ACCENT)
        try:
            self.btn_send.configure(relief=tk.FLAT)
        except tk.TclError:
            pass

    def _btn_leave(self, _e=None):
        self.btn_send.configure(bg=self._base_btn_bg, fg=theme.ON_SECONDARY)

    def focus(self):
        self.entry.focus_set()


# ==========================================================================
# Birleşik şablon
# ==========================================================================
class ChatTemplate(tk.Frame):
    """Hazır sohbet ekranı: StatusBar + MessageList + NeonEntry."""

    def __init__(self, master, room_code: str = "3K7QX"):
        super().__init__(master, bg=theme.BG)
        self.pack(fill=tk.BOTH, expand=True)

        import tkinter.font as tkfont
        base = tkfont.nametofont("TkDefaultFont")
        base.configure(family=theme.FONT_FAMILY, size=theme.FONT_SIZE)

        self.fonts = {
            "title": (theme.FONT_FAMILY, 18, "bold"),
            "body": (theme.FONT_FAMILY, theme.FONT_CHAT),
            "meta": (theme.FONT_CODE, 9),
            "code": (theme.FONT_CODE, 15, "bold"),
            "small": (theme.FONT_FAMILY, 9),
        }

        self.status = StatusBar(self, room_code=room_code,
                                on_theme_toggle=self._toggle)
        self.status.pack(side=tk.TOP, fill=tk.X)

        # DÜZELTME: alt yazma çubuğu ÖNCE side=BOTTOM ile sabitlenir;
        # mesaj listesi kalan alanı doldurur (flex:1). Liste uzadıkça
        # giriş kutusu asla ezilmez, aşağı kaymaz, arkada kalmaz.
        self.entry = NeonEntry(self, on_send=self._send)
        self.entry.pack(side=tk.BOTTOM, fill=tk.X)

        self.messages = MessageList(self, self.fonts)
        self.messages.pack(fill=tk.BOTH, expand=True, pady=(0, 0))

        self.bind("<Configure>", self._responsive)
        self._seed()

    # -- duyarlı spacing ---------------------------------------------------
    def _responsive(self, e):
        if e.widget is not self:
            return
        sp = theme.spacing_for(e.width)
        # bar yüksekliği kırılıma göre
        self.status.configure(height=sp["bar_h"])

    def _toggle(self):
        theme.toggle_theme()
        # şablon basitçe yeniden kurulur (token'lar global)
        w = self.winfo_toplevel()
        for child in w.winfo_children():
            child.destroy()
        ChatTemplate(w)

    def _send(self, text: str):
        self.messages.hide_typing()
        self.messages.add("sen", text, _now(), mine=True)
        # karşı taraf "yazıyor..." sonra yanıtlar (demo)
        self.after(700, lambda: self.messages.show_typing("ada"))
        self.after(1900, self._auto_reply)

    def _auto_reply(self):
        self.messages.hide_typing()
        self.messages.add("ada", "Aldım — bu mesaj uçtan uca şifreli. 🔐",
                          _now(), mine=False)

    def _seed(self):
        self.messages.add_system(
            "Oda kuruldu. 5 haneli kodu paylaşan katılımcılar bağlanabilir.",
            _now())
        self.messages.add("ada", "Selam! Kanal güvenli, E2EE aktif.",
                          _now(), mine=False)
        self.messages.add("sen", "Harika, anahtarı doğruladım. 🔑", _now(),
                          mine=True)
        self.messages.add("ada",
                          "Bu uzun bir mesaj — baloncuk otomatik sarılıyor "
                          "ve köşe yarıçapı asimetrik (12 12 12 2).",
                          _now(), mine=False)
        self.messages.show_typing("ada")


def _now() -> str:
    import time
    return time.strftime("%H:%M")


# ==========================================================================
# Doğrudan çalıştırma
# ==========================================================================
def run_demo():
    root = tk.Tk()
    root.title(f"{theme.APP_NAME} — {theme.THEME_NAME} şablonu")
    root.configure(bg=theme.BG)
    root.geometry("860x640")
    root.minsize(420, 480)
    ChatTemplate(root)
    root.mainloop()


if __name__ == "__main__":
    run_demo()
