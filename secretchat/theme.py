"""Cyber-Incognito / Cyberpunk Minimalism tema sistemi.

Konsept
-------
Odaklanmayı artıran, gizlilik hissi veren; neon dokunuşlarla zenginleştirilmiş
ama gözü yormayan karanlık mod (Dark Mode Default).

Bu modül üç şeyi birden tanımlar:

1. **Semantik renk token'ları** (`PALETTE`)  -> istediğiniz çerçeveye (Streamlit /
   CustomTkinter / Flet / PyQt / Tk) birebir taşınabilir saf değer sözlüğü.
2. **CSS / Stil Sözlüğü** (`CSS`)            -> `:root` değişkenleri + bileşen
   sınıfları. `css_variables()` / `css_style_sheet()` ile doğrudan yazdırılabilir.
3. **Çalışan tema motoru**                   -> Tkinter arayüzünün kullandığı
   `DARK_PALETTE` / `LIGHT_PALETTE` + `set_theme()` / `toggle_theme()` / `is_dark()`
   geri-uyumlu API'si (eski testler ve ui.py bu adlara dokunmadan çalışır).

Ayrıca tipografi (mono + sans), duyarlı (responsive) boşluk ölçekleri, köşe
yarıçapı, neon parıltı ve mikro-etkileşim süreleri burada merkezîleşir.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".secretchat")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")

APP_NAME = "SecretChat"
APP_VERSION = "3.0.0"
THEME_NAME = "Cyber-Incognito"

# ==========================================================================
# 1. RENK TOKEN'LARI  (Color Palette & Tokens)
# ==========================================================================
# Kullanıcının istediği birebir palet. Bu sözlük çerçeveden bağımsızdır;
# Tk, Qt, CSS, Streamlit... hepsine birebir taşınabilir.

PALETTE: Dict[str, str] = {
    # -- Zemin & Yüzey -----------------------------------------------------
    "background":       "#0B0E14",  # Derin, hafif maviye çalan siyah (zemin)
    "surface":          "#151B26",  # Sohbet pencereleri, kartlar (Surface/Card)
    "surface_alt":      "#1E293B",  # Gelen mesaj balonu / iç içe kutular
    "surface_input":    "#10161F",  # Girdi kutusu (zeminden hafif ayrışır)

    # -- Vurgu -------------------------------------------------------------
    "primary":          "#00F5D4",  # Neon Turkuaz — şifreli vurgu, aktif buton
    "primary_hover":    "#00D9BD",  # Biraz koyu turkuaz (hover/pressed)
    "primary_ink":      "#04211E",  # Primary üzerinde okunur mürekkep (kontrast)

    "secondary":        "#7B2CBF",  # Derin Mor — kendi mesajların, gizli rozet
    "secondary_deep":   "#2E1065",  # Mor gradient başlangıcı (giden balon)

    # -- Metin -------------------------------------------------------------
    "text":             "#F1F5F9",  # Yüksek kontrastlı off-white (ana metin)
    "text_muted":       "#64748B",  # Zaman damgaları, ikincil bilgiler
    "text_dim":         "#475569",  # Pasif/placeholder (metinden bir kademe koyu)
    "on_primary":       "#0B0E14",  # Neon primary üzerinde metin (kontrast!)
    "on_secondary":     "#F5F3FF",  # Mor üzerinde metin
    "meta_on_secondary": "#EDE9FE",  # Mor balon üzerinde meta/saat (5.99:1)

    # -- Durum -------------------------------------------------------------
    "success":          "#10B981",  # Çevrimiçi / şifreleme aktif
    "warning":          "#F59E0B",  # Bağlanıyor / uyarı
    "error":            "#EF4444",  # Bağlantı koptu / mesaj silindi
    "info":             "#38BDF8",  # Bilgi / sistem notu

    # -- Kenarlık & odak ---------------------------------------------------
    "border":           "#1F2A3A",  # Kart/panel kenarlığı
    "border_strong":    "#2B3A4F",  # Vurgulu kenarlık
    "focus":            "#00F5D4",  # Odak halkası (neon)
    "glow_rgba":        "rgba(0, 245, 212, 0.30)",  # box-shadow parıltı rengi
}

# Semantik isim -> eski Tk anahtar eşlemesi (geri uyumluluk için)
_ALIAS = {
    "BG": "background", "BG_PANEL": "surface", "BG_CARD": "surface",
    "BG_INPUT": "surface_input", "BG_HOVER": "surface_alt",
    "BORDER": "border", "BORDER_GLOW": "focus",
    "FG": "text", "FG_DIM": "text_muted", "FG_MUTED": "text_dim",
    "ACCENT": "primary", "ACCENT_HV": "primary_hover", "ACCENT_NEON": "primary",
    "ON_ACCENT": "on_primary", "ON_SECONDARY": "on_secondary",
    "META_ON_SECONDARY": "meta_on_secondary",
    "OK": "success", "WARN": "warning", "ERR": "error", "INFO": "info",
    "BUBBLE_ME": "secondary", "BUBBLE_ME_FG": "on_secondary",
    "BUBBLE_OTH": "surface_alt", "BUBBLE_OTH_FG": "text",
    "BUBBLE_SYS": "surface", "BUBBLE_SYS_FG": "text_muted",
}


def _palette_with_aliases(base: Dict[str, str], name: str) -> Dict[str, str]:
    """Semantik token'ları alıp eski Tk anahtarlarını da ekler."""
    out: Dict[str, str] = {"NAME": name}
    out.update(base)
    for legacy, semantic in _ALIAS.items():
        out[legacy] = base.get(semantic, base.get("background", "#000000"))
    return out


