"""ui.py sohbet ekranı yerleşim yeniden-üretici (geçici)."""
from __future__ import annotations
import sys, time, tkinter as tk
from PIL import ImageGrab
from secretchat import theme, ui


class FakeRoom:
    room_code = "3K7QX"
    nickname = "sen"
    members = {"sen": 1, "ada": 2}

    def send_chat(self, t):
        return True

    def leave(self):
        pass


def main():
    geom = sys.argv[1] if len(sys.argv) > 1 else "880x620"
    out = sys.argv[2] if len(sys.argv) > 2 else "_repro_chat.png"
    mode = sys.argv[3] if len(sys.argv) > 3 else "dark"
    theme.set_theme(mode)

    root = tk.Tk()
    app = ui.ChatApp(root)
    root.geometry(geom)

    app.room = FakeRoom()
    app.room_code = "3K7QX"
    app._enter_chat(is_host=False)
    for i in range(25):
        app._append_message("ada", f"Mesaj {i} — şifreli deneme metni.", False)

    root.update_idletasks()
    root.update()
    time.sleep(0.3)
    root.update()
    root.lift()
    root.attributes("-topmost", True)
    root.focus_force()
    root.update_idletasks()
    root.update()
    time.sleep(0.4)
    root.update()

    # --- ölçümler
    print(f"window: {root.winfo_width()}x{root.winfo_height()}")
    for name in ("chat", "chat_top", "chat_mid", "chat_bottom", "msg_entry", "btn_send"):
        w = getattr(app, name, None)
        if w is None or not w.winfo_exists():
            print(f"  {name}: YOK")
            continue
        y, h = w.winfo_y(), w.winfo_height()
        print(f"  {name}: y={y} h={h} bottom={y + h}"
              + ("  <-- PENCERE DIŞI" if y + h > root.winfo_height() else ""))
    print("  bar height ok:", app.chat_bottom.winfo_height(),
          "spec 60-80:", 60 <= app.chat_bottom.winfo_height() <= 80)

    x0, y0 = root.winfo_rootx(), root.winfo_rooty()
    img = ImageGrab.grab(bbox=(x0, y0, x0 + root.winfo_width(), y0 + root.winfo_height()))
    img.save(out)
    print("saved", out)
    root.destroy()


if __name__ == "__main__":
    main()
