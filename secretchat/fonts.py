"""Google Fonts desteği: bağlantı/ad → indir → kaydet → uygula.

Kullanıcı fonts.google.com'dan beğendiği yazı tipinin bağlantısını
(örn. ``https://fonts.google.com/specimen/Caveat``) veya doğrudan adını
(örn. ``Caveat``) yapıştırır; modül TTF dosyasını indirip
``~/.secretchat/fonts/`` altında önbelleğe alır ve Windows'ta
``AddFontResourceEx`` (özel/process) ile Tkinter'a tanıtır.

Ağ erişimi yalnızca standart kütüphane (urllib) ile yapılır; ek bağımlılık yok.
"""
from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request

DEFAULT_FAMILY = "Segoe UI"
FONTS_DIR = os.path.join(os.path.expanduser("~"), ".secretchat", "fonts")
MAX_FONT_BYTES = 8 * 1024 * 1024
_TTF_MAGICS = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf")


def parse_family(text: str) -> str:
    """Google Fonts bağlantısı veya düz addan aile adını çıkar.

    Kabul edilenler:
      * https://fonts.google.com/specimen/Caveat
      * https://fonts.googleapis.com/css2?family=Caveat:wght@400..700&...
      * https://fonts.googleapis.com/css?family=Roboto+Mono
      * Düz ad: "Caveat", "Roboto Mono"
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Boş girdi. Bir Google Fonts bağlantısı veya yazı tipi adı yapıştır.")
    if len(raw) > 500:
        raise ValueError("Girdi çok uzun.")
    low = raw.lower()
    if low.startswith(("javascript:", "data:", "file:", "vbscript:")):
        raise ValueError("Geçersiz bağlantı.")

    family = ""
    if "fonts.google.com/specimen/" in low:
        m = re.search(r"fonts\.google\.com/specimen/([^/?#&]+)", raw, re.IGNORECASE)
        if m:
            family = urllib.parse.unquote(m.group(1)).replace("+", " ")
    elif "fonts.googleapis.com/css" in low:
        try:
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(raw).query)
            fams = qs.get("family", [])
            if fams:
                # css2 ilk aileyi al: "Caveat:wght@400..700" → "Caveat"
                family = fams[0].split(":")[0].replace("+", " ")
        except Exception:
            family = ""
    elif "://" in raw or "/" in raw or "." in raw and " " not in raw and len(raw) > 40:
        raise ValueError("Bağlantı anlaşılamadı. Specimen (…/specimen/…) bağlantısı "
                         "veya düz yazı tipi adı kullan.")
    else:
        family = raw

    family = re.sub(r"\s+", " ", family).strip()
    if not family:
        raise ValueError("Yazı tipi adı bulunamadı.")
    if len(family) > 64 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 \-]*", family):
        raise ValueError(f"Geçersiz yazı tipi adı: {family!r} "
                         "(harf, rakam, boşluk ve tire kullanılabilir).")
    return family


def _cache_path(family: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", family).strip("_") or "font"
    return os.path.join(FONTS_DIR, f"{safe}.ttf")


def _fetch_css(family: str, timeout: float = 15.0) -> str:
    # Bilerek özel User-Agent YOK: urllib varsayılanıyla Google truetype
    # (TTF) CSS döndürür; modern tarayıcı UA'si woff2 döndürür.
    q = urllib.parse.quote_plus(family)
    url = f"https://fonts.googleapis.com/css2?family={q}:wght@400&display=swap"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Google Fonts yanıt vermedi (HTTP {resp.status}).")
        return resp.read().decode("utf-8", errors="replace")


def _pick_ttf_url(css: str) -> str:
    """CSS içinden tercihen latin alt-kümenin TTF adresini seç."""
    blocks = re.split(r"/\*\s*([a-z\-]+)\s*\*/", css)
    # blocks: [css0, label1, css1, label2, css2, ...]
    labeled: list[tuple[str, str]] = []
    for i in range(1, len(blocks) - 1, 2):
        for m in re.finditer(r"url\((https://[^)]+\.ttf)\)", blocks[i + 1]):
            labeled.append((blocks[i].strip(), m.group(1)))
    if not labeled:
        for m in re.finditer(r"url\((https://[^)]+\.ttf)\)", css):
            labeled.append(("", m.group(1)))
    if not labeled:
        raise RuntimeError("Bu aile için indirilebilir TTF bulunamadı.")
    for label, url in labeled:
        if label == "latin":
            return url
    return labeled[0][1]


def download_family(family: str, timeout: float = 20.0) -> str:
    """Aileyi indirip önbelleğe al; dosya yolunu döndür (önbellek varsa tekrar indirmez)."""
    path = _cache_path(family)
    if os.path.exists(path) and os.path.getsize(path) > 1024:
        return path
    css = _fetch_css(family, timeout=timeout)
    ttf_url = _pick_ttf_url(css)
    req = urllib.request.Request(ttf_url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(MAX_FONT_BYTES + 1)
    if len(raw) > MAX_FONT_BYTES or len(raw) < 1024:
        raise RuntimeError("İndirilen dosya geçersiz boyutta.")
    if raw[:4] not in _TTF_MAGICS and raw[:4] != b"wOF2" and raw[:4] != b"wOFF":
        raise RuntimeError("İndirilen dosya yazı tipi formatında değil.")
    os.makedirs(FONTS_DIR, exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, path)
    return path


def register_font_file(path: str) -> bool:
    """TTF dosyasını çalışma zamanına tanıt (Windows: özel/process kaydı).

    Başarıda True. Diğer platformlarda elden gelen yapılır.
    """
    if not path or not os.path.exists(path):
        return False
    if os.name == "nt":
        try:
            import ctypes
            gdi32 = ctypes.WinDLL("gdi32")
            fn = gdi32.AddFontResourceExW
            fn.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
            fn.restype = ctypes.c_int
            return fn(os.path.abspath(path), 0x10, None) > 0
        except Exception:
            return False
    # Diğer platformlar: kullanıcı font dizinine kopyala (fc-cache sonrası görülür)
    try:
        dest_dir = os.path.join(os.path.expanduser("~"), ".fonts")
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(path))
        if not os.path.exists(dest):
            import shutil
            shutil.copyfile(path, dest)
        return False  # Tk yeniden başlatılmadan garanti edilemez
    except Exception:
        return False


def ensure_registered(family: str) -> bool:
    """Önbellekteki dosyayı (varsa) kaydet; açılışta kullanılır (ağ yok)."""
    path = _cache_path(family)
    if not os.path.exists(path):
        return False
    return register_font_file(path)


def fetch_and_register(family: str, timeout: float = 20.0) -> str:
    """İndir + tanıt; dosya yolunu döndür (tanıtım başarısızsa da indirilir)."""
    path = download_family(family, timeout=timeout)
    register_font_file(path)
    return path


def load_saved_family() -> str | None:
    """Kayıtlı özel yazı tipi ailesi (yoksa None)."""
    try:
        from . import theme
        return theme.load_saved_font()
    except Exception:
        return None


def save_family(family: str | None) -> None:
    """Yazı tipi tercihini kalıcı kaydet (None → varsayılan)."""
    try:
        from . import theme
        theme.save_font_preference(family)
    except Exception:
        pass