# ==========================================================================
# 2. AÇIK MOD PALETİ  (aynı mimari, gündüz karşılığı)
# ==========================================================================
LIGHT_TOKENS: Dict[str, str] = {
    "background":       "#F8FAFC",
    "surface":          "#FFFFFF",
    "surface_alt":      "#EEF2F7",
    "surface_input":    "#F1F5F9",
    "primary":          "#0E7490",  # cyan-700: beyaz metinle 5.4:1 (AA), zeminde de AA
    "primary_hover":    "#155E75",
    "primary_ink":      "#FFFFFF",
    "secondary":        "#7C3AED",
    "secondary_deep":   "#5B21B6",
    "text":             "#0F172A",
    "text_muted":       "#64748B",
    "text_dim":         "#94A3B8",
    "on_primary":       "#FFFFFF",
    "on_secondary":     "#FFFFFF",
    "meta_on_secondary": "#EDE9FE",
    "success":          "#059669",
    "warning":          "#D97706",
    "error":            "#DC2626",
    "info":             "#0284C7",
    "border":           "#E2E8F0",
    "border_strong":    "#CBD5E1",
    "focus":            "#0E7490",
    "glow_rgba":        "rgba(14, 116, 144, 0.30)",
}

DARK_PALETTE: Dict[str, str] = _palette_with_aliases(PALETTE, "dark")
LIGHT_PALETTE: Dict[str, str] = _palette_with_aliases(LIGHT_TOKENS, "light")

# Aktif semantik token sözlüğü (set_theme ile değişir)
ACTIVE_TOKENS: Dict[str, str] = dict(PALETTE)

# ==========================================================================
# 3. TİPOGRAFİ  (Typography & Hiyerarşi)
# ==========================================================================
# Monospace: kod / hash / anahtar göstergeleri, durum metinleri
FONT_MONO_STACK: List[str] = ["Fira Code", "JetBrains Mono", "Consolas",
                              "Menlo", "DejaVu Sans Mono", "Courier New"]
# Sans-Serif: mesaj baloncukları, menüler, genel okuma
FONT_SANS_STACK: List[str] = ["Inter", "Roboto", "Segoe UI", "system-ui",
                              "Helvetica Neue", "Arial"]

