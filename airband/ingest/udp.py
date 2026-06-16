"""UDP PCM ingest from rtl_airband (f32le @ 8 kHz) with VAD segmentation."""

from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

try:
    import webrtcvad
except ImportError:
    webrtcvad = None  # type: ignore

log = logging.getLogger(__name__)

SAMPLE_RATE_IN = 8000
SAMPLE_RATE_OUT = 16000


@dataclass
class AudioSegment:
    freq_mhz: float
    label: str
    role: str
    ts_ns: int
    pcm_f32: np.ndarray  # mono 16 kHz float32 [-1, 1]
    duration_s: float
    audio_ref: str = ""


def _resample_8k_to_16k(pcm8: np.ndarray) -> np.ndarray:
    if len(pcm8) < 2:
        return np.zeros(0, dtype=np.float32)
    # Linear upsample 8k -> 16k
    x = np.arange(len(pcm8), dtype=np.float32)
    xi = np.linspace(0, len(pcm8) - 1, len(pcm8) * 2, dtype=np.float32)
    return np.interp(xi, x, pcm8).astype(np.float32)


class UDPSegmentReceiver:
    """Receive float32 PCM bursts and emit segments on silence."""

    def __init__(
        self,
        port: int,
        freq_mhz: float,
        label: str,
        role: str,
        on_segment: Callable[[AudioSegment], None],
        *,
        min_segment_s: float = 0.8,
        max_segment_s: float = 30.0,
        silence_tail_s: float = 0.35,
    ) -> None:
        self.port = port
        self.freq_mhz = freq_mhz
        self.label = label
        self.role = role
        self.on_segment = on_segment
        self.min_segment_s = min_segment_s
        self.max_segment_s = max_segment_s
        self.silence_tail_s = silence_tail_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._buf: list[float] = []
        self._seg_start_ns: int | None = None
        self._last_audio_ns = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"udp-{self.port}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _emit(self) -> None:
        if not self._buf or self._seg_start_ns is None:
            return
        pcm8 = np.array(self._buf, dtype=np.float32)
        dur = len(pcm8) / SAMPLE_RATE_IN
        if dur < self.min_segment_s:
            self._buf.clear()
            self._seg_start_ns = None
            return
        pcm16 = _resample_8k_to_16k(pcm8)
        seg = AudioSegment(
            freq_mhz=self.freq_mhz,
            label=self.label,
            role=self.role,
            ts_ns=self._seg_start_ns,
            pcm_f32=pcm16,
            duration_s=len(pcm16) / SAMPLE_RATE_OUT,
        )
        self._buf.clear()
        self._seg_start_ns = None
        try:
            self.on_segment(seg)
        except Exception:
            log.exception("on_segment callback failed")

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", self.port))
        sock.settimeout(0.25)
        log.info("UDP ingest listening on :%d (%s %.3f MHz)", self.port, self.label, self.freq_mhz)

        while not self._stop.is_set():
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                now = time.time_ns()
                if self._buf and self._last_audio_ns and (now - self._last_audio_ns) / 1e9 > self.silence_tail_s:
                    self._emit()
                continue
            if len(data) < 4:
                continue
            n = len(data) // 4
            samples = struct.unpack(f"{n}f", data[: n * 4])
            peak = max(abs(s) for s in samples) if samples else 0.0
            if peak < 1e-5:
                continue
            now_ns = time.time_ns()
            if self._seg_start_ns is None:
                self._seg_start_ns = now_ns
            self._last_audio_ns = now_ns
            self._buf.extend(samples)
            max_samples = int(self.max_segment_s * SAMPLE_RATE_IN)
            if len(self._buf) >= max_samples:
                self._emit()

        sock.close()
        if self._buf:
            self._emit()
