"""Tkinter arayüzü: Dinamik Açık / Koyu Tema (Theme Toggle), yüksek kontrast ve akıcı UX.

Tüm ağ işleri arka planda yürür; UI thread'i yalnızca `after()` ile
beslenir (Tkinter thread-safe değildir).
"""
from __future__ import annotations

import logging
import math
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from . import config, honeypot, messages, theme
from . import emoji_picker, media, nicknames
from .components import _lerp
from .room import Client, Host
from .storage import ChatStore

logger = logging.getLogger("secretchat.ui")


class ChatApp:
    """Tek pencereli modern uygulama: karşılama -> sohbet (Açık & Koyu mod destekli)."""

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"{theme.APP_NAME} — {theme.APP_VERSION}")
        root.configure(bg=theme.BG)
        root.geometry("880x620")
        root.minsize(720, 500)

        self.store = ChatStore()
        self.room: Optional[object] = None  # Host veya Client
        self.room_code = ""
        # Kullanıcı punto tercihi (mesaj puntusu 9–18, varsayılan 12)
        self._font_size_base = theme.load_saved_font_size()
        self._font_scale_cache: dict = {}
        self._fonts()

        # ── Broker Ön-Bağlantı (Pre-Connect) ────────────────────────────────
        # Karşılama ekranı açıkken arka planda hangi broker'ın erişilebilir
        # olduğunu saptarız. Buton ilk tıklandığında Host/Client bu bilgiyi
        # kullanarak doğrudan çalışan broker'a bağlanır — ilk tıklama hatası
        # ortadan kalkar.
        self._broker_index: Optional[int] = None  # None = henüz bilinmiyor
        self._broker_probe_done = threading.Event()
        threading.Thread(target=self._probe_broker, daemon=True).start()

        self.container = tk.Frame(root, bg=theme.BG)
        self.container.pack(fill=tk.BOTH, expand=True)

        self.welcome: Optional[tk.Frame] = None
        self.chat: Optional[tk.Frame] = None
        self._msg_i = 0
        # Mesaj kayıt defteri: msg_id -> {sender, text/caption, kind, mine,
        #   row, bubble, body, meta, deleted, edited}
        self._msg_registry: dict = {}
        self._bubble_menu: Optional[tk.Menu] = None
        # ---- Honeypot durumu (gizli girdi tuzağı + oturum kilidi) ----
        self._honeypot_tripped = False
        self._hp_var = tk.StringVar()
        self._hp_var.trace_add("write", self._on_hp_write)
        self._show_welcome()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- fontlar

    def _fonts(self):
        import tkinter.font as tkfont
        auto = self._font_scale_for(theme.FONT_FAMILY)
        user = getattr(self, "_font_size_base", 12) / 12.0

        def _sz(n: int) -> int:
            return max(8, round(n * auto * user))

        base = tkfont.nametofont("TkDefaultFont")
        base.configure(family=theme.FONT_FAMILY, size=_sz(theme.FONT_SIZE))
        self.f_title = (theme.FONT_FAMILY, _sz(22), "bold")
        self.f_sub = (theme.FONT_FAMILY, _sz(10))
        self.f_normal = (theme.FONT_FAMILY, _sz(theme.FONT_SIZE))
        self.f_chat = (theme.FONT_FAMILY, _sz(theme.FONT_CHAT))
        self.f_code = (theme.FONT_CODE, 15, "bold")
        self.f_small = (theme.FONT_FAMILY, _sz(9))

    def _font_scale_for(self, family: str) -> float:
        """Özel fontun satır yüksekliğini varsayılana oranla (0.7–1.3).

        Dekoratif fontlar aynı puntoda çok iri/ufak dizilir ve buton/kart
        ölçülerini bozar. Oran önbelleğe alınır; açılış dahil her _fonts()
        çağrısında aynı değer bulunur.
        """
        from . import fonts as _fonts_mod
        if family == _fonts_mod.DEFAULT_FAMILY:
            return 1.0
        cache = getattr(self, "_font_scale_cache", None)
        if cache is None:
            cache = self._font_scale_cache = {}
        if family in cache:
            return cache[family]
        try:
            import tkinter.font as tkfont
            if family not in tkfont.families():
                # Dosyası silinmiş/kayıtsız aile: yedek fontun metriğine göre
                # ölçekleme yapma, nötr kal (yanlış kaymayı önler).
                scale = 1.0
            else:
                base = tkfont.Font(family=_fonts_mod.DEFAULT_FAMILY, size=theme.FONT_CHAT)
                probe = tkfont.Font(family=family, size=theme.FONT_CHAT)
                ratio = base.metrics("linespace") / max(1, probe.metrics("linespace"))
                scale = min(1.3, max(0.7, round(ratio, 2)))
        except Exception:
            scale = 1.0
        cache[family] = scale
        return scale

    # ================================================================ BROKER ÖN-BAĞLANTI

    def _probe_broker(self) -> None:
        """Arka planda broker keşfi yapar (pre-connect / warm-up).

        Boş bir SignalingChannel açarak hangi broker'ın erişilebilir olduğunu
        saptar ve `self._broker_index`'e kaydeder. Bu sayede kullanıcı
        "Oda Kur" / "Katıl" butonuna ilk basışında Host/Client zaten çalışan
        broker'a yönelir — ilk tıklama hatası ortadan kalkar.
        """
        from .signaling import SignalingChannel
        try:
            probe = SignalingChannel(topics=())  # abonelik yok, sadece bağlantı testi
            ok = probe.start(timeout=10.0)
            if ok:
                self._broker_index = probe.broker_index
                logger.debug("Broker ön-bağlantı başarılı: index=%d", self._broker_index)
            else:
                logger.debug("Broker ön-bağlantı başarısız — ilk tıklamada yeniden denenecek")
            try:
                probe.stop()
            except Exception:
                pass
        except Exception as exc:
            logger.debug("Broker probe hatası: %s", exc)
        finally:
            self._broker_probe_done.set()

    # ================================================================ KARŞILAMA EKRANI

    def _show_welcome(self):
        if self.welcome is not None:
            self.welcome.destroy()
            self.welcome = None

        if self.chat is not None:
            self.chat.destroy()
            self.chat = None

        self.welcome = tk.Frame(self.container, bg=theme.BG)
        self.welcome.pack(fill=tk.BOTH, expand=True)

        # Üst Araç Çubuğu (Tema Değiştirme Butonu için)
        # Köşe düğmeleri için bol nefes payı: sağda/yanda 24, üstte 20.
        top_bar = tk.Frame(self.welcome, bg=theme.BG, padx=24, pady=20)
        top_bar.pack(fill=tk.X)

        theme_txt = "☀️ Açık Mod" if theme.is_dark() else "🌙 Koyu Mod"
        self.btn_theme_welcome = tk.Button(
            top_bar, text=theme_txt, font=self.f_small,
            bg=theme.BG_CARD, fg=theme.FG, relief=tk.FLAT,
            activebackground=theme.BG_HOVER, activeforeground=theme.FG,
            cursor="hand2", padx=10, pady=4,
            highlightbackground=theme.BORDER, highlightthickness=1,
            command=self._toggle_theme
        )
        self.btn_theme_welcome.pack(side=tk.RIGHT)
        self.btn_settings_welcome = tk.Button(
            top_bar, text="⚙ Ayarlar", font=self.f_small,
            bg=theme.BG_CARD, fg=theme.FG, relief=tk.FLAT,
            activebackground=theme.BG_HOVER, activeforeground=theme.FG,
            cursor="hand2", padx=10, pady=4,
            highlightbackground=theme.BORDER, highlightthickness=1,
            command=self._show_settings_dialog
        )
        self.btn_settings_welcome.pack(side=tk.RIGHT, padx=(0, 12))

        # Kart Çerçevesi (Border & Card effect) — kaydırmalı ortalı alan:
        # içerik sığdığında ortalanır, taşınca dikey kaydırma belirir.
        self.welcome_vbar = ttk.Scrollbar(self.welcome, orient=tk.VERTICAL)
        self.welcome_canvas = tk.Canvas(self.welcome, bg=theme.BG,
                                        highlightthickness=0, bd=0)
        self.welcome_canvas.configure(yscrollcommand=self._welcome_yscroll)
        self.welcome_vbar.configure(command=self.welcome_canvas.yview)
        self.welcome_inner = tk.Frame(self.welcome_canvas, bg=theme.BG)
        self._welcome_win = self.welcome_canvas.create_window(
            (0, 0), window=self.welcome_inner, anchor="center")
        self.welcome_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        outer_box = tk.Frame(self.welcome_inner, bg=theme.BORDER, padx=1, pady=1)
        outer_box.place(relx=0.5, rely=0.5, anchor="center")

        box = tk.Frame(outer_box, bg=theme.BG_PANEL, padx=36, pady=28)
        box.pack(fill=tk.BOTH, expand=True)
        # Duyarlı kart: dar/basık pencerede dolgular kısalır (_responsive_welcome)
        self._welcome_outer = outer_box
        self._welcome_box = box
        self._welcome_compact = "unset"
        self._welcome_vbar_shown = False
        self._welcome_layout_running = False
        self._welcome_layout_dirty = False
        self._welcome_dead = False
        self.welcome.bind("<Destroy>", self._on_welcome_destroy)
        self.welcome_canvas.bind("<Configure>", self._on_welcome_canvas)
        outer_box.bind("<Configure>", lambda _e: self._request_welcome_layout())
        self.welcome_canvas.bind("<MouseWheel>", self._on_welcome_wheel)
        self.welcome_canvas.bind("<Button-4>", self._on_welcome_wheel)
        self.welcome_canvas.bind("<Button-5>", self._on_welcome_wheel)

        tk.Label(box, text="🔐 SecretChat", font=self.f_title,
                 bg=theme.BG_PANEL, fg=theme.FG).pack(pady=(0, 4))
        tk.Label(box, text="Uçtan Uca Şifreli • Sıfır İz • E2EE Güvenli Sohbet",
                 font=self.f_sub, bg=theme.BG_PANEL,
                 fg=theme.ACCENT_NEON).pack(pady=(0, 22))

        # ---- Takma Ad Alanı
        tk.Label(box, text="Kullanıcı Adı (Benzersiz)", font=self.f_normal, bg=theme.BG_PANEL,
                 fg=theme.FG_DIM).pack(anchor="w")
        tk.Label(box, text="Boş bırakırsan gizli bir rumuz atanır (örn. mavi bulut 1923)",
                 font=self.f_small, bg=theme.BG_PANEL, fg=theme.FG_MUTED).pack(anchor="w")

        if not hasattr(self, "nick_var"):
            self.nick_var = tk.StringVar()

        nick_frame = tk.Frame(box, bg=theme.BORDER, padx=1, pady=1)
        nick_frame.pack(fill=tk.X, pady=(4, 4))

        self.nick_entry = tk.Entry(
            nick_frame, textvariable=self.nick_var, font=self.f_chat,
            bg=theme.BG_INPUT, fg=theme.FG, insertbackground=theme.FG,
            selectbackground=theme.ACCENT, selectforeground=theme.ON_ACCENT,
            relief=tk.FLAT, width=30
        )
        self.nick_entry.pack(fill=tk.X, ipady=7, padx=1, pady=1)

        # Canlı doğrulama geri bildirim etiketi
        self.nick_feedback = tk.Label(
            box, text="2-24 karakter — boş bırakılırsa otomatik gizli rumuz atanır",
            font=self.f_small, bg=theme.BG_PANEL, fg=theme.FG_MUTED
        )
        self.nick_feedback.pack(anchor="w", pady=(0, 16))
        self.nick_var.trace_add("write", self._on_nick_change)
        self._on_nick_change()  # İlk durumu kontrol et

        # ---- Oda kur butonu
        self.btn_host = tk.Button(
            box, text="⚡ Yeni Oda Kur (Host)", font=self.f_chat,
            bg=theme.ACCENT, fg=theme.ON_ACCENT, relief=tk.FLAT,
            activebackground=theme.ACCENT_HV, activeforeground=theme.ON_ACCENT,
            cursor="hand2", command=self._start_host
        )
        self.btn_host.pack(fill=tk.X, ipady=8, pady=(0, 10))

        # ---- Ayraç
        sep = tk.Frame(box, bg=theme.BORDER, height=1)
        sep.pack(fill=tk.X, pady=8)

        tk.Label(box, text="veya 5 haneli oda kodu ile katıl", font=self.f_small,
                 bg=theme.BG_PANEL, fg=theme.FG_DIM).pack(pady=(0, 8))

        row = tk.Frame(box, bg=theme.BG_PANEL)
        row.pack(fill=tk.X)

        if not hasattr(self, "code_var"):
            self.code_var = tk.StringVar()
            self.code_var.trace_add("write", self._on_code_change)

        code_frame = tk.Frame(row, bg=theme.BORDER, padx=1, pady=1)
        code_frame.pack(side=tk.LEFT, expand=True, fill=tk.X)

        self.code_entry = tk.Entry(
            code_frame, textvariable=self.code_var, font=self.f_code,
            bg=theme.BG_INPUT, fg=theme.ACCENT_NEON,
            insertbackground=theme.FG,
            selectbackground=theme.ACCENT, selectforeground=theme.ON_ACCENT,
            relief=tk.FLAT, width=12, justify="center"
        )
        self.code_entry.pack(fill=tk.X, ipady=6, padx=1, pady=1)

        self.btn_join = tk.Button(
            row, text="Katıl →", font=self.f_chat,
            bg=theme.BG_HOVER, fg=theme.FG, relief=tk.FLAT,
            activebackground=theme.ACCENT, activeforeground=theme.ON_ACCENT,
            cursor="hand2", command=self._join_room
        )
        self.btn_join.pack(side=tk.LEFT, padx=(10, 0), ipady=6, ipadx=14)

        self.welcome_status = tk.Label(
            box, text="", font=self.f_small,
            bg=theme.BG_PANEL, fg=theme.WARN, wraplength=380
        )
        self.welcome_status.pack(pady=(14, 0))

        self.nick_entry.focus_set()
        self.root.bind("<Return>", self._on_enter_key)

        # Honeypot: karşılama ekranına ekran dışı gizli tuzak girdisi yerleştir
        self._install_honeypot_input(self.welcome)

        # İlk yerleşim: kartı ortala / gerekirse kaydır
        self._request_welcome_layout()

    # ---------------------------------------------------------------- honeypot

    def _install_honeypot_input(self, parent) -> None:
        """Gizli tuzak girdisi (web'deki `display:none` eşdeğeri).

        Normal kullanıcı bu alanı asla görmez/dokunmaz; otomasyon araçları
        ise formları toplu doldururken bu alana da yazar → trace alarmı
        tetiklenir ve oturum anında kilitlenir.
        """
        try:
            hp = tk.Entry(parent, textvariable=self._hp_var, width=1,
                          bg=theme.BG, fg=theme.BG, insertbackground=theme.BG,
                          relief=tk.FLAT, highlightthickness=0)
            hp.place(x=-9000, y=-9000)  # ekran dışı konum
        except tk.TclError:
            logger.debug("honeypot girdisi yerleştirilemedi")

    def _on_hp_write(self, *_a) -> None:
        """Gizli alana veri yazıldıysa: bot/otomasyon tespiti → oturumu kilitle."""
        if self._hp_var.get():
            honeypot.alert("honeypot-hidden-input",
                           "gizli form alanına otomatik veri yazıldı — "
                           "bot/otomasyon tespit edildi",
                           dedupe=True)
            self._honeypot_trip("gizli input")

    def _honeypot_trip(self, source: str) -> None:
        """Tuzak tetiklendi: yönetici logu + uyarı + aktif bağlantıyı anında kes."""
        if self._honeypot_tripped:
            return
        self._honeypot_tripped = True
        logger.warning("Honeypot tetiklendi (%s) — oturum kilitlendi", source)
        if self.room is not None:  # aktif odayı anında bırak
            try:
                self._leave_chat()
            except Exception as exc:
                logger.debug("honeypot ayrılma hatası: %s", exc)
        self._honeypot_lock_notice()

    def _honeypot_lock_notice(self) -> None:
        """Kilit uyarısını SENKRON göster.

        `after(0)` ile asenkron yazılsaydı, trip ile aynı tıkta tetiklenen
        aldatıcı "Oda bulunamadı." yanıtı ana döngüde ezilebilir veya hiç
        çalışmayabilir (mainloop'suz ortam). Senkron yazım her iki ortamda
        da aynı sıralamayı garanti eder.
        """
        msg = "⚠ Otomasyon algılandı — oturum kilitlendi."
        if self.welcome is not None and self.welcome.winfo_exists():
            self._set_welcome_status(msg, theme.ERR)
        elif self.chat is not None and self.chat.winfo_exists():
            self._set_status(msg, theme.ERR)

    def _on_welcome_destroy(self, event) -> None:
        """Karşılama yok olurken yerleşim işlerini durdur (teardown koruması)."""
        try:
            if event.widget is not self.welcome:
                return
        except Exception:
            return
        self._welcome_dead = True

    def _on_welcome_canvas(self, event) -> None:
        """Tuval boyutlanınca kart sığmasını + yerleşimi tazele."""
        if getattr(self, "_welcome_dead", False):
            return
        try:
            if event.widget is not self.welcome_canvas:
                return
        except Exception:
            return
        try:
            self._responsive_welcome()
        except Exception:
            pass
        self._request_welcome_layout()

    def _request_welcome_layout(self) -> None:
        """Karşılama yerleşimini hemen tazele.

        Configure olayları zaten kuyrukludur; işlem sub-ms düzeyinde
        olduğundan birleştirme (coalescing) için after_idle kullanılmaz —
        bekleyen betikler teardown anında gürültü çıkarıyordu.
        """
        if getattr(self, "_welcome_dead", False):
            return
        try:
            self._layout_welcome()
        except Exception:
            pass

    def _layout_welcome(self) -> None:
        """Kartı ortala; taşıyorsa kaydırma çubuğunu göster."""
        if getattr(self, "_welcome_layout_running", False):
            self._welcome_layout_dirty = True
            return
        self._welcome_layout_running = True
        try:
            while True:
                self._welcome_layout_dirty = False
                self._layout_welcome_once()
                if not getattr(self, "_welcome_layout_dirty", False):
                    break
        finally:
            self._welcome_layout_running = False

    def _layout_welcome_once(self) -> None:
        # NOT: burada update_idletasks ÇAĞRILMAZ. Yok-oluş (teardown) sırasında
        # gelen Configure olayları içinde olay pompalamak özyinelemeye girip
        # yorumlayıcıyı çökertiyordu. Ölçüler bir kare gecikmeli de olsa
        # Configure akışıyla yakınsar; kritik olan gürültüsüzlüktür.
        try:
            if getattr(self, "_welcome_dead", False):
                return
            cv = getattr(self, "welcome_canvas", None)
            outer = getattr(self, "_welcome_outer", None)
            if cv is None or outer is None:
                return
            if not (cv.winfo_exists() and outer.winfo_exists()):
                return
        except tk.TclError:
            return
        try:
            cw, ch = max(1, cv.winfo_width()), max(1, cv.winfo_height())
        except tk.TclError:
            return
        if cw < 10 or ch < 10:
            return
        try:
            reqw = outer.winfo_reqwidth() + 16
            reqh = outer.winfo_reqheight() + 16
        except tk.TclError:
            return
        w, h = max(cw, reqw), max(ch, reqh)
        try:
            cv.itemconfigure(self._welcome_win, width=w, height=h)
            cv.coords(self._welcome_win, (w / 2, h / 2))
            cv.configure(scrollregion=(0, 0, w, h))
        except tk.TclError:
            return
        need = reqh > ch + 1
        if need != getattr(self, "_welcome_vbar_shown", False):
            self._welcome_vbar_shown = need
            try:
                if need:
                    self.welcome_vbar.pack(side=tk.RIGHT, fill=tk.Y)
                else:
                    self.welcome_vbar.pack_forget()
                    cv.yview_moveto(0)
            except tk.TclError:
                pass

    def _welcome_yscroll(self, first: str, last: str) -> None:
        try:
            self.welcome_vbar.set(first, last)
        except Exception:
            pass

    def _on_welcome_wheel(self, event) -> None:
        """Yalnızca kaydırma gerekiyorsa tekerleği karta ilet."""
        if not getattr(self, "_welcome_vbar_shown", False):
            return
        try:
            if getattr(event, "num", None) in (4,):
                self.welcome_canvas.yview_scroll(-3, "units")
            elif getattr(event, "num", None) in (5,):
                self.welcome_canvas.yview_scroll(3, "units")
            else:
                delta = getattr(event, "delta", 0)
                self.welcome_canvas.yview_scroll(-1 if delta > 0 else 1, "units")
        except Exception:
            pass

    def _on_code_change(self, *_a) -> None:
        """Oda kodu girdisi: büyük harfe çevir, uzunluğu sınırla, tuzağı izle.

        Not: eski `[:5]` kırpması tam tuzak adlarının (admin-secrets, vault)
        görülmesini engelliyordu — kırpma kaldırıldı, doğrulama katılaştı.
        """
        raw = self.code_var.get()
        capped = raw.upper()[:24]
        if raw != capped:
            self.code_var.set(capped)
        if honeypot.is_trap_room(capped):
            honeypot.alert("honeypot-join-input-typing",
                           f"tuzak oda adı girildi: {capped!r}", dedupe=True)

    def _on_nick_change(self, *args):
        if not hasattr(self, "nick_feedback") or not self.nick_feedback.winfo_exists():
            return
        nick = self.nick_var.get().strip()
        if not nick:
            self.nick_feedback.configure(
                text="Boş bırakılırsa otomatik gizli rumuz atanır (örn. mavi bulut 1923)",
                fg=theme.FG_MUTED)
            return
        valid, msg = messages.validate_nickname(nick)
        if valid:
            self.nick_feedback.configure(text="✓ Uygun kullanıcı adı", fg=theme.OK)
        else:
            self.nick_feedback.configure(text=f"✗ {msg}", fg=theme.ERR)

    def _on_enter_key(self, _event):
        if self.welcome and self.welcome.winfo_ismapped():
            if self.code_var.get().strip():
                self._join_room()
            else:
                self._start_host()

    def _welcome_status(self, text: str, color: str = theme.WARN):
        if self.welcome and self.welcome.winfo_exists():
            self.welcome.after(0, lambda: self._set_welcome_status(text, color))

    def _set_welcome_status(self, text: str, color: str):
        if self.welcome and self.welcome.winfo_exists():
            self.welcome_status.configure(text=text, fg=color)

    def _busy(self, busy: bool):
        state = tk.DISABLED if busy else tk.NORMAL
        if hasattr(self, "btn_host") and self.btn_host.winfo_exists():
            self.btn_host.configure(state=state)
        if hasattr(self, "btn_join") and self.btn_join.winfo_exists():
            self.btn_join.configure(state=state)

    # ---------------------------------------------------------------- aksiyonlar

    def _start_host(self):
        if self._honeypot_tripped:
            self._honeypot_lock_notice()
            return
        raw_nick = self.nick_var.get().strip()
        valid, nick = nicknames.resolve_nickname(raw_nick)
        if not valid:
            self._welcome_status(nick, theme.ERR)
            return
        auto_nick = not raw_nick  # boş bırakıldı → gizli rumuz
        if auto_nick:
            self.nick_var.set(nick)
        self._busy(True)
        self._welcome_status("Oda açılıyor (güvenli kanal kuruluyor)...", theme.WARN)

        def work():
            from .room import Host as H

            # Ön-bağlantı probe'u bitmemişse en fazla 3s bekle.
            # Bu, uygulama yeni açılmışken "ilk tıklama" hatasını engeller.
            if not self._broker_probe_done.wait(timeout=3.0):
                logger.debug("Broker probe 3s içinde bitmedi; devam ediliyor")

            host = H(nick, status_cb=lambda s: self._welcome_status(s))

            # Probe başarılıysa kazanan broker indeksini ilet (soğuk başlatma bypass).
            if self._broker_index is not None:
                host.channel = None  # henüz açılmadı, güvenli
                host._preferred_broker = self._broker_index

            ok = host.start()

            # İlk deneme başarısızsa tek otomatik yeniden deneme yap.
            # (Broker intermittent hata durumu için yeterli; ikinci tıklama gerekmez)
            if not ok:
                self._welcome_status("Yeniden bağlanılıyor...", theme.WARN)
                host2 = H(nick, status_cb=lambda s: self._welcome_status(s))
                ok = host2.start()
                if ok:
                    host = host2

            self.root.after(0, lambda: self._host_ready(host, ok))

        threading.Thread(target=work, daemon=True).start()

    def _host_ready(self, host: Host, ok: bool):
        self._busy(False)
        if not ok:
            self._welcome_status("Bağlantı kurulamadı. İnterneti kontrol et.", theme.ERR)
            return
        self.room = host
        self.room_code = host.room_code
        self._enter_chat(is_host=True)

    def _join_room(self):
        if self._honeypot_tripped:
            self._honeypot_lock_notice()
            return
        raw_nick = self.nick_var.get().strip()
        raw_code = self.code_var.get().strip()
        valid, nick = nicknames.resolve_nickname(raw_nick)
        if not valid:
            self._welcome_status(nick, theme.ERR)
            return
        if not raw_nick:
            self.nick_var.set(nick)

        # ---- HONEYPOT: tuzak oda adı/kodu denemesi → anında algıla + kilitle ----
        # Yanıt kasıtlı olarak aldatıcıdır: "Oda bulunamadı" — saldırgan
        # tuzak olduğunu anlamaz; olay yalnızca yönetici loguna yazılır.
        if honeypot.is_trap_room(raw_code):
            honeypot.alert("honeypot-join-input",
                           f"tuzak oda kodu/adı ile katılım denendi: {raw_code!r}")
            self._honeypot_trip(f"tuzak oda girdisi: {raw_code!r}")
            # Aldatıcı yanıt SENKRON yazılır: trip'in kilit mesajını bilerek
            # ezer; saldırgan yalnızca "Oda bulunamadı." görmeli.
            if self.welcome is not None and self.welcome.winfo_exists():
                self._set_welcome_status("Oda bulunamadı.", theme.ERR)
            elif self.chat is not None and self.chat.winfo_exists():
                self._set_status("Oda bulunamadı.", theme.ERR)
            return

        ok_code, code_or_reason = messages.validate_room_code(raw_code)
        if not ok_code:
            self._welcome_status(code_or_reason, theme.ERR)
            return
        code = code_or_reason
        self._busy(True)
        self._welcome_status("Odaya bağlanılıyor (el sıkışma)...", theme.WARN)

        def work():
            from .room import Client as C

            # Ön-bağlantı probe'u bitmemişse en fazla 3s bekle.
            if not self._broker_probe_done.wait(timeout=3.0):
                logger.debug("Broker probe 3s içinde bitmedi; devam ediliyor")

            client = C(nick, code, status_cb=lambda s: self._welcome_status(s))
            client.on_rejected = lambda reason: self.root.after(
                0, lambda: self._on_client_rejected(client, reason))

            ok = client.start() and client.wait_joined()

            # İlk deneme başarısızsa (el sıkışma zaman aşımı) tek yeniden deneme.
            if not ok and not client._joined.is_set():
                self._welcome_status("Yeniden bağlanılıyor...", theme.WARN)
                try:
                    client.stop()
                except Exception:
                    pass
                client2 = C(nick, code, status_cb=lambda s: self._welcome_status(s))
                client2.on_rejected = lambda reason: self.root.after(
                    0, lambda: self._on_client_rejected(client2, reason))
                ok = client2.start() and client2.wait_joined()
                if ok:
                    client = client2

            self.root.after(0, lambda: self._join_ready(client, ok))

        threading.Thread(target=work, daemon=True).start()

    def _on_client_rejected(self, client: Client, reason: str):
        self._busy(False)
        self._welcome_status(f"Katılım Reddedildi: {reason}", theme.ERR)
        try:
            client.stop()
        except Exception:
            pass

    def _join_ready(self, client: Client, ok: bool):
        self._busy(False)
        if not ok:
            err_msg = client.last_error or "Odaya ulaşılamadı. Kodu ve interneti kontrol et."
            self._welcome_status(err_msg, theme.ERR)
            try:
                client.stop()
            except Exception:
                pass
            return
        self.room = client
        self.room_code = client.room_code
        self._enter_chat(is_host=False)

    # ================================================================ SOHBET EKRANI

    def _enter_chat(self, is_host: bool):
        if self.welcome is not None:
            self.welcome.destroy()
            self.welcome = None
        self.root.unbind("<Return>")

        # ----------------------------------------------------------------
        # ÖNCE: Oda callback'lerini kaydet — widget'lardan ÖNCE bağlanmalı!
        # Dispatch thread herhangi bir anda on_message / on_peer_left
        # tetikleyebilir; bu callback'ler root.after() ile güvenle sıraya
        # girer, henüz oluşturulmamış widget'lara erişmeye çalışmaz çünkü
        # _append_message / _refresh_members içinde hasattr + winfo_exists
        # kontrolleri mevcuttur.
        # ----------------------------------------------------------------
        self.room.on_message = lambda s, t, sys_, m="": self.root.after(
            0, lambda: self._append_message(s, t, sys_, mine=False, msg_id=m or None))
        self.room.on_image = lambda s, b, c, m="": self.root.after(
            0, lambda: self._append_image_message(s, b, c, False, msg_id=m or None))
        self.room.on_edit = lambda s, i, t: self.root.after(
            0, lambda: self._on_remote_edit(s, i, t))
        self.room.on_delete = lambda s, i: self.root.after(
            0, lambda: self._on_remote_delete(s, i))
        self.room.on_sas = lambda s: self.root.after(
            0, lambda: self._append_system(f"🔐 Doğrulama kodu {s} — "
                                           "karşı taraf ile karşılaştırın."))
        if isinstance(self.room, Host):
            self.room.on_peer_left = lambda n: self.root.after(
                0, lambda: self._refresh_members())
        # Fotoğraf PhotoImage referansları (GC'ye karşı saklanır)
        self._photo_refs: list = getattr(self, "_photo_refs", [])
        # Yeni odaya girerken mesaj kayıt defterini sıfırla
        self._msg_registry = {}
        self._close_bubble_menu()
        # Üst bar kompaktlık durumu + pencere boyutu dinleyicisi
        self._top_compact = False
        self._reflow_after = None

        self.chat = tk.Frame(self.container, bg=theme.BG)
        self.chat.pack(fill=tk.BOTH, expand=True)

        # ---------------- üst panel: durum + oda kodu + tema + çıkış
        self.chat_top = tk.Frame(self.chat, bg=theme.BG_PANEL, padx=14, pady=10)
        self.chat_top.pack(side=tk.TOP, fill=tk.X)

        self.status_dot = tk.Label(self.chat_top, text="●", font=(theme.FONT_FAMILY, 12),
                                   bg=theme.BG_PANEL, fg=theme.OK)
        self.status_dot.pack(side=tk.LEFT)
        self.status_lbl = tk.Label(self.chat_top, text="Bağlandı", font=self.f_normal,
                                   bg=theme.BG_PANEL, fg=theme.FG)
        self.status_lbl.pack(side=tk.LEFT, padx=(6, 12))

        # Oda Kodu Rozeti
        self.code_box = tk.Frame(self.chat_top, bg=theme.BG_CARD, padx=8, pady=3,
                                 highlightbackground=theme.BORDER, highlightthickness=1)
        self.code_box.pack(side=tk.LEFT, padx=(0, 10))

        self.code_lbl_prefix = tk.Label(self.code_box, text="ODA:", font=self.f_small,
                                        bg=theme.BG_CARD, fg=theme.FG_DIM)
        self.code_lbl_prefix.pack(side=tk.LEFT)

        self.code_lbl = tk.Label(self.code_box, text=self.room_code, font=self.f_code,
                                 bg=theme.BG_CARD, fg=theme.ACCENT_NEON)
        self.code_lbl.pack(side=tk.LEFT, padx=6)

        self.btn_copy = tk.Button(self.code_box, text="📋 Kopyala", font=self.f_small,
                                  bg=theme.BG_HOVER, fg=theme.FG, relief=tk.FLAT,
                                  activebackground=theme.ACCENT, activeforeground=theme.ON_ACCENT,
                                  cursor="hand2", command=self._copy_code)
        self.btn_copy.pack(side=tk.LEFT, padx=(2, 0), ipadx=4)

        self.members_lbl = tk.Label(self.chat_top, text="", font=self.f_small,
                                    bg=theme.BG_PANEL, fg=theme.FG_DIM)
        self.members_lbl.pack(side=tk.LEFT, padx=10)

        # Sağ aksiyonlar: Ayrıl + Tema Değiştir + Kayıt
        self.btn_leave = tk.Button(
            self.chat_top, text="🚪 Odadan Ayrıl", font=self.f_small,
            bg=theme.BG_HOVER, fg=theme.ERR, relief=tk.FLAT,
            activebackground=theme.ERR, activeforeground="#ffffff",
            cursor="hand2", command=self._leave_chat
        )
        self.btn_leave.pack(side=tk.RIGHT, padx=(8, 0), ipadx=8, ipady=2)

        theme_txt = "☀️ Açık" if theme.is_dark() else "🌙 Koyu"
        self.btn_theme_chat = tk.Button(
            self.chat_top, text=theme_txt, font=self.f_small,
            bg=theme.BG_HOVER, fg=theme.FG, relief=tk.FLAT,
            activebackground=theme.BG_HOVER, activeforeground=theme.FG,
            cursor="hand2", command=self._toggle_theme
        )
        self.btn_theme_chat.pack(side=tk.RIGHT, padx=(8, 0), ipadx=8, ipady=2)
        self.btn_settings_chat = tk.Button(
            self.chat_top, text="⚙", font=self.f_small,
            bg=theme.BG_HOVER, fg=theme.FG, relief=tk.FLAT,
            activebackground=theme.BG_HOVER, activeforeground=theme.FG,
            cursor="hand2", command=self._show_settings_dialog
        )
        self.btn_settings_chat.pack(side=tk.RIGHT, padx=(10, 0), ipadx=10, ipady=2)

        self.save_var = tk.BooleanVar(value=False)
        self.save_cb = tk.Checkbutton(
            self.chat_top, text="Geçmişi Kaydet", font=self.f_small,
            variable=self.save_var, command=self._toggle_recording,
            bg=theme.BG_PANEL, fg=theme.FG_DIM,
            activebackground=theme.BG_PANEL, activeforeground=theme.FG,
            selectcolor=theme.BG_INPUT, relief=tk.FLAT,
            highlightthickness=0, cursor="hand2"
        )
        self.save_cb.pack(side=tk.RIGHT)

        # ---------------- mesaj alanı
        # DÜZELTME-1: chat_mid henüz pack EDİLMEZ. Önce alt bar side=BOTTOM
        # ile yerini ayırır, mesaj alanı kalan her şeyi doldurur (flex:1).
        # pack_propagate(False) EKLENMEZ — expand=True ile height talebi değil
        # gerçek container boyutu kullanılır.
        self.chat_mid = tk.Frame(self.chat, bg=theme.BG)

        # DÜZELTME-2: height=1 (minimum satır talebi) → widget boyut isteğini
        # sıfıra indirger; gerçek yükseklik pack geometrisi tarafından belirlenir.
        # Eski height=12 değeri (~280 px talep ediyordu) alt barı eziyordu.
        self.chat_text = tk.Text(
            self.chat_mid, wrap=tk.WORD, bg=theme.BG, fg=theme.FG,
            insertbackground=theme.FG, selectbackground=theme.ACCENT, selectforeground=theme.ON_ACCENT,
            font=self.f_chat, relief=tk.FLAT, padx=18, pady=14,
            height=1, state=tk.DISABLED, cursor="arrow", spacing1=5, spacing3=5
        )
        scroll = ttk.Scrollbar(self.chat_mid, command=self._on_chat_scroll)
        self.chat_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.chat_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Kullanıcı kaydırınca sabitleme çözülür (tekerlek + kaydırma çubuğu)
        self._chat_pinned = True
        self.chat_text.bind("<MouseWheel>", self._on_chat_user_scroll, add="+")
        self.chat_text.bind("<Button-4>", self._on_chat_user_scroll, add="+")
        self.chat_text.bind("<Button-5>", self._on_chat_user_scroll, add="+")

        # DÜZELTME-4: padding-bottom eşdeğeri — mesaj listesinin altına 80px boşluk
        # ekleyerek en son mesajın sabit alt barın arkasında kalmasını önler.
        # "spacer" tag'i her zaman son satır olarak tutulur (_ensure_bottom_spacer).
        self.chat_text.tag_configure("spacer", spacing3=80)

        self._update_chat_tag_colors()

        # ---------------- alt panel: giriş + gönder
        # DÜZELTME-3: SABİT ALT BAR — side=BOTTOM + pack_propagate(False):
        # yüksekliği 72px (spec 60-80px) ve mesaj listesinden bağımsız.
        # Scroll eden tek alan mesaj listesidir; bar asla ezilmez/kaybolmaz.
        # highlightthickness=1 → 1px üst kenarlık (ayıraç çizgisi) ekler.
        self.chat_bottom = tk.Frame(
            self.chat, bg=theme.BG_PANEL, padx=14, pady=8,
            height=72,
            highlightbackground=theme.BORDER, highlightthickness=1
        )
        self.chat_bottom.pack_propagate(False)
        # KRITIK SIRA: alt bar ÖNCE pack edilir (BOTTOM'u rezerve eder),
        # mesaj alanı SONRA expand=True ile kalan tüm alanı doldurur.
        self.chat_bottom.pack(side=tk.BOTTOM, fill=tk.X)

        # mesaj alanı: alt bar yerini aldıktan sonraki kalanı tamamen kaplar
        self.chat_mid.pack(fill=tk.BOTH, expand=True)

        self.msg_var = tk.StringVar()

        # DÜZELTME-4: kenarlık #1E293B (surface_alt) — odakta neon parıltı
        self.msg_entry_frame = tk.Frame(self.chat_bottom, bg=theme.SURFACE_ALT, padx=1, pady=1)
        self.msg_entry_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.msg_entry = tk.Entry(
            self.msg_entry_frame, textvariable=self.msg_var, font=self.f_chat,
            bg=theme.BG_INPUT, fg=theme.FG, insertbackground=theme.FG,
            selectbackground=theme.ACCENT, selectforeground=theme.ON_ACCENT,
            relief=tk.FLAT
        )
        self.msg_entry.pack(fill=tk.BOTH, expand=True, ipady=9, padx=1, pady=1)
        self.msg_entry.bind("<Return>", lambda e: self._send())
        self.msg_entry.bind("<FocusIn>", self._entry_focus_in)
        self.msg_entry.bind("<FocusOut>", self._entry_focus_out)
        self.msg_entry.bind("<Escape>", lambda e: self._cancel_inline_edit())

        # Fotoğraf + emoji kısayolları (modüler: media / emoji_picker)
        # Temiz ikon stili: düz zemin, tema uyumlu, hover'da neon vurgu.
        self.btn_emoji = tk.Button(
            self.chat_bottom, text="☺", font=("Segoe UI Emoji", 13),
            bg=theme.BG_PANEL, fg=theme.FG_DIM, relief=tk.FLAT,
            activebackground=theme.BG_HOVER, activeforeground=theme.ACCENT_NEON,
            cursor="hand2", command=self._show_emoji_picker,
            bd=0, highlightthickness=0, padx=6, pady=2
        )
        self.btn_emoji.pack(side=tk.LEFT, padx=(10, 0), ipady=7, fill=tk.Y)
        self._style_icon_button(self.btn_emoji, "Emoji seç")

        self.btn_photo = tk.Button(
            self.chat_bottom, text="🖼", font=("Segoe UI Emoji", 13),
            bg=theme.BG_PANEL, fg=theme.FG_DIM, relief=tk.FLAT,
            activebackground=theme.BG_HOVER, activeforeground=theme.ACCENT_NEON,
            cursor="hand2", command=self._pick_and_send_image,
            bd=0, highlightthickness=0, padx=6, pady=2
        )
        self.btn_photo.pack(side=tk.LEFT, padx=(4, 0), ipady=7, fill=tk.Y)
        self._style_icon_button(self.btn_photo, "Fotoğraf gönder")

        # DÜZELTME-5: Gönder butonu #7B2CBF (secondary) → hover'da #00F5D4
        # (primary); metin rengi de değişir ki kontrast her durumda AA kalsın.
        self.btn_send = tk.Button(
            self.chat_bottom, text="Gönder ➤", font=self.f_normal,
            bg=theme.SECONDARY, fg=theme.ON_SECONDARY, relief=tk.FLAT,
            activebackground=theme.PRIMARY, activeforeground=theme.ON_ACCENT,
            cursor="hand2", command=self._send
        )
        self.btn_send.pack(side=tk.LEFT, padx=(10, 0), ipady=7, ipadx=12, fill=tk.Y)
        self.btn_send.bind("<Enter>", lambda e: self.btn_send.configure(
            bg=theme.PRIMARY, fg=theme.ON_ACCENT))
        self.btn_send.bind("<Leave>", lambda e: self.btn_send.configure(
            bg=theme.SECONDARY, fg=theme.ON_SECONDARY))

        # Telegram tarzı satır-içi düzenleme çubuğu (gizli başlar):
        # Düzenle'ye basınca giriş kutusunun üstünde belirir, Gönder
        # "Kaydet"e dönüşür. Kutu tamamen silinip gönderilirse mesaj silinir.
        self._editing_msg_id: Optional[str] = None
        self._edit_bar = tk.Frame(
            self.chat, bg=theme.BG_PANEL, padx=14, pady=6,
            highlightbackground=theme.BORDER, highlightthickness=1,
        )
        self._edit_lbl = tk.Label(
            self._edit_bar, text="", font=self.f_small,
            bg=theme.BG_PANEL, fg=theme.ACCENT_NEON,
            anchor="w", justify=tk.LEFT,
        )
        self._edit_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._edit_cancel = tk.Button(
            self._edit_bar, text="✕", font=self.f_small,
            bg=theme.BG_PANEL, fg=theme.FG_DIM, relief=tk.FLAT, bd=0,
            activebackground=theme.BG_HOVER, activeforeground=theme.ERR,
            cursor="hand2", command=self._cancel_inline_edit,
        )
        self._edit_cancel.pack(side=tk.RIGHT)
        # packlenmedi → gizli; _start_inline_edit içinde side=BOTTOM ile
        # gösterilir (alt barın hemen üstünde belirir).

        # Tüm widget'ların gerçekten render edildiğinden emin ol (thread-safe flush).
        # Bu noktadan sonra dispatch thread'den gelen after() çağrıları güvenlidir.
        self.root.update_idletasks()

        # ---------------- ilk sistem mesajları ve üye sayacı
        if isinstance(self.room, Host):
            self._set_status("Bağlandı — oda açık", theme.OK)
            self._append_system("Oda kuruldu. 5 haneli kodu paylaşan katılımcılar bağlanabilir.")
        else:
            self._set_status("Bağlandı", theme.OK)
            self._append_system("Odaya katıldın. Sohbet uçtan uca şifreli (E2EE).")
        try:
            self._append_system(f"Rumuzun: {self.room.nickname} — gizliliğin için boş bırakırsan otomatik atanır.")
        except Exception:
            pass
        self._refresh_members()

        # Odaya girince mesaj kutusuna odaklan
        self.msg_entry.focus_set()

        # Honeypot: sohbet ekranına da ekran dışı gizli tuzak girdisi
        self._install_honeypot_input(self.chat)

        # Duyarlı düzen: sohbet çerçevesi boyutlanınca akışı tazele
        # (yalnızca çerçevenin kendi olayı işlenir, çocuklar elenir)
        self.chat.bind("<Configure>", self._on_chat_resize)
        try:
            self._responsive_topbar(force=True)
        except Exception:
            pass

    def _on_chat_resize(self, event) -> None:
        """Sohbet çerçevesi boyutlanınca akışı tazele (yalnızca kendi olayı)."""
        try:
            if event.widget is not self.chat:
                return
        except Exception:
            return
        self._request_reflow()

    def _on_chat_scroll(self, *args) -> None:
        """Kaydırma çubuğu kullanıcı hareketi: sabiti çöz, görünümü uygula."""
        self._chat_pinned = False
        try:
            self.chat_text.yview(*args)
        except Exception:
            pass

    def _on_chat_user_scroll(self, _event=None) -> None:
        """Tekerlek ile kaydırma: sonda-sabitleme çözülür (varsayılan kayar)."""
        self._chat_pinned = False

    # ---------------------------------------------------------------- dinamik tema geçişi

    def _toggle_theme(self):
        """Temayı Açık / Koyu arasında dinamik olarak değiştir."""
        theme.toggle_theme()
        self.root.configure(bg=theme.BG)
        self.container.configure(bg=theme.BG)

        if self.welcome is not None and self.welcome.winfo_exists():
            self._show_welcome()
        elif self.chat is not None and self.chat.winfo_exists():
            self._apply_chat_theme()

    # ------------------------------------------------------- yazı tipi değiştir
    def _center_over_parent(self, win: tk.Toplevel) -> None:
        """Açılır pencereyi ana pencerenin ortasına al (yapışık durmaz).

        İçerik ölçüldükten sonra konumlanır; sığmazsa ekran sınırına çekilir.
        """
        try:
            self.root.update_idletasks()
            win.update_idletasks()
            rw, rh = self.root.winfo_width(), self.root.winfo_height()
            rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
            ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
            if rw < 50 or rh < 50:  # ana pencere henüz ölçülmediyse ortala-geç
                return
            x = rx + max(0, (rw - ww) // 2)
            y = ry + max(0, (rh - wh) // 2)
            try:  # çoklu monitörde ekran dışına taşmayı engelle
                sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
                x = min(max(0, x), max(0, sw - ww))
                y = min(max(0, y), max(0, sh - wh))
            except Exception:
                pass
            win.geometry(f"+{x}+{y}")
            win.minsize(ww, wh)
        except Exception as exc:
            logger.debug("pencere ortalama hatası: %s", exc)

    def _show_settings_dialog(self):
        """Ayarlar penceresi: yazı tipi (Google Fonts) + yazı boyutu."""
        try:
            if getattr(self, "_settings_win", None) is not None \
                    and self._settings_win.winfo_exists():
                self._settings_win.lift()
                self._settings_win.focus_set()
                return
        except Exception:
            pass
        win = tk.Toplevel(self.root)
        self._settings_win = win
        win.title("Ayarlar")
        win.transient(self.root)
        win.configure(bg=theme.BG_PANEL)
        win.resizable(False, False)

        # Tek tip iç boşluk: pencere kenarından içerik her yönde eşit uzaklıkta
        PAD = 16
        body = tk.Frame(win, bg=theme.BG_PANEL, padx=PAD, pady=PAD)
        body.pack(fill=tk.BOTH, expand=True)

        # ---- Bölüm 1: yazı tipi -------------------------------------
        tk.Label(body, text="YAZI TİPİ", font=self.f_small,
                 bg=theme.BG_PANEL, fg=theme.ACCENT_NEON).pack(
                     anchor="w", pady=(0, 4))
        tk.Label(body, text="Google Fonts bağlantısı veya yazı tipi adı:",
                 font=self.f_small, bg=theme.BG_PANEL, fg=theme.FG_DIM).pack(
                     anchor="w", pady=(0, 2))
        tk.Label(body, text="örn. https://fonts.google.com/specimen/Caveat  veya  Caveat",
                 font=self.f_small, bg=theme.BG_PANEL, fg=theme.FG_MUTED).pack(
                     anchor="w", pady=(0, 10))

        var = tk.StringVar()
        entry = tk.Entry(body, textvariable=var, font=self.f_chat,
                         bg=theme.BG_INPUT, fg=theme.FG,
                         insertbackground=theme.FG, relief=tk.FLAT)
        entry.pack(fill=tk.X, pady=(0, 10), ipady=6)
        entry.focus_set()

        ex_row = tk.Frame(body, bg=theme.BG_PANEL)
        ex_row.pack(fill=tk.X, pady=(0, 10), anchor="w")
        tk.Label(ex_row, text="Örnekler:", font=self.f_small,
                 bg=theme.BG_PANEL, fg=theme.FG_DIM).pack(side=tk.LEFT)
        for ex in ("Caveat", "Roboto Mono", "Playfair Display"):
            tk.Button(ex_row, text=ex, font=self.f_small,
                      bg=theme.BG_HOVER, fg=theme.FG, relief=tk.FLAT,
                      activebackground=theme.ACCENT,
                      activeforeground=theme.ON_ACCENT,
                      cursor="hand2", padx=8, pady=3,
                      command=lambda e=ex: var.set(e)).pack(side=tk.LEFT, padx=(8, 0))

        status = tk.Label(body, text=" ", font=self.f_small,
                          bg=theme.BG_PANEL, fg=theme.WARN, wraplength=420,
                          justify=tk.LEFT)
        status.pack(fill=tk.X, pady=(0, 12), anchor="w")

        # ---- Bölüm 2: yazı boyutu ------------------------------------
        tk.Label(body, text="YAZI BOYUTU", font=self.f_small,
                 bg=theme.BG_PANEL, fg=theme.ACCENT_NEON).pack(
                     anchor="w", pady=(0, 4))
        size_row = tk.Frame(body, bg=theme.BG_PANEL)
        size_row.pack(fill=tk.X, pady=(0, 6))
        self._size_val_lbl = tk.Label(size_row, text=f"{self._font_size_base} pt",
                                      font=self.f_small, bg=theme.BG_PANEL,
                                      fg=theme.FG, width=7)
        self._size_val_lbl.pack(side=tk.RIGHT, padx=(8, 0))
        size_scale = tk.Scale(size_row, from_=9, to=18, orient=tk.HORIZONTAL,
                              showvalue=False, resolution=1,
                              bg=theme.BG_PANEL, fg=theme.FG,
                              troughcolor=theme.BG_INPUT,
                              activebackground=theme.ACCENT,
                              highlightthickness=0, relief=tk.FLAT,
                              command=self._on_settings_size)
        size_scale.set(self._font_size_base)
        size_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._size_scale = size_scale
        # Bırakınca kaydet (sürüklerken her tıkte disk yazılmaz → akıcı)
        size_scale.bind("<ButtonRelease-1>",
                        lambda _e: theme.save_font_size_preference(
                            getattr(self, "_font_size_base", 12)))
        self._size_sample = tk.Label(
            body, text="Önizleme: Merhaba dünya! 123 ğşıç",
            font=(theme.FONT_FAMILY, int(self._font_size_base)),
            bg=theme.BG_INPUT, fg=theme.FG, padx=10, pady=8,
            anchor="w", justify=tk.LEFT)
        self._size_sample.pack(fill=tk.X, pady=(0, 12))

        btn_row = tk.Frame(body, bg=theme.BG_PANEL)
        btn_row.pack(fill=tk.X)

        def _set_busy(busy: bool):
            state = tk.DISABLED if busy else tk.NORMAL
            for w in (btn_apply, btn_default, entry):
                try:
                    w.configure(state=state)
                except Exception:
                    pass

        def _apply():
            from . import fonts as _fonts
            raw = var.get()
            try:
                family = _fonts.parse_family(raw)
            except ValueError as exc:
                status.configure(text=str(exc), fg=theme.ERR)
                return
            _set_busy(True)
            status.configure(text=f"“{family}” indiriliyor...", fg=theme.WARN)

            def work():
                try:
                    path = _fonts.fetch_and_register(family)
                    try:
                        import tkinter.font as tkfont
                        fams = tkfont.families()
                        known = family in fams
                    except Exception:
                        known = True
                    note = "" if known else " (ad doğrulanamadı, yine de uygulandı)"
                    self.root.after(0, lambda: _done(family, path, note))
                except Exception as exc:
                    msg = str(exc) or "İndirme başarısız."
                    self.root.after(0, lambda: _fail(msg))

            def _done(family: str, _path: str, note: str):
                _set_busy(False)
                try:
                    self._refont_all(new_family=family)
                    try:
                        self._size_sample.configure(
                            font=(family, self._font_size_base))
                    except Exception:
                        pass
                    status.configure(
                        text=f"“{family}” uygulandı ✓{note}", fg=theme.OK)
                except Exception as exc:
                    logger.debug("font uygulama hatası: %s", exc)
                    status.configure(text="Uygulanamadı.", fg=theme.ERR)

            def _fail(msg: str):
                _set_busy(False)
                status.configure(text=msg, fg=theme.ERR)

            threading.Thread(target=work, daemon=True).start()

        def _reset_default():
            from . import fonts as _fonts
            _fonts.save_family(None)
            self._refont_all(new_family=_fonts.DEFAULT_FAMILY)
            self._tween_size_to(12)  # yumuşak dönüş + kaydırıcı senkronu
            status.configure(text="Varsayılanlara dönüldü (tip + boyut).", fg=theme.OK)

        btn_apply = tk.Button(btn_row, text="Yazı Tipini Uygula", font=self.f_small,
                              bg=theme.ACCENT, fg=theme.ON_ACCENT, relief=tk.FLAT,
                              activebackground=theme.ACCENT_HV, cursor="hand2",
                              padx=14, pady=4, command=_apply)
        btn_apply.pack(side=tk.RIGHT)
        btn_default = tk.Button(btn_row, text="Varsayılanlar", font=self.f_small,
                                bg=theme.BG_HOVER, fg=theme.FG, relief=tk.FLAT,
                                activebackground=theme.ACCENT,
                                activeforeground=theme.ON_ACCENT,
                                cursor="hand2", padx=14, pady=4,
                                command=_reset_default)
        btn_default.pack(side=tk.RIGHT, padx=(0, 8))
        entry.bind("<Return>", lambda _e: _apply())

        def _close_save():
            try:
                theme.save_font_size_preference(getattr(self, "_font_size_base", 12))
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", _close_save)
        win.bind("<Escape>", lambda _e: _close_save())
        self._center_over_parent(win)

    @staticmethod
    def _split_font_spec(spec):
        """Font tanımını (aile, punto, kalan) üçlüsüne ayır; bilinmeyende None."""
        if isinstance(spec, (tuple, list)):
            if not spec:
                return None
            fam = spec[0]
            if len(spec) > 1 and isinstance(spec[1], int):
                return fam, spec[1], list(spec[2:])
            return fam, None, list(spec[1:])
        if isinstance(spec, str):
            s = spec.strip()
            if not s:
                return None
            if s.startswith("{"):
                end = s.find("}")
                if end <= 0:
                    return None
                tail = s[end + 1:].split()
                size = int(tail[0]) if tail and tail[0].lstrip("-").isdigit() else None
                rest = tail[1:] if size is not None else tail
                return s[1:end], size, rest
            parts = s.split()
            if parts and parts[0].lstrip("-").isdigit():
                return None
            if len(parts) > 1 and parts[1].lstrip("-").isdigit():
                return parts[0], int(parts[1]), parts[2:]
            return s, None, []
        return None

    def _refont_all(self, new_family: str | None = None,
                    new_size_base: int | float | None = None,
                    save: bool = True) -> None:
        """Yazı tipi ve/veya boyutu tüm arayüze yay (save=False → diske yazmaz).

        Emoji (Segoe UI Emoji) ve kod (Consolas) fontlarına dokunulmaz;
        yalnızca yönetilen aileyle açılmış widget'lar güncellenir.
        Punto değişimi mevcut puntolar oranlanarak uygulanır.
        """
        old_family = theme.FONT_FAMILY
        old_base = float(getattr(self, "_font_size_base", 12))
        new_family = new_family or old_family
        new_base = float(new_size_base) if new_size_base is not None else old_base
        if new_family == old_family and new_base == old_base:
            return
        auto_old = self._font_scale_for(old_family)
        if new_family != old_family:
            theme.set_font_family(new_family)
        if save and new_base != old_base:
            theme.save_font_size_preference(new_base)
        self._font_size_base = new_base
        auto_new = self._font_scale_for(new_family)
        ratio = (auto_new * new_base) / max(1e-6, auto_old * old_base)
        self._fonts()
        targets = {old_family, new_family}

        def _swap(widget) -> None:
            try:
                parsed = self._split_font_spec(widget.cget("font"))
            except Exception:
                parsed = None
            if not parsed:
                return
            fam, size, rest = parsed
            if fam not in targets:
                return
            try:
                if size is None or ratio == 1.0:
                    widget.configure(font=(new_family,) + tuple(rest))
                else:
                    widget.configure(
                        font=(new_family, max(8, round(size * ratio))) + tuple(rest))
            except Exception:
                pass

        def _fix(widget) -> None:
            _swap(widget)
            try:
                children = widget.winfo_children()
            except Exception:
                children = ()
            for child in children:
                _fix(child)

        try:
            _fix(self.root)
        except Exception as exc:
            logger.debug("font yayma hatası: %s", exc)

        # Font değişimi ölçüleri değiştirir → akışı yeniden düzenle:
        # balon satır kaymaları, alt bar yüksekliği, üst bar kompaktlığı,
        # karşılama kartı sığması. Hatasız yeniden boyutlanmanın çekirdeği.
        try:
            self._reflow_chat()
        except Exception as exc:
            logger.debug("reflow hatası: %s", exc)
        try:
            self._responsive_welcome()
        except Exception as exc:
            logger.debug("welcome responsive hatası: %s", exc)

    def _apply_font_family(self, new_family: str) -> None:
        """Geriye uyumlu sarmalayıcı: yalnızca aileyi değiştirir."""
        self._refont_all(new_family=new_family)

    # --------------------------------- duyarlı düzen (responsive) + yeniden akış
    def _request_reflow(self, _event=None) -> None:
        """Pencere yeniden boyutlanınca akışı kısa gecikmeyle tek seferde tazele.

        Üst üste binen istekler birleştirilir (önceki zamanlayıcı iptal).
        Zamanlayıcı `after` ile kurulur; yok-oluşta Tk bekleyen betiği
        kendisi iptal eder, gürültü kalmaz.
        """
        try:
            old = getattr(self, "_reflow_after", None)
            if old is not None:
                try:
                    self.root.after_cancel(old)
                except Exception:
                    pass
            self._reflow_after = self.root.after(40, self._do_reflow_deferred)
        except Exception:
            pass

    def _do_reflow_deferred(self) -> None:
        self._reflow_after = None
        try:
            if getattr(self, "chat", None) is None \
                    or not self.chat.winfo_exists():
                return
            self._reflow_chat(light=True)
        except Exception:
            pass
        try:
            self._responsive_topbar()
        except Exception:
            pass

    def _reflow_chat(self, light: bool = False) -> None:
        """Sohbet akışını güncel ölçülere göre yeniden düzenle.

        - Balon `wraplength` değerleri güncellenir (font/pencere değişiminde
          taşma veya gereksiz daralma olmaz).
        - Alt bar yüksekliği giriş kutusuna göre ayarlanır (içerik kesilmez;
          varsayılanda 72px spec korunur).
        - Kaydırma konumu korunur (sondaysa sonda kalır).
        """
        if not (getattr(self, "chat", None) is not None
                and self.chat.winfo_exists()):
            return
        self.root.update_idletasks()
        area_w = self.chat_text.winfo_width()
        if area_w < 120:
            area_w = self.root.winfo_width() - 60
        max_wrap = max(120, int(area_w * 0.70)) - 24
        try:
            y0, _y1 = self.chat_text.yview()
        except Exception:
            y0 = 0.0
        # Sonda-sabit bayrağı kesirli tahminden güvenilirdir: gömülü balonlar
        # ilk görüntüde ölçü değiştirip see(END) sonrası kesri kaydırır.
        pinned = bool(getattr(self, "_chat_pinned", True))
        if not light:
            try:
                self.chat_text.configure(state=tk.NORMAL)
            except tk.TclError:
                pass
        for reg in list(getattr(self, "_msg_registry", {}).values()):
            try:
                bubble = reg.get("bubble")
                meta = reg.get("meta")
                if bubble is None or not bubble.winfo_exists():
                    continue
                for child in bubble.winfo_children():
                    if child is meta or child.winfo_class() != "Label":
                        continue
                    try:
                        child.configure(wraplength=max_wrap)
                    except tk.TclError:
                        pass
            except Exception:
                continue
        if not light:
            try:
                self.chat_text.configure(state=tk.DISABLED)
            except tk.TclError:
                pass
        # Alt bar: giriş kutusunu kesmeyecek yükseklik (varsayılan 72 korunur)
        try:
            need = self.msg_entry.winfo_reqheight() + 24
            self.chat_bottom.configure(height=max(72, need))
        except (tk.TclError, AttributeError):
            pass
        try:
            if pinned:
                self.chat_text.see(tk.END)
            else:
                self.chat_text.yview_moveto(y0)
        except tk.TclError:
            pass

    def _responsive_topbar(self, force: bool = False) -> None:
        """Dar pencerede üst barı sadeleştir (taşma/örtüşme olmaz).

        Genişlik 820px altına düşünce üye sayacı gizlenir, çıkış butonu
        simgeye iner, kayıt onay kutusu metinsiz kalır; genişleyince geri gelir.
        """
        if not (getattr(self, "chat_top", None) is not None
                and self.chat_top.winfo_exists()):
            return
        try:
            wide = self.chat.winfo_width() >= 820
        except tk.TclError:
            return
        compact = not wide
        if not force and compact == getattr(self, "_top_compact", False):
            return
        self._top_compact = compact
        try:
            if compact:
                self.members_lbl.pack_forget()
                self.btn_leave.configure(text="🚪")
                self.save_cb.configure(text="")
            else:
                if not self.members_lbl.winfo_ismapped():
                    self.members_lbl.pack(side=tk.LEFT, padx=10)
                self.btn_leave.configure(text="🚪 Odadan Ayrıl")
                self.save_cb.configure(text="Geçmişi Kaydet")
        except tk.TclError:
            pass
        try:
            self.root.update_idletasks()
        except Exception:
            pass

    def _responsive_welcome(self) -> None:
        """Karşılama kartını pencereye sığdır (taşma/kırpma olmaz).

        Dar veya basık pencerede kart dolguları ve giriş genişliği kısalır;
        mod değişimi yalnızca eşik atlanınca uygulanır (döngü yapmaz).
        """
        if not (getattr(self, "welcome", None) is not None
                and self.welcome.winfo_exists()):
            return
        try:
            w, h = self.welcome.winfo_width(), self.welcome.winfo_height()
        except tk.TclError:
            return
        if w < 50 or h < 50:
            return
        compact = (w < 780 or h < 560)
        if not compact:
            # Pencere yeterli görünse de içerik taşıyorsa kıs (büyük puntolar)
            try:
                outer = getattr(self, "_welcome_outer", None)
                if outer is not None and outer.winfo_exists():
                    self.root.update_idletasks()
                    if outer.winfo_reqheight() > h - 24:
                        compact = True
            except tk.TclError:
                pass
        if compact == getattr(self, "_welcome_compact", "unset"):
            return  # mod değişmedi → dokunma (Configure döngüsü olmaz)
        self._welcome_compact = compact
        try:
            box = getattr(self, "_welcome_box", None)
            if box is not None and box.winfo_exists():
                box.configure(padx=20 if compact else 36,
                              pady=16 if compact else 28)
            if getattr(self, "nick_entry", None) is not None \
                    and self.nick_entry.winfo_exists():
                self.nick_entry.configure(width=24 if compact else 30)
        except tk.TclError:
            pass

    @staticmethod
    def _round_half(value) -> float | None:
        try:
            return round(min(18.0, max(9.0, float(value))) * 2) / 2
        except (TypeError, ValueError):
            return None

    def _on_settings_size(self, value) -> None:
        """Kaydırıcıdan elle boyut: varsa tween'i iptal et, uygula.

        Tek tıklık değişim anında yansır; banda tıklama gibi büyük
        sıçramalar yumuşak geçişle gider. Sürüklerken diske yazılmaz.
        """
        self._size_tween_token = getattr(self, "_size_tween_token", 0) + 1
        size = self._round_half(value)
        if size is None:
            return
        size = int(size)
        try:
            cur = float(getattr(self, "_font_size_base", 12))
        except (TypeError, ValueError):
            cur = 12.0
        if abs(size - cur) >= 3:
            self._tween_size_to(size)
            return
        self._apply_size_value(size)

    def _apply_size_value(self, size, save: bool = False) -> None:
        """Puntoyu önizleme + uygulamaya yansıt (save=True → diske yaz)."""
        try:
            size = int(size)
        except (TypeError, ValueError):
            return
        try:
            if getattr(self, "_size_val_lbl", None) is not None \
                    and self._size_val_lbl.winfo_exists():
                self._size_val_lbl.configure(text=f"{size} pt")
            if getattr(self, "_size_sample", None) is not None \
                    and self._size_sample.winfo_exists():
                self._size_sample.configure(font=(theme.FONT_FAMILY, size))
        except Exception:
            pass
        self._refont_all(new_size_base=size, save=save)

    def _tween_size_to(self, target, delay_ms: int = 35) -> None:
        """Puntoyu tam-sayı merdivenle yumuşakça hedefe taşı (~200ms).

        Tk Dove tam sayı punto ister; her basamak ayrı karede uygulanır.
        Elle müdahale tween'i iptal eder, son karede kayıt + kaydırıcı
        senkronlanır.
        """
        target = self._round_half(target)
        if target is None:
            return
        target = int(target)
        try:
            start = int(float(getattr(self, "_font_size_base", 12)))
        except (TypeError, ValueError):
            start = 12
        if start == target:
            try:
                theme.save_font_size_preference(target)
            except Exception:
                pass
            return
        token = getattr(self, "_size_tween_token", 0) + 1
        self._size_tween_token = token
        # Hedef merdivene dahil DEĞİL: son kare hedefi save=True ile uygular.
        # (Hedef basamakta olsaydı erken-dönüş kaydı atlardı.)
        step = 1 if target > start else -1
        waypoints = list(range(start + step, target, step))

        def _sync_slider() -> None:
            try:
                sc = getattr(self, "_size_scale", None)
                if sc is not None and sc.winfo_exists():
                    sc.set(target)  # baz zaten hedefte → komut erken döner
            except Exception:
                pass

        def _step(idx: int) -> None:
            if getattr(self, "_size_tween_token", 0) != token:
                return  # elle müdahale, eskisi durur
            if idx >= len(waypoints):
                self._apply_size_value(target, save=True)
                _sync_slider()
                return
            self._apply_size_value(waypoints[idx])
            try:
                self.root.after(delay_ms, lambda: _step(idx + 1))
            except Exception:
                pass

        _step(0)

    def _apply_chat_theme(self):
        """Sohbet ekranındaki tüm widget'ların ve baloncukların renklerini yeni temaya uyarla."""
        if not (self.chat and self.chat.winfo_exists()):
            return

        # Üst Panel
        self.chat_top.configure(bg=theme.BG_PANEL)
        self.status_lbl.configure(bg=theme.BG_PANEL, fg=theme.FG)
        self.status_dot.configure(bg=theme.BG_PANEL, fg=theme.OK)
        self.code_box.configure(bg=theme.BG_CARD, highlightbackground=theme.BORDER)
        self.code_lbl_prefix.configure(bg=theme.BG_CARD, fg=theme.FG_DIM)
        self.code_lbl.configure(bg=theme.BG_CARD, fg=theme.ACCENT_NEON)
        self.btn_copy.configure(bg=theme.BG_HOVER, fg=theme.FG, activebackground=theme.ACCENT)
        self.members_lbl.configure(bg=theme.BG_PANEL, fg=theme.FG_DIM)

        theme_txt = "☀️ Açık" if theme.is_dark() else "🌙 Koyu"
        self.btn_theme_chat.configure(
            text=theme_txt, bg=theme.BG_HOVER, fg=theme.FG, activebackground=theme.BG_HOVER
        )
        if getattr(self, "btn_settings_chat", None) is not None \
                and self.btn_settings_chat.winfo_exists():
            self.btn_settings_chat.configure(
                bg=theme.BG_HOVER, fg=theme.FG, activebackground=theme.BG_HOVER
            )
        self.save_cb.configure(
            bg=theme.BG_PANEL, fg=theme.FG_DIM, selectcolor=theme.BG_INPUT,
            activebackground=theme.BG_PANEL, activeforeground=theme.FG
        )
        self.btn_leave.configure(bg=theme.BG_HOVER, fg=theme.ERR, activebackground=theme.ERR)

        # Mesaj Alanı
        self.chat_mid.configure(bg=theme.BG)
        self.chat_text.configure(
            bg=theme.BG, fg=theme.FG, insertbackground=theme.FG,
            selectbackground=theme.ACCENT, selectforeground=theme.ON_ACCENT
        )
        self._update_chat_tag_colors()

        # Alt Giriş Paneli
        self.chat_bottom.configure(bg=theme.BG_PANEL, highlightbackground=theme.BORDER)
        self.msg_entry_frame.configure(bg=theme.SURFACE_ALT)
        self.msg_entry.configure(
            bg=theme.BG_INPUT, fg=theme.FG, insertbackground=theme.FG,
            selectbackground=theme.ACCENT, selectforeground=theme.ON_ACCENT
        )
        self.btn_send.configure(
            bg=theme.SECONDARY, fg=theme.ON_SECONDARY,
            activebackground=theme.PRIMARY, activeforeground=theme.ON_ACCENT
        )
        for _b in (getattr(self, "btn_photo", None), getattr(self, "btn_emoji", None)):
            if _b is not None and _b.winfo_exists():
                _b.configure(bg=theme.BG_PANEL, fg=theme.FG_DIM,
                             activebackground=theme.BG_HOVER,
                             activeforeground=theme.ACCENT_NEON)
        # Satır-içi düzenleme çubuğu
        if getattr(self, "_edit_bar", None) is not None and self._edit_bar.winfo_exists():
            self._edit_bar.configure(bg=theme.BG_PANEL,
                                     highlightbackground=theme.BORDER)
            self._edit_lbl.configure(bg=theme.BG_PANEL, fg=theme.ACCENT_NEON)
            self._edit_cancel.configure(bg=theme.BG_PANEL, fg=theme.FG_DIM,
                                        activebackground=theme.BG_HOVER)

    # ---------------------------------------------------------------- input odak parıltısı
    def _entry_focus_in(self, _e=None):
        """Odakta kenarlık #00F5D4 neon parıltısına döner
        (box-shadow: 0 0 10px rgba(0,245,212,.3) hissi)."""
        self._entry_glow = True
        self._entry_glow_step(0)

    def _entry_glow_step(self, i: int) -> None:
        if not getattr(self, "_entry_glow", False):
            return
        if not (self.chat and self.chat.winfo_exists()
                and self.msg_entry_frame.winfo_exists()):
            return
        t = (math.sin(i / 6.0) + 1) / 2
        self.msg_entry_frame.configure(
            bg=_lerp(theme.BG, theme.PRIMARY, 0.45 + 0.35 * t))
        self.root.after(90, lambda: self._entry_glow_step(i + 1))

    def _entry_focus_out(self, _e=None):
        self._entry_glow = False
        if self.msg_entry_frame.winfo_exists():
            self.msg_entry_frame.configure(bg=theme.SURFACE_ALT)

    def _style_icon_button(self, btn: tk.Button, tip: str = "") -> None:
        """İkon butonuna temiz hover + tema uyumu kazandır.

        Zemin çubukla bütünleşir (BG_PANEL), simge soluk başlar,
        üzerine gelince neon vurguya döner. Açık/koyu temada da
        kontrast korunur çünkü renkler tema token'larından gelir.
        """
        def _enter(_e=None):
            try:
                btn.configure(fg=theme.ACCENT_NEON, bg=theme.BG_HOVER)
            except tk.TclError:
                pass
        def _leave(_e=None):
            try:
                btn.configure(fg=theme.FG_DIM, bg=theme.BG_PANEL)
            except tk.TclError:
                pass
        btn.bind("<Enter>", _enter, add="+")
        btn.bind("<Leave>", _leave, add="+")

    def _update_chat_tag_colors(self):
        """Mevcut ve yeni mesaj baloncuklarının renk/kontrast ayarlarını uygular."""
        if not (hasattr(self, "chat_text") and self.chat_text.winfo_exists()):
            return
        self.chat_text.tag_configure(
            "sys_bubble", background=theme.BUBBLE_SYS, foreground=theme.BUBBLE_SYS_FG, font=self.f_small
        )
        self.chat_text.tag_configure("me_bubble", background=theme.BUBBLE_ME)
        self.chat_text.tag_configure("oth_bubble", background=theme.BUBBLE_OTH)

        meta_me_fg = theme.META_ON_SECONDARY
        self.chat_text.tag_configure("me_meta", foreground=meta_me_fg, font=self.f_small)
        self.chat_text.tag_configure("oth_meta", foreground=theme.FG_MUTED, font=self.f_small)
        self.chat_text.tag_configure("me_body", foreground=theme.BUBBLE_ME_FG, font=self.f_chat)
        self.chat_text.tag_configure("oth_body", foreground=theme.BUBBLE_OTH_FG, font=self.f_chat)

    # ---------------------------------------------------------------- sohbet eylemleri

    def _send(self):
        if self.room is None:
            return
        # Satır-içi düzenleme kipi: Gönder → kaydet, boş gönderim → sil
        if getattr(self, "_editing_msg_id", None):
            self._commit_inline_edit()
            return
        text = self.msg_var.get().strip()
        if not text:
            return

        res = self.room.send_chat(text)
        if res:
            self.msg_var.set("")
            mid = res if isinstance(res, str) else None
            self._append_message(self.room.nickname, text, False, mine=True,
                                 msg_id=mid)
        else:
            self._set_status("Mesaj gönderilemedi (Rate limit veya bağlantı yok)!", theme.WARN)

    # ------------------------------------------------------- fotoğraf gönderimi
    def _pick_and_send_image(self):
        """Dosya seç → media.prepare_image → room.send_image → balonu ekle."""
        if self.room is None:
            return
        if getattr(self, "_editing_msg_id", None):
            # Düzenleme kipinde giriş kutusu taslak tutar; karışmaması için
            # kipi kapatıp (balon aynen durur) fotoğraf akışına devam et.
            self._cancel_inline_edit()
        path = filedialog.askopenfilename(
            title="Fotoğraf seç",
            filetypes=[("Resimler", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
                       ("Tümü", "*.*")])
        if not path:
            return
        caption = self.msg_var.get().strip()[:config.IMAGE_CAPTION_MAX]
        try:
            prepared = media.prepare_image(path, caption=caption)
        except ValueError as exc:
            self._set_status(str(exc), theme.ERR)
            return
        except Exception as exc:
            logger.debug("fotoğraf hazırlama hatası: %s", exc)
            self._set_status("Fotoğraf işlenemedi.", theme.ERR)
            return
        sent = self.room.send_image(prepared["b64"], prepared["caption"],
                                    prepared["w"], prepared["h"])
        if sent:
            if caption:
                self.msg_var.set("")
            mid = sent if isinstance(sent, str) else None
            self._append_image_message(self.room.nickname, prepared["b64"],
                                       prepared["caption"], mine=True, msg_id=mid)
        else:
            self._set_status("Fotoğraf gönderilemedi (Rate limit veya bağlantı yok)!", theme.WARN)

    def _append_image_message(self, sender: str, image_b64: str, caption: str = "",
                              mine: bool = False, msg_id: Optional[str] = None):
        """Fotoğrafı sohbet akışında baloncuk içinde göster."""
        if not (self.chat and self.chat.winfo_exists()):
            return
        # Bozuk veride metin balonuna düş (akışı bozma)
        try:
            photo, pw, ph = media.to_photoimage(image_b64)
        except Exception as exc:
            logger.debug("fotoğraf decode hatası: %s", exc)
            self._append_message(sender, "[fotoğraf alınamadı]" +
                                (f" {caption}" if caption else ""), False,
                                mine=mine, msg_id=msg_id)
            return
        if not hasattr(self, "_photo_refs"):
            self._photo_refs = []
        self._photo_refs.append(photo)  # GC koruması
        if len(self._photo_refs) > 40:  # bellek tavanı
            del self._photo_refs[:len(self._photo_refs) - 40]

        import uuid as _uuid
        mid = msg_id or _uuid.uuid4().hex[:12]

        self.chat_text.configure(state=tk.NORMAL)
        self._msg_i += 1
        stamp = self._now()
        area_w = self.chat_text.winfo_width()
        if area_w < 120:
            area_w = self.root.winfo_width() - 60
        max_bubble_w = max(120, int(area_w * 0.70))

        who = "sen" if mine else sender
        bubble_bg = theme.BUBBLE_ME if mine else theme.BUBBLE_OTH
        meta_fg = theme.META_ON_SECONDARY if mine else theme.FG_MUTED
        cap_fg = theme.BUBBLE_ME_FG if mine else theme.BUBBLE_OTH_FG

        row = tk.Frame(self.chat_text, bg=theme.BG)
        bubble = tk.Frame(row, bg=bubble_bg, padx=12, pady=8)
        meta_lbl = tk.Label(bubble, text=f"{who}  ·  {stamp}  📷",
                            font=self.f_small, bg=bubble_bg, fg=meta_fg)
        meta_lbl.pack(anchor=tk.W)
        img_lbl = tk.Label(bubble, image=photo, bg=bubble_bg,
                           wraplength=max_bubble_w - 24, justify=tk.LEFT)
        img_lbl.pack(anchor=tk.W, pady=(4, 2))
        cap_lbl = None
        if caption:
            cap_lbl = tk.Label(bubble, text=caption, font=self.f_chat,
                               bg=bubble_bg, fg=cap_fg,
                               wraplength=max_bubble_w - 24, justify=tk.LEFT)
            cap_lbl.pack(anchor=tk.W)

        if mine:
            tk.Frame(row, bg=theme.BG).pack(side=tk.LEFT, fill=tk.X, expand=True)
            bubble.pack(side=tk.LEFT, padx=(0, 18), pady=3)
        else:
            bubble.pack(side=tk.LEFT, padx=(18, 0), pady=3)
            tk.Frame(row, bg=theme.BG).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.chat_text.insert(tk.END, "\n")
        self.chat_text.window_create(
            self.chat_text.index(tk.END) + "-1c",
            window=row, align=tk.BOTTOM, stretch=True)
        self.chat_text.insert(tk.END, "\n")
        self._finalize_bubble()
        if mid not in getattr(self, "_msg_registry", {}):
            self._msg_registry[mid] = {
                "sender": sender, "kind": "image", "mine": mine,
                "caption": caption or "", "row": row, "bubble": bubble,
                "body": cap_lbl or img_lbl, "meta": meta_lbl,
                "stamp": stamp, "deleted": False, "edited": False,
            }
        for _w in (bubble, img_lbl, meta_lbl) + ((cap_lbl,) if cap_lbl else ()):
            self._bind_bubble_popup(_w, mid)
        self.store.append(f"{sender}: [fotoğraf] {caption}")
        self._refresh_members()

    # ------------------------------------------------------- emoji seçici
    def _show_emoji_picker(self):
        """Mesaj girişinin yanında emoji paneli aç."""
        try:
            emoji_picker.show_emoji_picker(self.msg_entry, on_pick=self._insert_emoji)
        except Exception as exc:
            logger.debug("emoji paneli açılamadı: %s", exc)

    def _insert_emoji(self, emo: str):
        """Seçilen emojiyi imleç konumuna ekle."""
        try:
            pos = self.msg_entry.index(tk.INSERT)
        except Exception:
            pos = len(self.msg_var.get())
        cur = self.msg_var.get()
        # Tk Entry indeksi karakter bazlıdır; emoji tek küme sayılır
        new = cur[:pos] + emo + cur[pos:]
        self.msg_var.set(new)
        try:
            self.msg_entry.icursor(pos + len(emo))
            self.msg_entry.focus_set()
        except Exception:
            pass

    def _copy_code(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.room_code)
        self.btn_copy.configure(text="✓ Kopyalandı")
        self.root.after(1800, lambda: self.btn_copy.configure(text="📋 Kopyala"))
        self._set_status("Oda kodu panoya kopyalandı ✓", theme.OK)

    def _leave_chat(self):
        """Mevcut odadan güvenle ayrıl ve karşılama ekranına dön (State reset)."""
        self._close_bubble_menu()
        try:
            self._cancel_inline_edit()
        except Exception:
            pass
        if self.room is not None:
            try:
                leave = getattr(self.room, "leave", None)
                if callable(leave):
                    leave()
                else:
                    self.room.stop()
            except Exception as exc:
                logger.debug("Ayrılma hatası: %s", exc)
            self.room = None
            self.room_code = ""
            self._msg_registry = {}

        self.store.wipe()
        self._show_welcome()

    def _toggle_recording(self):
        if self.save_var.get():
            path = filedialog.asksaveasfilename(
                title="Sohbeti kaydet",
                defaultextension=".log",
                initialfile="sohbet.log",
                filetypes=[("Log dosyası", "*.log *.txt"), ("Tümü", "*.*")])
            if not path:
                self.save_var.set(False)
                return
            self.store.set_recording(path)
            self._append_system(f"💾 Kayıt açık: {path}")
        else:
            self.store.set_recording(None)
            self._append_system("💾 Kayıt kapatıldı — mesajlar yalnızca RAM'de tutulur.")

    def _set_status(self, text: str, color: str):
        if self.chat and self.chat.winfo_exists():
            self.status_lbl.configure(text=text, fg=color)
            self.status_dot.configure(fg=color)

    def _append_message(self, sender: str, text: str, system: bool,
                        mine: bool = False, msg_id: Optional[str] = None):
        """Mesajı WhatsApp stili fit-content baloncuk olarak ekler.

        Her mesaj için chat_text içine window_create() ile bir tk.Frame
        gömülür. Frame genişliği metnin uzunluğuna göre daralır (fit-content);
        maksimum genişlik chat alanının ~%%70'i ile sınırlanır (max-width: 70%%).
        Gelen mesajlar sola, giden mesajlar sağa hizalanır.

        Balona sağ tık (Button-3) → Kopyala / (kendisiyse) Düzenle / Sil
        menüsü açılır. ``msg_id`` verilmezse üretilir ve kayıt defterinde
        tutulur (düzenleme/silme hedefi).
        """
        if not (self.chat and self.chat.winfo_exists()):
            return

        self.chat_text.configure(state=tk.NORMAL)
        self._msg_i += 1
        stamp = self._now()

        # Chat alanı genişliğini al; henüz render edilmemişse tahmini kullan
        area_w = self.chat_text.winfo_width()
        if area_w < 120:
            area_w = self.root.winfo_width() - 60
        max_bubble_w = max(120, int(area_w * 0.70))  # max-width: %70

        # ── Sistem mesajı: ortalanmış pill ──────────────────────────────────
        if system:
            pill = tk.Frame(self.chat_text, bg=theme.BUBBLE_SYS, padx=10, pady=4)
            tk.Label(
                pill,
                text=f"⟨ {stamp}  ·  {text} ⟩",
                font=self.f_small,
                bg=theme.BUBBLE_SYS, fg=theme.BUBBLE_SYS_FG,
                wraplength=max_bubble_w,
                justify=tk.CENTER,
            ).pack()
            self.chat_text.insert(tk.END, "\n")
            self.chat_text.window_create(
                self.chat_text.index(tk.END) + "-1c",
                window=pill, align=tk.CENTER, padx=0, pady=3,
            )
            self.chat_text.insert(tk.END, "\n")

        # ── Normal mesaj: fit-content balon ─────────────────────────────────
        else:
            import uuid as _uuid
            mid = msg_id or _uuid.uuid4().hex[:12]
            who = "sen" if mine else sender
            bubble_bg = theme.BUBBLE_ME if mine else theme.BUBBLE_OTH
            bubble_fg = theme.BUBBLE_ME_FG if mine else theme.BUBBLE_OTH_FG
            meta_fg   = theme.META_ON_SECONDARY if mine else theme.FG_MUTED

            # Satır kapsayıcısı: tam genişlik (hizalama için)
            row = tk.Frame(self.chat_text, bg=theme.BG)

            # Balon: yalnızca içeriği kadar genişler
            bubble = tk.Frame(row, bg=bubble_bg, padx=12, pady=8)
            meta_lbl = tk.Label(
                bubble,
                text=f"{who}  ·  {stamp}",
                font=self.f_small,
                bg=bubble_bg, fg=meta_fg,
            )
            meta_lbl.pack(anchor=tk.W)
            body_lbl = tk.Label(
                bubble,
                text=text,
                font=self.f_chat,
                bg=bubble_bg, fg=bubble_fg,
                wraplength=max_bubble_w - 24,  # padx(12*2) düşürüldü
                justify=tk.LEFT,
            )
            body_lbl.pack(anchor=tk.W)

            # Hizalama: giden → sağ, gelen → sol
            if mine:
                tk.Frame(row, bg=theme.BG).pack(side=tk.LEFT, fill=tk.X, expand=True)
                bubble.pack(side=tk.LEFT, padx=(0, 18), pady=3)
            else:
                bubble.pack(side=tk.LEFT, padx=(18, 0), pady=3)
                tk.Frame(row, bg=theme.BG).pack(side=tk.LEFT, fill=tk.X, expand=True)

            self.chat_text.insert(tk.END, "\n")
            self.chat_text.window_create(
                self.chat_text.index(tk.END) + "-1c",
                window=row, align=tk.BOTTOM, stretch=True,
            )
            self.chat_text.insert(tk.END, "\n")
            if mid not in getattr(self, "_msg_registry", {}):
                self._msg_registry[mid] = {
                    "sender": sender, "kind": "text", "mine": mine,
                    "text": text, "row": row, "bubble": bubble,
                    "body": body_lbl, "meta": meta_lbl,
                    "stamp": stamp, "deleted": False, "edited": False,
                }
            for _w in (bubble, body_lbl, meta_lbl):
                self._bind_bubble_popup(_w, mid)

        self._finalize_bubble()

        label = "sistem" if system else sender
        self.store.append(f"{label}: {text}")
        self._refresh_members()

    def _finalize_bubble(self) -> None:
        """Balon sonrası ortak işlemler: spacer, bellek tavanı, kaydır."""
        try:
            last_line = self.chat_text.index("end-1c linestart")
            self.chat_text.tag_add("spacer", last_line, "end")
            total_lines = int(self.chat_text.index("end-1c").split(".")[0])
            if total_lines > config.MAX_UI_TEXT_LINES:
                self.chat_text.delete("1.0", f"{config.MAX_UI_TEXT_LINES // 2}.0")
        except tk.TclError:
            pass
        try:
            self.chat_text.configure(state=tk.DISABLED)
            self.chat_text.see(tk.END)
            self._chat_pinned = True
        except tk.TclError:
            pass

    def _append_system(self, text: str):
        self._append_message("sistem", text, True)

    # --------------------------------------- balon sağ-tık menüsü (kopyala/düzenle/sil)
    def _bind_bubble_popup(self, widget: tk.Widget, msg_id: str) -> None:
        """Balon ve iç etiketlere sağ-tık menüsü bağla (win: Button-3, mac: Button-2/Ctrl)."""
        widget.bind("<Button-3>", lambda e: self._show_bubble_menu(e, msg_id))
        widget.bind("<Button-2>", lambda e: self._show_bubble_menu(e, msg_id))
        widget.bind("<Control-Button-1>", lambda e: self._show_bubble_menu(e, msg_id))

    def _show_bubble_menu(self, event, msg_id: str) -> None:
        """Kayıtlı mesaja tema uyumlu açılır menü göster."""
        reg = getattr(self, "_msg_registry", {}).get(msg_id)
        if not reg or reg.get("deleted"):
            return
        self._close_bubble_menu()
        try:
            menu = tk.Menu(self.root, tearoff=0, bg=theme.BG_PANEL, fg=theme.FG,
                           activebackground=theme.ACCENT,
                           activeforeground=theme.ON_ACCENT,
                           relief=tk.FLAT, bd=1)
        except Exception:
            menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="📋 Kopyala", command=lambda: self._copy_msg(msg_id))
        if reg.get("mine") and not reg.get("deleted"):
            if reg.get("kind") == "text":
                menu.add_command(label="✎ Düzenle",
                                 command=lambda: self._start_inline_edit(msg_id))
            menu.add_command(label="🗑 Sil",
                             command=lambda: self._delete_msg_confirm(msg_id))
        self._bubble_menu = menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _close_bubble_menu(self) -> None:
        try:
            if self._bubble_menu is not None:
                self._bubble_menu.unpost()
        except Exception:
            pass
        self._bubble_menu = None

    def _copy_msg(self, msg_id: str) -> None:
        """Mesaj metnini (fotoğrafta açıklamayı) panoya kopyala."""
        self._close_bubble_menu()
        reg = getattr(self, "_msg_registry", {}).get(msg_id)
        if not reg:
            return
        text = reg.get("text", "") if reg.get("kind") == "text" else (
            reg.get("caption", "") or "[fotoğraf]")
        if not text:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._set_status("Mesaj panoya kopyalandı ✓", theme.OK)
        except Exception as exc:
            logger.debug("kopyalama hatası: %s", exc)
            self._set_status("Kopyalanamadı.", theme.ERR)

    def _start_inline_edit(self, msg_id: str) -> None:
        """Telegram tarzı düzenleme: metni yazma kutusuna taşı, çubuğu göster.

        Gönder/Enter → kaydet, kutu tamamen silinip gönderilirse → sil,
        ✕ veya Esc → vazgeç.
        """
        self._close_bubble_menu()
        reg = getattr(self, "_msg_registry", {}).get(msg_id)
        if not reg or not reg.get("mine") or reg.get("kind") != "text" \
                or reg.get("deleted"):
            return
        self._editing_msg_id = msg_id
        self.msg_var.set(reg.get("text", ""))
        preview = (reg.get("text", "")[:42] + "…") if len(reg.get("text", "")) > 42 \
            else reg.get("text", "")
        self._edit_lbl.configure(text=f"✎ Düzenleniyor: {preview}  ·  "
                                      "boş bırakıp gönderirsen silinir")
        if self._edit_bar.winfo_exists() and not self._edit_bar.winfo_ismapped():
            self._edit_bar.pack(side=tk.BOTTOM, fill=tk.X)
        try:
            self.btn_send.configure(text="Kaydet ✓")
        except tk.TclError:
            pass
        try:
            self.msg_entry.focus_set()
            self.msg_entry.icursor(tk.END)
        except Exception:
            pass

    def _commit_inline_edit(self) -> None:
        """Yazma kutusundaki hali kaydet (boşsa sil)."""
        mid = getattr(self, "_editing_msg_id", None)
        if not mid:
            return
        reg = getattr(self, "_msg_registry", {}).get(mid)
        if not reg or not reg.get("mine") or reg.get("deleted"):
            self._cancel_inline_edit()
            return
        new = self.msg_var.get()
        if not new.strip():
            # Kutu tamamen silindi → mesajı sil (onaysız, Telegram davranışı)
            sender = getattr(self.room, "send_delete", None)
            res = sender(mid) if callable(sender) else True
            if res is False:
                self._set_status("Silme gönderilemedi.", theme.WARN)
                return
            self._apply_delete(mid)
            self._set_status("Mesaj silindi.", theme.WARN)
            self._cancel_inline_edit()
            return
        if new == reg.get("text", ""):
            self._cancel_inline_edit()  # değişiklik yok
            return
        sender = getattr(self.room, "send_edit", None)
        ok = sender(mid, new.strip()) if callable(sender) else True
        if ok is False:
            self._set_status("Düzenleme gönderilemedi.", theme.WARN)
            return
        self._apply_edit(mid, new.strip())
        self._cancel_inline_edit()

    def _cancel_inline_edit(self, _e=None) -> None:
        """Düzenleme kipinden çık, çubuğu gizle, kutuyu temizle."""
        self._editing_msg_id = None
        try:
            if hasattr(self, "_edit_bar") and self._edit_bar.winfo_exists() \
                    and self._edit_bar.winfo_ismapped():
                self._edit_bar.pack_forget()
        except tk.TclError:
            pass
        try:
            if hasattr(self, "btn_send") and self.btn_send.winfo_exists():
                self.btn_send.configure(text="Gönder ➤")
        except tk.TclError:
            pass
        try:
            if hasattr(self, "msg_var"):
                self.msg_var.set("")
        except Exception:
            pass

    def _apply_edit(self, msg_id: str, new_text: str) -> None:
        """Balondaki metni güncelle + '(düzenlendi)' işareti koy."""
        reg = getattr(self, "_msg_registry", {}).get(msg_id)
        if not reg or reg.get("deleted") or reg.get("kind") != "text":
            return
        reg["text"] = new_text
        reg["edited"] = True
        try:
            reg["body"].configure(text=new_text)
            base_meta = reg.get("meta_base") or reg["meta"].cget("text")
            if "meta_base" not in reg:
                reg["meta_base"] = base_meta
            if "(düzenlendi)" not in reg["meta"].cget("text"):
                reg["meta"].configure(text=f"{reg['meta_base']}  ·  (düzenlendi)")
        except (tk.TclError, KeyError) as exc:
            logger.debug("edit uygulama hatası: %s", exc)

    def _delete_msg_confirm(self, msg_id: str) -> None:
        """Silme onayı al, ağa yayınla ve yerelde uygula."""
        self._close_bubble_menu()
        reg = getattr(self, "_msg_registry", {}).get(msg_id)
        if not reg or not reg.get("mine") or reg.get("deleted"):
            return
        try:
            ok = messagebox.askyesno("Mesajı sil",
                                     "Bu mesaj silinsin mi? Karşı taraf da "
                                     "“mesaj silindi” olarak görecek.")
        except Exception:
            ok = True
        if not ok:
            return
        sender = getattr(self.room, "send_delete", None)
        res = sender(msg_id) if callable(sender) else True
        if res is False:
            self._set_status("Silme gönderilemedi.", theme.WARN)
            return
        self._apply_delete(msg_id)

    def _apply_delete(self, msg_id: str) -> None:
        """Balonu 'mesaj silindi' yer tutucusuna çevir."""
        reg = getattr(self, "_msg_registry", {}).get(msg_id)
        if not reg or reg.get("deleted"):
            return
        reg["deleted"] = True
        try:
            bubble_bg = reg["bubble"].cget("bg")
            reg["body"].configure(text="— Bu mesaj silindi —",
                                  font=self.f_small,
                                  fg=theme.FG_MUTED)
            # Fotoğrafta görseli gizle, yalnızca yer tutucu kalsın
            for child in reg["bubble"].winfo_children():
                if child is not reg["body"] and child is not reg["meta"] \
                        and child.winfo_class() == "Label":
                    try:
                        child.pack_forget()
                    except Exception:
                        pass
            reg["bubble"].configure(bg=bubble_bg)
        except (tk.TclError, KeyError) as exc:
            logger.debug("delete uygulama hatası: %s", exc)

    def _on_remote_edit(self, sender: str, msg_id: str, new_text: str) -> None:
        """Karşı tarafın düzenlemesini uygula (sahiplik kontrollü)."""
        reg = getattr(self, "_msg_registry", {}).get(msg_id)
        if not reg or reg.get("deleted"):
            return
        if reg.get("sender") != sender:  # başkasının mesajını düzenleyemez
            logger.warning("Yetkisiz düzenleme denemesi: %s -> %s", sender, msg_id)
            return
        if reg.get("kind") != "text":
            return
        self._apply_edit(msg_id, messages.sanitize_text(new_text))

    def _on_remote_delete(self, sender: str, msg_id: str) -> None:
        """Karşı tarafın silmesini uygula (sahiplik kontrollü)."""
        reg = getattr(self, "_msg_registry", {}).get(msg_id)
        if not reg or reg.get("deleted"):
            return
        if reg.get("sender") != sender:
            logger.warning("Yetkisiz silme denemesi: %s -> %s", sender, msg_id)
            return
        self._apply_delete(msg_id)

    @staticmethod
    def _now() -> str:
        import time
        return time.strftime("%H:%M")

    def _refresh_members(self):
        if not (self.chat and self.chat.winfo_exists()) or self.room is None:
            return
        try:
            n = len(getattr(self.room, "members", {}) or {})
            host_extra = 1 if isinstance(self.room, Host) else 0
            total = n + host_extra
            self.members_lbl.configure(text=f"👥 {total} katılımcı")
        except Exception:
            pass

    def _on_close(self):
        try:
            if self.room is not None:
                leave = getattr(self.room, "leave", None)
                if callable(leave):
                    leave()
                else:
                    self.room.stop()
        except Exception as exc:
            logger.debug("Çıkışta oda durdurma hatası: %s", exc)
        try:
            self.store.wipe()
        except Exception as exc:
            logger.debug("RAM temizleme hatası: %s", exc)
        self.root.destroy()


def run():
    """Uygulamayı başlat (main.py burayı çağırır)."""
    root = tk.Tk()
    # Kayıtlı özel yazı tipi varsa açılışta tanıt (ağ gerekmez, önbellekten)
    try:
        from . import fonts as _fonts
        fam = _fonts.load_saved_family()
        if fam and _fonts.ensure_registered(fam):
            theme.FONT_FAMILY = fam
    except Exception:
        pass
    ChatApp(root)
    root.mainloop()