FONT_FAMILY = "Segoe UI"   # ui.py geri uyumluluğu (aktif sans)
FONT_CODE = "Consolas"     # mono aile (kod/oda kodu)
FONT_SIZE = 11             # gövde metni (pt)
FONT_CHAT = 12             # mesaj balonu metni (pt)

# Nokta cinsinden tip skalası — ferah satır aralığı için satır yüksekliği ~1.5
TYPE_SCALE: Dict[str, Tuple[int, str, float]] = {
    # anahtar: (boyut_pt, ağırlık, satır yüksekliği katsayısı)
    "caption":  (10, "normal", 1.4),
    "body":     (11, "normal", 1.5),
    "body_big": (12, "normal", 1.5),
    "label":    (11, "bold",   1.3),
    "title":    (14, "bold",   1.25),
    "heading":  (18, "bold",   1.2),
    "display":  (26, "bold",   1.15),
    "code":     (16, "bold",   1.0),   # oda kodu / anahtar
}

# ==========================================================================
# 4. DUYARLI BOŞLUKLAR  (Responsive Spacing / Padding)
# ==========================================================================
# Breakpoint genişlikleri (px) — masaüstü ve mobil için ölçekler.
BREAKPOINTS: Dict[str, int] = {"mobile": 576, "tablet": 768, "desktop": 1024}

# Her kırılım için: genel boşluk (unit), kart dolgusu, baloncuk dolgusu,
# eleman arası boşluk, yatay kenar boşluğu.
SPACING: Dict[str, Dict[str, int]] = {
    #             unit  card_pad  bubble_pad  gap  gutter  bar_h
    "mobile":  {"unit": 4,  "card_pad": 16, "bubble_pad": 10, "gap": 6,  "gutter": 12, "bar_h": 52},
    "tablet":  {"unit": 6,  "card_pad": 24, "bubble_pad": 12, "gap": 10, "gutter": 20, "bar_h": 56},
    "desktop": {"unit": 8,  "card_pad": 32, "bubble_pad": 14, "gap": 12, "gutter": 28, "bar_h": 60},
}

_DEFAULT_SPACING = SPACING["desktop"]


def spacing_for(width_px: int) -> Dict[str, int]:
    """Pencere/genişliğe göre uygun boşluk ölçeğini döndürür.

    Mobil (<=576) -> tablet (<=768) -> masaüstü (>768).
    """
    if width_px <= BREAKPOINTS["mobile"]:
        return SPACING["mobile"]
    if width_px <= BREAKPOINTS["tablet"]:
        return SPACING["tablet"]
    return SPACING["desktop"]


def breakpoint_of(width_px: int) -> str:
    """Genişliğin adını döndürür: 'mobile' | 'tablet' | 'desktop'."""
    if width_px <= BREAKPOINTS["mobile"]:
        return "mobile"
    if width_px <= BREAKPOINTS["tablet"]:
        return "tablet"
    return "desktop"


# ==========================================================================
# 5. KÖŞE YARICAPI, PARILTI & MİKRO ETKİLEŞİM  (Effects)
# ==========================================================================
RADIUS: Dict[str, int] = {
    "sm": 4, "md": 8, "lg": 12, "xl": 16, "pill": 999,
    "bubble_tail": 2,  # asimetrik "kuyruk" köşesi
}

# Baloncuk köşe yarıçapı (CSS sıralaması: sol-üst, sağ-üst, sağ-alt, sol-alt)
BUBBLE_RADIUS: Dict[str, str] = {
    "incoming": "12px 12px 12px 2px",    # sol hizalı, sol-alt köşe sivri
    "outgoing": "12px 12px 2px 12px",    # sağ hizalı, sağ-alt köşe sivri
    "system":   "8px",
}

