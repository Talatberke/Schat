"""El sıkışma hata ayıklama: her zarfın akışını izler."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from secretchat import messages
from secretchat.room import Client, Host


def trace(name, side, seen):
    """handle_envelope devreden çıkmadan ham izleme: orijinal callback sarılır."""
    original = side.channel.on_message

    def wire(topic, payload):
        try:
            env = messages.decode_envelope(payload)
            print(f"[{name}] t={env.get('t')} mid={env.get('mid')} "
                  f"nick={env.get('nick')} announce={env.get('announce')}")
        except Exception as exc:
            print(f"[{name}] BAD {exc}")
        if original:
            original(topic, payload)
        seen[name].append(env.get("t"))

    side.channel.on_message = wire


seen = {"host": [], "client": []}

h = Host("kurucu")
print("host start:", h.start(), "code:", h.room_code)
trace("host", h, seen)

c = Client("katilan", h.room_code)
print("client start:", c.start())
trace("client", c, seen)

print("joined:", c.wait_joined(25))
print("host members:", list(h.members))
print("client sas:", c.sas, "| host sas:", h.pending_sas)

c.send_chat("ping")
time.sleep(2)

client_msgs, host_msgs = [], []
c.on_message = lambda s, t, sys_: client_msgs.append((s, t))
h.on_message = lambda s, t, sys_: host_msgs.append((s, t))
h.send_chat("pong")
c.send_chat("ping2")
time.sleep(3)
print("client got:", client_msgs)
print("host got:", host_msgs)

c.leave()
h.stop()
print("done")
