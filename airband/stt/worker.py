"""faster-whisper STT worker queue."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from airband.config import STTCfg
from airband.ingest.udp import AudioSegment
from airband.lexicon import postprocess

log = logging.getLogger(__name__)


@dataclass
class TranscriptResult:
    freq_mhz: float
    label: str
    role: str
    ts_ns: int
    text: str
    confidence: float
    direction: str
    duration_s: float
    audio_ref: str = ""


class STTWorker:
    def __init__(
        self,
        cfg: STTCfg,
        *,
        callsign: str = "",
        on_result: Callable[[TranscriptResult], None] | None = None,
    ) -> None:
        self._cfg = cfg
        self._callsign = callsign
        self._on_result = on_result
        self._q: queue.PriorityQueue[tuple[int, int, AudioSegment]] = queue.PriorityQueue()
        self._seq = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._model = None

    def _load_model(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        log.info("loading STT model %s (%s)...", self._cfg.model, self._cfg.compute_type)
        t0 = time.perf_counter()
        self._model = WhisperModel(
            self._cfg.model,
            device="cpu",
            compute_type=self._cfg.compute_type,
        )
        log.info("STT model loaded in %.1fs", time.perf_counter() - t0)

    def enqueue(self, seg: AudioSegment, *, priority: int = 5) -> None:
        self._seq += 1
        self._q.put((priority, self._seq, seg))

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="stt-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=30)

    def _transcribe(self, seg: AudioSegment) -> TranscriptResult | None:
        self._load_model()
        assert self._model is not None
        t0 = time.perf_counter()
        segments, info = self._model.transcribe(
            seg.pcm_f32,
            beam_size=self._cfg.beam_size,
            language=self._cfg.language,
            vad_filter=True,
            initial_prompt=self._cfg.initial_prompt,
        )
        parts = []
        logprobs: list[float] = []
        for s in segments:
            parts.append(s.text.strip())
            if s.avg_logprob is not None:
                logprobs.append(float(s.avg_logprob))
        raw = " ".join(parts).strip()
        text = postprocess.postprocess(raw, callsign=self._callsign)
        if not text:
            return None
        conf = float(np.exp(np.mean(logprobs))) if logprobs else 0.0
        direction = postprocess.guess_direction(text, self._callsign)
        log.info(
            "STT %.1fs audio -> %.1fs infer [%s %.3f] %s",
            seg.duration_s,
            time.perf_counter() - t0,
            seg.label,
            seg.freq_mhz,
            text[:80],
        )
        return TranscriptResult(
            freq_mhz=seg.freq_mhz,
            label=seg.label,
            role=seg.role,
            ts_ns=seg.ts_ns,
            text=text,
            confidence=conf,
            direction=direction,
            duration_s=seg.duration_s,
            audio_ref=seg.audio_ref,
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                _, _, seg = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                result = self._transcribe(seg)
                if result and self._on_result:
                    self._on_result(result)
            except Exception:
                log.exception("STT failed for %s", seg.label)
            finally:
                self._q.task_done()