GLOW: Dict[str, str] = {
    # Giriş alanı odak parıltısı
    "focus_input": "0 0 10px rgba(0, 245, 212, 0.30)",
    "focus_ring":  "0 0 0 2px rgba(0, 245, 212, 0.55)",
    # Yumuşak neon yayılımı (aktif buton)
    "accent_soft": "0 0 16px rgba(0, 245, 212, 0.18)",
    "secondary_soft": "0 0 16px rgba(123, 44, 191, 0.28)",
}

# Mikro-etkileşim süreleri (ms) — yumuşak geçişler
MOTION: Dict[str, int] = {
    "fast": 150,      # hover / renk değişimi
    "normal": 250,    # durum geçişi
    "slow": 400,      # kaybolan mesaj / yazıyor animasyonu
    "stagger": 40,    # liste öğeleri arası gecikme
}

# Kaybolan mesaj / yazıyor göstergesi için CSS geçişi (web/prototip için)
TRANSITION_CSS = "all 250ms cubic-bezier(0.4, 0, 0.2, 1)"

# ==========================================================================
# 6. CSS / STİL SÖZLÜĞÜ  (Theme Dict)
# ==========================================================================
# Tkinter dışındaki herhangi bir çerçeveye birebir taşınabilir sözlük.
# css_variables() -> ":root { ... }", css_style_sheet() -> tam CSS.

