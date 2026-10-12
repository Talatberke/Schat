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
        # ---- Honeypot durumu (gizli girdi tuzağı + oturum kilidi) ----
        self._honeypot_tripped = False
        self._hp_var = tk.StringVar()
        self._hp_var.trace_add("write", self._on_hp_write)
        self._show_welcome()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- fontlar

    def _fonts(self):
        import tkinter.font as tkfont
        base = tkfont.nametofont("TkDefaultFont")
        base.configure(family=theme.FONT_FAMILY, size=theme.FONT_SIZE)
        self.f_title = (theme.FONT_FAMILY, 22, "bold")
        self.f_sub = (theme.FONT_FAMILY, 10)
        self.f_normal = (theme.FONT_FAMILY, theme.FONT_SIZE)
        self.f_chat = (theme.FONT_FAMILY, theme.FONT_CHAT)
        self.f_code = (theme.FONT_CODE, 15, "bold")
        self.f_small = (theme.FONT_FAMILY, 9)

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
        top_bar = tk.Frame(self.welcome, bg=theme.BG, padx=20, pady=16)
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

        # Kart Çerçevesi (Border & Card effect)
        outer_box = tk.Frame(self.welcome, bg=theme.BORDER, padx=1, pady=1)
        outer_box.place(relx=0.5, rely=0.5, anchor="center")

        box = tk.Frame(outer_box, bg=theme.BG_PANEL, padx=36, pady=32)
        box.pack(fill=tk.BOTH, expand=True)

        tk.Label(box, text="🔐 SecretChat", font=self.f_title,
                 bg=theme.BG_PANEL, fg=theme.FG).pack(pady=(0, 4))
        tk.Label(box, text="Uçtan Uca Şifreli • Sıfır İz • E2EE Güvenli Sohbet",
                 font=self.f_sub, bg=theme.BG_PANEL,
                 fg=theme.ACCENT_NEON).pack(pady=(0, 22))

        # ---- Takma Ad Alanı
        tk.Label(box, text="Kullanıcı Adı (Benzersiz)", font=self.f_normal, bg=theme.BG_PANEL,
                 fg=theme.FG_DIM).pack(anchor="w")

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
            box, text="2-24 karakter (harf, rakam, alt çizgi)",
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
            self.nick_feedback.configure(text="2-24 karakter (harf, rakam, alt çizgi)", fg=theme.FG_MUTED)
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
        valid, nick = messages.validate_nickname(raw_nick)
        if not valid:
            self._welcome_status(nick, theme.ERR)
            return
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
        valid, nick = messages.validate_nickname(raw_nick)
        if not valid:
            self._welcome_status(nick, theme.ERR)
            return

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
        self.room.on_message = lambda s, t, sys_: self.root.after(
            0, lambda: self._append_message(s, t, sys_))
        self.room.on_sas = lambda s: self.root.after(
            0, lambda: self._append_system(f"🔐 Doğrulama kodu {s} — "
                                           "karşı taraf ile karşılaştırın."))
        if isinstance(self.room, Host):
            self.room.on_peer_left = lambda n: self.root.after(
                0, lambda: self._refresh_members())

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
        scroll = ttk.Scrollbar(self.chat_mid, command=self.chat_text.yview)
        self.chat_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.chat_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

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
        self._refresh_members()

        # Odaya girince mesaj kutusuna odaklan
        self.msg_entry.focus_set()

        # Honeypot: sohbet ekranına da ekran dışı gizli tuzak girdisi
        self._install_honeypot_input(self.chat)

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
        text = self.msg_var.get().strip()
        if not text or self.room is None:
            return

        sent = self.room.send_chat(text)
        if sent:
            self.msg_var.set("")
            self._append_message(self.room.nickname, text, False, mine=True)
        else:
            self._set_status("Mesaj gönderilemedi (Rate limit veya bağlantı yok)!", theme.WARN)

    def _copy_code(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.room_code)
        self.btn_copy.configure(text="✓ Kopyalandı")
        self.root.after(1800, lambda: self.btn_copy.configure(text="📋 Kopyala"))
        self._set_status("Oda kodu panoya kopyalandı ✓", theme.OK)

    def _leave_chat(self):
        """Mevcut odadan güvenle ayrıl ve karşılama ekranına dön (State reset)."""
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
                        mine: bool = False):
        """Mesajı WhatsApp stili fit-content baloncuk olarak ekler.

        Her mesaj için chat_text içine window_create() ile bir tk.Frame
        gömülür. Frame genişliği metnin uzunluğuna göre daralır (fit-content);
        maksimum genişlik chat alanının ~%%70'i ile sınırlanır (max-width: 70%%).
        Gelen mesajlar sola, giden mesajlar sağa hizalanır.
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
            who = "sen" if mine else sender
            bubble_bg = theme.BUBBLE_ME if mine else theme.BUBBLE_OTH
            bubble_fg = theme.BUBBLE_ME_FG if mine else theme.BUBBLE_OTH_FG
            meta_fg   = theme.META_ON_SECONDARY if mine else theme.FG_MUTED

            # Satır kapsayıcısı: tam genişlik (hizalama için)
            row = tk.Frame(self.chat_text, bg=theme.BG)

            # Balon: yalnızca içeriği kadar genişler
            bubble = tk.Frame(row, bg=bubble_bg, padx=12, pady=8)
            tk.Label(
                bubble,
                text=f"{who}  ·  {stamp}",
                font=self.f_small,
                bg=bubble_bg, fg=meta_fg,
            ).pack(anchor=tk.W)
            tk.Label(
                bubble,
                text=text,
                font=self.f_chat,
                bg=bubble_bg, fg=bubble_fg,
                wraplength=max_bubble_w - 24,  # padx(12*2) düşürüldü
                justify=tk.LEFT,
            ).pack(anchor=tk.W)

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

        # padding-bottom: son satıra spacer tag uygula
        last_line = self.chat_text.index("end-1c linestart")
        self.chat_text.tag_add("spacer", last_line, "end")

        # Bellek tavanı: gömülü balon widget'ları sınırsız büyümesin (DoS)
        total_lines = int(self.chat_text.index("end-1c").split(".")[0])
        if total_lines > config.MAX_UI_TEXT_LINES:
            self.chat_text.delete("1.0", f"{config.MAX_UI_TEXT_LINES // 2}.0")

        self.chat_text.configure(state=tk.DISABLED)
        self.chat_text.see(tk.END)

        label = "sistem" if system else sender
        self.store.append(f"{label}: {text}")
        self._refresh_members()

    def _append_system(self, text: str):
        self._append_message("sistem", text, True)

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
    ChatApp(root)
    root.mainloop()
