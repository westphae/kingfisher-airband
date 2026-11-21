"""Live PCM fan-out for browser debug monitor (f32le @ 8 kHz from rtl_airband)."""

from __future__ import annotations

import logging
import queue
import socket
import threading

log = logging.getLogger(__name__)

LIVE_SAMPLE_RATE = 8000


class LiveAudioHub:
    """Thread-safe broadcast of raw UDP PCM payloads to WebSocket subscribers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queues: list[queue.Queue[bytes]] = []

    def subscribe(self) -> queue.Queue[bytes]:
        q: queue.Queue[bytes] = queue.Queue(maxsize=48)
        with self._lock:
            self._queues.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[bytes]) -> None:
        with self._lock:
            if q in self._queues:
                self._queues.remove(q)

    def publish(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            for q in list(self._queues):
                try:
                    q.put_nowait(data)
                except queue.Full:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        q.put_nowait(data)
                    except queue.Full:
                        self._queues.remove(q)


LIVE_AUDIO = LiveAudioHub()


class LiveAudioReceiver:
    """Listen on a dedicated rtl_airband UDP port (usually continuous demod)."""

    def __init__(self, port: int, hub: LiveAudioHub = LIVE_AUDIO) -> None:
        self.port = port
        self._hub = hub
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"live-udp-{self.port}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", self.port))
        sock.settimeout(0.5)
        log.info("live audio UDP on :%d", self.port)
        while not self._stop.is_set():
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                if not self._stop.is_set():
                    log.exception("live audio UDP error")
                break
            self._hub.publish(data)
        sock.close()
