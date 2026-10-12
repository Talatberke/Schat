"""Çalışan Cyber-Incognito şablonunun ekran görüntüsünü alır.

    PYTHONPATH=. python tools/shot_theme.py [dark|light] [cikti.png]
"""
from __future__ import annotations
import sys
import time
import tkinter as tk

from PIL import ImageGrab

from secretchat import theme
from secretchat.components import ChatTemplate


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "dark"
    out = sys.argv[2] if len(sys.argv) > 2 else "docs/theme_dark.png"
    theme.set_theme(mode)

    root = tk.Tk()
    root.title(f"{theme.APP_NAME} — {theme.THEME_NAME} ({mode})")
    root.configure(bg=theme.BG)
    root.geometry("900x660+40+40")
    root.minsize(420, 480)

    tpl = ChatTemplate(root, room_code="3K7QX")
    tpl.messages.hide_typing()          # yazıyor etiketini kaldır
    tpl.messages.add("ada", "Kanal güvenli — E2EE anahtarı doğrulandı.",
                     "14:02", mine=False)
    tpl.messages.add("sen", "Süper, oda kodunu paylaşıyorum.", "14:03",
                     mine=True)
    tpl.messages.add_system("kayıt kapalı — mesajlar yalnızca RAM'de",
                            "14:03")

    root.update_idletasks()
    root.update()
    time.sleep(0.4)                     # yazıların render olması için
    root.update()

    # pencereyi en öne getir (aksi halde ImageGrab başka pencereyi yakalar)
    root.lift()
    root.attributes("-topmost", True)
    root.focus_force()
    root.update_idletasks()
    root.update()
    time.sleep(0.5)
    root.update()

    x0, y0 = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    # klavye/ikon tarafı köşelerini de kapsa
    x0 = max(0, x0)
    y0 = max(0, y0)
    img = ImageGrab.grab(bbox=(x0, y0, x0 + w, y0 + h))
    img.save(out)
    print(f"saved {out} ({w}x{h}) mode={theme.CURRENT_MODE}")
    root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