CSS: Dict[str, Any] = {
    ":root": {
        # renk token'ları
        "--bg": PALETTE["background"],
        "--surface": PALETTE["surface"],
        "--surface-alt": PALETTE["surface_alt"],
        "--surface-input": PALETTE["surface_input"],
        "--primary": PALETTE["primary"],
        "--primary-hover": PALETTE["primary_hover"],
        "--primary-ink": PALETTE["primary_ink"],
        "--secondary": PALETTE["secondary"],
        "--secondary-deep": PALETTE["secondary_deep"],
        "--text": PALETTE["text"],
        "--text-muted": PALETTE["text_muted"],
        "--text-dim": PALETTE["text_dim"],
        "--on-primary": PALETTE["on_primary"],
        "--on-secondary": PALETTE["on_secondary"],
        "--success": PALETTE["success"],
        "--warning": PALETTE["warning"],
        "--error": PALETTE["error"],
        "--info": PALETTE["info"],
        "--border": PALETTE["border"],
        "--border-strong": PALETTE["border_strong"],
        "--focus": PALETTE["focus"],
        "--glow": PALETTE["glow_rgba"],
        # tipografi
        "--font-sans": "Inter, Roboto, 'Segoe UI', system-ui, sans-serif",
        "--font-mono": "'Fira Code', 'JetBrains Mono', Consolas, 'Courier New', monospace",
        "--fs-caption": "10px", "--fs-body": "13px", "--fs-title": "16px",
        "--fs-heading": "20px", "--fs-code": "18px",
        "--lh-body": "1.5", "--lh-tight": "1.2",
        # boşluk (desktop varsayılan; mobilde SPACING["mobile"] ile değişir)
        "--unit": "8px", "--gutter": "28px", "--card-pad": "32px",
        "--bubble-pad": "14px", "--gap": "12px", "--bar-h": "60px",
        # köşe & efekt
        "--radius-sm": "4px", "--radius-md": "8px", "--radius-lg": "12px",
        "--radius-xl": "16px",
        "--radius-in": "12px 12px 12px 2px",
        "--radius-out": "12px 12px 2px 12px",
        "--glow-focus": GLOW["focus_input"],
        "--transition": TRANSITION_CSS,
    },

    # -- bileşen sınıfları ------------------------------------------------
    "body": {
        "background": "var(--bg)", "color": "var(--text)",
        "font-family": "var(--font-sans)", "line-height": "var(--lh-body)",
        "-webkit-font-smoothing": "antialiased",
    },

    ".bubble": {
        "padding": "var(--bubble-pad) calc(var(--bubble-pad) + 4px)",
        "line-height": "var(--lh-body)",
        "max-width": "min(75%, 46ch)",
        "transition": "var(--transition)",
        "border": "1px solid var(--border)",
    },
    ".bubble-in": {           # Gelen mesaj: sol hizada, yumuşak köşe
        "background": "var(--surface-alt)", "color": "var(--text)",
        "border-radius": "var(--radius-in)",
        "align-self": "flex-start",
        "margin-right": "auto",
    },
    ".bubble-out": {          # Giden mesaj: sağ hizada, mor gradient
        "background": "linear-gradient(135deg, var(--secondary-deep), var(--secondary))",
        "color": "var(--on-secondary)",
        "border-radius": "var(--radius-out)",
        "align-self": "flex-end",
        "margin-left": "auto",
        "border-color": "transparent",
        "box-shadow": GLOW["secondary_soft"],
    },
    ".bubble-system": {
        "background": "var(--surface)", "color": "var(--text-muted)",
        "border-radius": "var(--radius-md)", "align-self": "center",
        "font-family": "var(--font-mono)", "font-size": "var(--fs-caption)",
    },

    ".input": {               # Giriş alanı: kenarlık #1E293B, odakta neon parıltı
        "background": "var(--surface-input)",
        "color": "var(--text)",
        "border": "1px solid var(--surface-alt)",
        "border-radius": "var(--radius-lg)",
        "padding": "12px 16px",
        "font-family": "var(--font-sans)",
        "transition": "border-color 200ms ease, box-shadow 200ms ease",
    },
    ".input:focus": {
        "outline": "none",
        "border-color": "var(--primary)",
        "box-shadow": GLOW["focus_input"],
    },
    ".input::placeholder": {"color": "var(--text-dim)"},

    ".btn": {
        "border": "none", "border-radius": "var(--radius-md)",
        "padding": "10px 18px", "font-family": "var(--font-sans)",
        "font-weight": "600", "cursor": "pointer",
        "transition": "background var(--fast,150ms) ease, transform 120ms ease, box-shadow 200ms ease",
    },
    ".btn-primary": {
        "background": "var(--primary)", "color": "var(--on-primary)",
        "box-shadow": "var(--glow-focus)",
    },
    ".btn-primary:hover": {"background": "var(--primary-hover)", "transform": "translateY(-1px)"},
    ".btn-primary:active": {"transform": "translateY(0)"},
    ".btn-ghost": {
        "background": "transparent", "color": "var(--text-muted)",
        "border": "1px solid var(--border)",
    },    ".btn-ghost:hover": {
        "background": "var(--surface-alt)",
        "color": "var(--primary)",
        "border-color": "var(--primary)",
    },

    # -- layout:2 bölme mimarisi (mesaj alanı + sabit alt yazma çubuğu) -----
    ".chat-body": {           # tek scroll yapan alan (scroll isolation)
        "overflow-y": "auto",
        "padding-bottom": "80px",  # son mesaj alt barın altında kalmasın
        "display": "flex",
        "flex-direction": "column",
        "gap": "6px",
    },
    ".input-bar": {           # yapışkan alt bar: sabit yükseklik, üst katman
        "position": "sticky",
        "bottom": "0",
        "z-index": "100",
        "height": "72px",         # spec: 60-80px
        "box-sizing": "border-box",
        "background": "var(--surface)",
        "border-top": "1px solid var(--border)",
        "display": "flex",
        "align-items": "center",
        "gap": "var(--gap)",
        "padding": "0 var(--gutter)",
    },
    ".btn-send": {            # Gönder: #7B2CBF → hover #00F5D4 (spec)
        "background": "var(--secondary)",
        "color": "var(--on-secondary)",
    },
    ".btn-send:hover": {
        "background": "var(--primary)",
        "color": "var(--on-primary)",
    },


    ".status-bar": {
        "background": "var(--surface)", "border-bottom": "1px solid var(--border)",
        "height": "var(--bar-h)", "padding": "0 var(--gutter)",
        "display": "flex", "align-items": "center", "gap": "var(--gap)",
        "font-family": "var(--font-mono)", "font-size": "var(--fs-caption)",
        "letter-spacing": "0.04em",
    },
    ".status-online": {"color": "var(--success)"},
    ".status-encrypted": {"color": "var(--success)"},
    ".meta": {                # zaman damgası / gönderen
        "color": "var(--text-muted)", "font-size": "var(--fs-caption)",
        "font-family": "var(--font-mono)",
    },
    ".typing": {              # "yazıyor..." yumuşak geçiş
        "color": "var(--primary)", "opacity": "0.7",
        "transition": "opacity 400ms ease",
        "font-family": "var(--font-mono)", "font-size": "var(--fs-caption)",
    },
}


