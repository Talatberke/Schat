"""Fotoğraf gönderimi: dosya doğrulama, yeniden boyutlandırma, base64 kodlama.

Ağ katmanı (``messages``/``room``) yalnızca base64 metin taşır; bu modül
dosya ↔ base64 dönüşümünü ve sohbet akışına uygun küçük boyut üretimini
üstlenir. Pillow zorunludur (requirements.txt).

Güvenlik notları:
  * Yalnızca bilinen resim uzantıları kabul edilir.
  * Girdi dosyası boyutu sınırlıdır (DoS koruması).
  * Çıktı: en uzun kenar ``IMAGE_MAX_DIM``'e indirilir, JPEG (kalite 82)
    veya saydamlık varsa PNG olarak kodlanır; base64 uzunluğu
    ``config.IMAGE_MAX_B64_LEN`` ile sınırlıdır.
  * Decompression-bomb koruması için Pillow'un ``MAX_IMAGE_PIXELS`` değeri
    düşürülür.
"""
from __future__ import annotations

import base64
import binascii
import io
import os
from typing import Dict, Tuple

from PIL import Image

# Decompression bomb eşiğini sıkılaştır (~50 MP)
Image.MAX_IMAGE_PIXELS = 50_000_000

SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

# Varsayılanlar config.py'dan okunur; import döngüsü olmaması için
# değerler burada tekrar tanımlanmaz, fonksiyonlar config'e başvurur.


def _cfg(name: str, default: int) -> int:
    try:
        from . import config
        return int(getattr(config, name, default))
    except Exception:
        return default


def validate_image_file(path: str) -> Tuple[bool, str]:
    """Dosya uzantısı + boyut ön kontrolü."""
    if not isinstance(path, str) or not path:
        return False, "Dosya yolu geçersiz."
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTS:
        return False, f"Desteklenmeyen dosya türü: {ext or '?'} (png/jpg/gif/webp/bmp)"
    try:
        size = os.path.getsize(path)
    except OSError:
        return False, "Dosya okunamadı."
    max_raw = _cfg("IMAGE_MAX_RAW_BYTES", 8 * 1024 * 1024)
    if size <= 0:
        return False, "Dosya boş."
    if size > max_raw:
        return False, f"Dosya çok büyük (en fazla {max_raw // (1024 * 1024)} MB)."
    return True, ""


def prepare_image(path: str, caption: str = "") -> Dict[str, object]:
    """Görüntüyü sohbet gönderimine hazırla.

    Dönüş: ``{"b64": str, "w": int, "h": int, "fmt": str, "caption": str}``.
    Hata durumunda ``ValueError`` yükseltir.
    """
    ok, reason = validate_image_file(path)
    if not ok:
        raise ValueError(reason)

    max_dim = _cfg("IMAGE_MAX_DIM", 1024)
    try:
        with Image.open(path) as im:
            im.load()
            # Animasyonlu GIF'in ilk karesini al
            if getattr(im, "is_animated", False):
                try:
                    im.seek(0)
                except Exception:
                    pass
            has_alpha = im.mode in ("RGBA", "LA", "PA") or (
                im.mode == "P" and "transparency" in im.info
            )
            im = im.convert("RGBA" if has_alpha else "RGB")
            w0, h0 = im.size
            if w0 <= 0 or h0 <= 0:
                raise ValueError("Görüntü boyutu okunamadı.")
            scale = min(1.0, max_dim / max(w0, h0))
            if scale < 1.0:
                im = im.resize((max(1, int(w0 * scale)), max(1, int(h0 * scale))),
                               Image.LANCZOS)
            w, h = im.size
            buf = io.BytesIO()
            if has_alpha:
                im.save(buf, format="PNG", optimize=True)
                fmt = "png"
            else:
                # RGB'ye indir (RGBA→JPEG hata verir)
                if im.mode == "RGBA":
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.split()[3])
                    im = bg
                im.save(buf, format="JPEG", quality=82, optimize=True)
                fmt = "jpeg"
            raw = buf.getvalue()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Görüntü işlenemedi: {exc}") from exc

    b64 = base64.b64encode(raw).decode("ascii")
    max_b64 = _cfg("IMAGE_MAX_B64_LEN", 220_000)
    if len(b64) > max_b64:
        raise ValueError("Sıkıştırılmış görüntü bile çok büyük, daha küçük bir dosya seçin.")
    clean_cap = (caption or "")[:200].strip()
    # Kontrol karakterlerini temizle (sanitize ile tutarlı)
    clean_cap = "".join(ch for ch in clean_cap if ch in ("\n", "\t") or ord(ch) >= 32)
    return {"b64": b64, "w": w, "h": h, "fmt": fmt, "caption": clean_cap}


def decode_image_bytes(b64: str) -> bytes:
    """Base64 → ham resim baytı (boyut/sözdizimi korumalı)."""
    max_b64 = _cfg("IMAGE_MAX_B64_LEN", 220_000)
    if not isinstance(b64, str) or not b64:
        raise ValueError("Görüntü verisi boş.")
    if len(b64) > max_b64:
        raise ValueError("Görüntü verisi çok büyük.")
    try:
        raw = base64.b64decode(b64.encode("ascii"), validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("Görüntü verisi bozuk.") from exc
    if not raw.startswith((b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM")):
        # İmza kontrolü esnek: PIL'e de doğrulat
        pass
    return raw


def open_pil_image(b64: str) -> Image.Image:
    """Sohbetten gelen base64'ü doğrulanmış PIL görüntüsüne çevir."""
    raw = decode_image_bytes(b64)
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
        im = im.convert("RGB")
        return im
    except Exception as exc:
        raise ValueError("Görüntü açılamadı.") from exc


def make_thumbnail(b64: str, max_w: int = 0, max_h: int = 0) -> Image.Image:
    """Sohbet balonu için küçük önizleme (orantılı)."""
    if not max_w:
        max_w = _cfg("IMAGE_THUMB_W", 360)
    if not max_h:
        max_h = _cfg("IMAGE_THUMB_H", 280)
    im = open_pil_image(b64)
    w0, h0 = im.size
    scale = min(1.0, max_w / max(1, w0), max_h / max(1, h0))
    if scale < 1.0:
        im = im.resize((max(1, int(w0 * scale)), max(1, int(h0 * scale))),
                       Image.LANCZOS)
    return im


def to_photoimage(b64: str, max_w: int = 0, max_h: int = 0):
    """Tkinter'da gösterilebilir ``ImageTk.PhotoImage`` üret.

    Yalnızca UI katmanından çağrılmalı (Tk gerektirir).
    """
    from PIL import ImageTk

    thumb = make_thumbnail(b64, max_w=max_w, max_h=max_h)
    return ImageTk.PhotoImage(thumb), thumb.size[0], thumb.size[1]
