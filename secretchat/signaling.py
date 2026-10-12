"""MQTT (TLS) sinyalleşme + relay kanalı.

Hem P2P el sıkışması hem de relay sohbet trafiği bu kanaldan geçer.
Broker yalnızca şifreli zarfları taşır; içeriği göremez (E2EE).

paho-mqtt v2 API'si kullanılır (CallbackAPIVersion.VERSION2).
"""
from __future__ import annotations

import json
import logging
import queue
import random
import socket
import ssl
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config

logger = logging.getLogger("secretchat.signaling")

# paho-mqtt 2.x: ayrı callback API sürümü parametresi gerekiyor.
try:
    from paho.mqtt.client import CallbackAPIVersion
    from paho.mqtt.client import Client as _MqttClient
    _PAHO_V2 = True
except ImportError:  # paho 1.x fallback
    from paho.mqtt.client import Client as _MqttClient
    _PAHO_V2 = False

BROKERS: List[Tuple[str, int, bool]] = [
    (config.DEFAULT_BROKER, config.DEFAULT_PORT, True),    # TLS
    ("test.mosquitto.org", 8883, True),                    # TLS
    (config.WS_BROKER, config.WS_PORT, True),              # TLS (WSS)
]

StatusCb = Optional[Callable[[str], None]]
MessageCb = Optional[Callable[[str, bytes], None]]  # (topic, payload)