# CSS değişkeni -> semantik token eşlemesi (aktif modu izlemek için)
_CSS_TOKEN_MAP: List[Tuple[str, str]] = [
    ("--bg", "background"), ("--surface", "surface"),
    ("--surface-alt", "surface_alt"), ("--surface-input", "surface_input"),
    ("--primary", "primary"), ("--primary-hover", "primary_hover"),
    ("--primary-ink", "primary_ink"), ("--secondary", "secondary"),
    ("--secondary-deep", "secondary_deep"), ("--text", "text"),
    ("--text-muted", "text_muted"), ("--text-dim", "text_dim"),
    ("--on-primary", "on_primary"), ("--on-secondary", "on_secondary"),
    ("--success", "success"), ("--warning", "warning"),
    ("--error", "error"), ("--info", "info"),
    ("--border", "border"), ("--border-strong", "border_strong"),
    ("--focus", "focus"), ("--glow", "glow_rgba"),
]


def css_variables() -> str:
    """:root CSS değişken bloğunu döndürür (AKTİF MODA göre; web/prototip).

    `set_theme()` sonrası çağrıldığında açık/koyu karşılığını üretir;
    `CSS[":root"]` de senkron kalır (QSS'e çevirenler için).
    """
    for css_key, tok in _CSS_TOKEN_MAP:
        val = ACTIVE_TOKENS.get(tok)
        if val:
            CSS[":root"][css_key] = val
    lines = [f"  {k}: {v};" for k, v in CSS[":root"].items()]
    return ":root {\n" + "\n".join(lines) + "\n}"


def css_style_sheet() -> str:
    """Tam CSS stil sayfasını döndürür (tema kılavuzu eki)."""
    parts: List[str] = ["/* Cyber-Incognito tema — SecretChat */",
                        css_variables(), ""]
    for sel, decl in CSS.items():
        if sel == ":root":
            continue
        body = "".join(f"  {p.replace('_', '-')}: {v};" for p, v in decl.items())
        parts.append(f"{sel} {{\n{body}\n}}")
        parts.append("")
    return "\n".join(parts)


def spacing_css() -> str:
    """Mobil / tablet / masaüstü için duyarlı @media CSS bloğu."""
    rules = [
        "/* Duyarlı spacing: mobil -> tablet -> masaüstü */",
    ]
    # mobil (varsayılan en küçük)
    m = SPACING["mobile"]
    rules.append(
        ":root {\n"
        f"  --unit: {m['unit']}px; --gutter: {m['gutter']}px;\n"
        f"  --card-pad: {m['card_pad']}px; --bubble-pad: {m['bubble_pad']}px;\n"
        f"  --gap: {m['gap']}px; --bar-h: {m['bar_h']}px;\n"
        "}"
    )
    for bp in ("tablet", "desktop"):
        s = SPACING[bp]
        min_w = BREAKPOINTS[bp]
        rules.append(
            f"@media (min-width: {min_w}px) {{\n"
            "  :root {\n"
            f"    --unit: {s['unit']}px; --gutter: {s['gutter']}px;\n"
            f"    --card-pad: {s['card_pad']}px; --bubble-pad: {s['bubble_pad']}px;\n"
            f"    --gap: {s['gap']}px; --bar-h: {s['bar_h']}px;\n"
            "  }\n"
            "}"
        )
    return "\n\n".join(rules)


