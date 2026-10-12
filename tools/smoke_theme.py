"""Tema + bileşen duman testi: widget'ları gerçekten kur, örnek mesaj ekle,
yeniden boyutlandır (duyarlı spacing), kaydet ve temizle."""
from __future__ import annotations
import tkinter as tk

from secretchat import theme
from secretchat.components import ChatTemplate


def main() -> int:
    root = tk.Tk()
    root.title("Smoke")
    root.geometry("860x640")
    tpl = ChatTemplate(root, room_code="3K7QX")
    root.update_idletasks()
    root.update()

    # -- daralt -> mobil kırılım spacing
    root.geometry("420x560")
    root.update_idletasks()
    root.update()
    mobile = theme.spacing_for(420)
    wide = theme.spacing_for(1440)
    print("spacing mobile:", mobile)
    print("spacing desktop:", wide)
    assert mobile["gutter"] < wide["gutter"], "mobil gutter daha küçük olmalı"

    # -- geri genişlet
    root.geometry("1440x800")
    root.update_idletasks()
    root.update()

    # -- mesaj ekle (baloncuk çizimi)
    tpl.messages.hide_typing()
    tpl.messages.add("ada", "duman testi mesajı", "12:00", mine=False)
    tpl.messages.add("sen", "yanıt", "12:01", mine=True)
    tpl.messages.add_system("sistem notu", "12:02")
    root.update_idletasks()
    root.update()

    # -- tema geçişi: light yap, widget'lar yeniden kurulur
    theme.set_theme("light")
    assert not theme.is_dark()
    print("light mode BG:", theme.BG, "PRIMARY:", theme.PRIMARY)
    theme.set_theme("dark")
    assert theme.is_dark()
    print("dark mode BG:", theme.BG, "PRIMARY:", theme.PRIMARY)

    # -- CSS çıktısı üret (aktif moda göre senkron)
    css = theme.css_style_sheet()
    media = theme.spacing_css()
    assert "--primary: #00F5D4" in css
    assert ".bubble-in" in css and ".bubble-out" in css
    assert "@media (min-width: 768px)" in media

    theme.set_theme("light")
    css_light = theme.css_style_sheet()
    assert "--primary: #0E7490" in css_light, "açık mod CSS'i taze değil"
    assert "--bg: #F8FAFC" in css_light
    theme.set_theme("dark")
    print("CSS bytes:", len(css), "| light CSS sync OK | media bytes:", len(media))

    root.destroy()
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