class SignalingChannel:
    """TLS'li MQTT kanalı; topic'lere abone olur, zarf yayınlar."""

    def __init__(self, status_cb: StatusCb = None, topics: Tuple[str, ...] = ()):
        self.status_cb = status_cb
        self.topics = list(topics)
        self._client = None
        self._lock = threading.Lock()
        self._connected = threading.Event()
        self.broker_index = random.randrange(len(BROKERS))
        self.connected = False
        # Gelen zarflar paho'nun ağ thread'ini BLOKLAMADAN işlenir:
        # on_message sınırlı kuyruğa (bounded queue) ekler, worker thread dağıtır (DoS koruması).
        self._inbox: "queue.Queue[Tuple[str, bytes]]" = queue.Queue(maxsize=config.MAX_INBOX_SIZE)
        self._dispatch_stop = threading.Event()
        self._dispatch_thread = threading.Thread(
            target=self._dispatch_loop, daemon=True)
        self._dispatch_thread.start()

    # ------------------------------------------------------------- lifecycle

    def _make_client(self):
        if _PAHO_V2:
            client = _MqttClient(CallbackAPIVersion.VERSION2,
                                 client_id="sc-" + uuid.uuid4().hex[:10])
        else:
            client = _MqttClient(client_id="sc-" + uuid.uuid4().hex[:10])
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.on_publish = lambda *a, **k: None
        return client

    def start(self, timeout: float = 12.0) -> bool:
        """Broker'lara sırayla bağlanmayı dener; biri tutarsa True döner.

        `_preferred_broker` özelliği ayarlanmışsa o index ilk sıraya alınır;
        bu sayede ön-bağlantı probe'undan gelen kazanan broker direkt denenir,
        soğuk başlatma broker keşif döngüsü atlanır.
        """
        preferred = getattr(self, "_preferred_broker", None)
        all_indices = list(range(self.broker_index, len(BROKERS))) + list(range(0, self.broker_index))

        if preferred is not None and 0 <= preferred < len(BROKERS):
            # Tercih edilen index'i en öne al; kalanlar mevcut rotasyon sırasında
            order = [preferred] + [i for i in all_indices if i != preferred]
        else:
            order = all_indices

        for idx in order:
            host, port, tls = BROKERS[idx]
            if self._try_connect(host, port, tls, timeout):
                self.broker_index = idx
                return True
        return False

    def _try_connect(self, host: str, port: int, tls: bool, timeout: float) -> bool:
        self._set_status(f"Bağlanıyor: {host}:{port} ...")
        client = self._make_client()
        try:
            if tls:
                ctx = ssl.create_default_context()
                # Herkese açık broker'lar sertifika zinciri sorunları çıkarabilir;
                # E2EE tasarımı yüzünden bu güvenlik kritik değildir (mesajlar
                # zaten şifreli). Yine de sertifika doğrulaması aktif.
                client.tls_set_context(ctx)
                client.tls_insecure_set(False)
            client.connect(host, port, keepalive=30)
            client.loop_start()
            if not self._connected.wait(timeout):
                client.loop_stop()
                try:
                    client.disconnect()
                except Exception:
                    pass
                return False
            self._client = client
            self.connected = True
            return True
        except Exception as exc:
            self._set_status(f"{host} başarısız: {exc}")
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass
            return False

    def stop(self) -> None:
        """Kanalı kapat."""
        self._dispatch_stop.set()
        with self._lock:
            client = self._client
            self._client = None
            self.connected = False
        if client is not None:
            try:
                client.disconnect()
                client.loop_stop()
            except Exception:
                pass
        self._connected.clear()

    # ------------------------------------------------------------- callbacks

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False):
            self._set_status(f"broker reddetti: {reason_code}")
            return
        for topic in self.topics:
            try:
                client.subscribe(topic, qos=1)
            except Exception:
                pass
        self._connected.set()
        self._set_status("broker'a bağlandı")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.connected = False
        self._connected.clear()
        self._set_status("broker bağlantısı kesildi")

    def _on_message(self, client, userdata, msg):
        # Ağ thread'inde asla ağır çalışma yapma; sınırlı kuyruğa at ve dön.
        try:
            self._inbox.put_nowait((msg.topic, msg.payload))
        except queue.Full:
            logger.warning("Sinyalleşme gelen kutusu dolu (%d)! Paket düşürüldü.", config.MAX_INBOX_SIZE)

    def _dispatch_loop(self) -> None:
        """Gelen zarfları paho thread'i dışında dağıtan worker."""
        while not self._dispatch_stop.is_set():
            try:
                topic, payload = self._inbox.get(timeout=0.25)
            except queue.Empty:
                continue
            if self.on_message:
                try:
                    self.on_message(topic, payload)
                except Exception as exc:
                    logger.debug("Zarf dağıtımında hata: %s", exc)

    # ------------------------------------------------------------- pub / sub

    def set_topics(self, topics: Tuple[str, ...]) -> None:
        """Bağlantı sonrası abonelik listesini değiştir."""
        self.topics = list(topics)
        with self._lock:
            client = self._client
        if client is not None and self.connected:
            for topic in self.topics:
                try:
                    client.subscribe(topic, qos=1)
                except Exception as exc:
                    logger.debug("Topic abone hatası (%s): %s", topic, exc)

    def publish(self, topic: str, payload: Dict[str, Any] | bytes) -> None:
        """Zararı yayınla (QoS 1)."""
        with self._lock:
            client = self._client
        if client is None:
            return
        data = payload if isinstance(payload, bytes) else json.dumps(
            payload, separators=(",", ":")).encode("utf-8")
        try:
            # QoS 1: broker onayı için paho zaten yeniden dener. Network
            # thread'inden çağrılabileceğimiz için BEKLEMEYIZ (deadlock riski).
            client.publish(topic, data, qos=1)
        except Exception as exc:
            logger.debug("Yayınlama hatası (%s): %s", topic, exc)

    # ------------------------------------------------------------- misc

    on_message: MessageCb = None

    def _set_status(self, text: str) -> None:
        if self.status_cb:
            try:
                self.status_cb(text)
            except Exception:
                pass


def topic_for(code: str, suffix: str) -> str:
    """Oda kodundan topic üret.

    Güvenlik: kod sıkı doğrulamadan geçmeden topic ÜRETİLMEZ — aksi hâlde
    MQTT joker karakterleri (`+`, `#`) ile başka tüm odaların topic'lerine
    abone olunabilir (broken access control / topic enjeksiyonu).
    """
    from . import messages  # yerel import: döngüsel import önleme
    ok, reason = messages.validate_room_code(code)
    if not ok:
        raise ValueError(f"geçersiz oda kodu: {reason}")
    if suffix not in ("data", "ctrl"):
        raise ValueError("geçersiz topic son eki")
    return f"{config.SIGNAL_PREFIX}{reason}/{suffix}"