# ==========================================================================
# 7. TEMA YÖNETİMİ & KALICILIK  (Persistence)
# ==========================================================================
def load_saved_theme() -> str:
    """Kaydedilmiş tema tercihini oku (varsayılan: dark / Cyber-Incognito)."""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                mode = data.get("theme", "dark")
                if mode in ("dark", "light"):
                    return mode
    except Exception:
        pass
    return "dark"


def save_theme_preference(mode: str) -> None:
    """Tema tercihini diske kaydet."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"theme": mode}, f, indent=2)
    except Exception:
        pass


# ==========================================================================
# 8. DİNAMİK TEMA GEÇİŞİ  (Theme Toggle)
# ==========================================================================
CURRENT_MODE = "dark"

# -- Modül düzeyindeki erişilebilir değişkenler (ui.py bunları kullanır) ----
BG = DARK_PALETTE["BG"]
BG_PANEL = DARK_PALETTE["BG_PANEL"]
BG_CARD = DARK_PALETTE["BG_CARD"]
BG_INPUT = DARK_PALETTE["BG_INPUT"]
BG_HOVER = DARK_PALETTE["BG_HOVER"]
BORDER = DARK_PALETTE["BORDER"]
BORDER_GLOW = DARK_PALETTE["BORDER_GLOW"]
FG = DARK_PALETTE["FG"]
FG_DIM = DARK_PALETTE["FG_DIM"]
FG_MUTED = DARK_PALETTE["FG_MUTED"]
ACCENT = DARK_PALETTE["ACCENT"]
ACCENT_HV = DARK_PALETTE["ACCENT_HV"]
ACCENT_NEON = DARK_PALETTE["ACCENT_NEON"]
ON_ACCENT = DARK_PALETTE["ON_ACCENT"]
ON_SECONDARY = DARK_PALETTE["ON_SECONDARY"]
META_ON_SECONDARY = DARK_PALETTE["META_ON_SECONDARY"]
OK = DARK_PALETTE["OK"]
WARN = DARK_PALETTE["WARN"]
ERR = DARK_PALETTE["ERR"]
INFO = DARK_PALETTE["INFO"]
BUBBLE_ME = DARK_PALETTE["BUBBLE_ME"]
BUBBLE_ME_FG = DARK_PALETTE["BUBBLE_ME_FG"]
BUBBLE_OTH = DARK_PALETTE["BUBBLE_OTH"]
BUBBLE_OTH_FG = DARK_PALETTE["BUBBLE_OTH_FG"]
BUBBLE_SYS = DARK_PALETTE["BUBBLE_SYS"]
BUBBLE_SYS_FG = DARK_PALETTE["BUBBLE_SYS_FG"]

# Yeni semantik adlar da her zaman mevcut
PRIMARY = ACCENT
SECONDARY = BUBBLE_ME
SURFACE = BG_PANEL
SURFACE_ALT = BG_HOVER
TEXT = FG
MUTED = FG_DIM
SUCCESS = OK
ERROR = ERR


def set_theme(mode: str) -> str:
    """Temayı 'dark' (Cyber-Incognito) veya 'light' yapar; global'leri günceller."""
    global CURRENT_MODE, BG, BG_PANEL, BG_CARD, BG_INPUT, BG_HOVER
    global BORDER, BORDER_GLOW, FG, FG_DIM, FG_MUTED
    global ACCENT, ACCENT_HV, ACCENT_NEON, ON_ACCENT, ON_SECONDARY
    global META_ON_SECONDARY
    global OK, WARN, ERR, INFO
    global BUBBLE_ME, BUBBLE_ME_FG, BUBBLE_OTH, BUBBLE_OTH_FG
    global BUBBLE_SYS, BUBBLE_SYS_FG
    global PRIMARY, SECONDARY, SURFACE, SURFACE_ALT, TEXT, MUTED, SUCCESS, ERROR
    global ACTIVE_TOKENS, FONT_FAMILY, FONT_CODE

    palette = LIGHT_PALETTE if mode == "light" else DARK_PALETTE
    tokens = LIGHT_TOKENS if mode == "light" else PALETTE
    CURRENT_MODE = palette["NAME"]
    ACTIVE_TOKENS = dict(tokens)

    BG = palette["BG"]
    BG_PANEL = palette["BG_PANEL"]
    BG_CARD = palette["BG_CARD"]
    BG_INPUT = palette["BG_INPUT"]
    BG_HOVER = palette["BG_HOVER"]
    BORDER = palette["BORDER"]
    BORDER_GLOW = palette["BORDER_GLOW"]
    FG = palette["FG"]
    FG_DIM = palette["FG_DIM"]
    FG_MUTED = palette["FG_MUTED"]
    ACCENT = palette["ACCENT"]
    ACCENT_HV = palette["ACCENT_HV"]
    ACCENT_NEON = palette["ACCENT_NEON"]
    ON_ACCENT = palette["ON_ACCENT"]
    ON_SECONDARY = palette["ON_SECONDARY"]
    META_ON_SECONDARY = palette["META_ON_SECONDARY"]
    OK = palette["OK"]
    WARN = palette["WARN"]
    ERR = palette["ERR"]
    INFO = palette["INFO"]
    BUBBLE_ME = palette["BUBBLE_ME"]
    BUBBLE_ME_FG = palette["BUBBLE_ME_FG"]
    BUBBLE_OTH = palette["BUBBLE_OTH"]
    BUBBLE_OTH_FG = palette["BUBBLE_OTH_FG"]
    BUBBLE_SYS = palette["BUBBLE_SYS"]
    BUBBLE_SYS_FG = palette["BUBBLE_SYS_FG"]

    PRIMARY = ACCENT
    SECONDARY = BUBBLE_ME
    SURFACE = BG_PANEL
    SURFACE_ALT = BG_HOVER
    TEXT = FG
    MUTED = FG_DIM
    SUCCESS = OK
    ERROR = ERR

    save_theme_preference(CURRENT_MODE)
    return CURRENT_MODE


def toggle_theme() -> str:
    """Mevcut temayı Açık <-> Koyu arasında değiştirir."""
    new_mode = "light" if CURRENT_MODE == "dark" else "dark"
    return set_theme(new_mode)


def is_dark() -> bool:
    """Koyu (Cyber-Incognito) modun aktif olup olmadığını döndürür."""
    return CURRENT_MODE == "dark"


def token(key: str, default: str = "") -> str:
    """Semantik anahtarla aktif renk al (ör. token('primary'))."""
    return ACTIVE_TOKENS.get(key, default)


# --------------------------------------------------------------- font çözümle
def resolve_fonts(available: List[str]) -> Tuple[str, str]:
    """Verilen kurulu font listesinden (sans, mono) ailelerini seçer.

    `available` tkinter.font.families() çıktısı olabilir. Hiçbiri kurulu değilse
    yığının sonuna (sistem) düşer.
    """
    global FONT_FAMILY, FONT_CODE
    lower = {a.lower() for a in available}

    def pick(stack: List[str], fallback: str) -> str:
        for name in stack:
            if name.lower() in lower:
                return name
        return fallback

    FONT_FAMILY = pick(FONT_SANS_STACK, FONT_FAMILY)
    FONT_CODE = pick(FONT_MONO_STACK, FONT_CODE)
    return FONT_FAMILY, FONT_CODE


# Başlangıçta kayıtlı tercihi yükle (varsayılan: Cyber-Incognito dark)
set_theme(load_saved_theme())
