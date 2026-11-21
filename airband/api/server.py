"""HTTP API and transcript store."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from airband.ingest.live import LIVE_AUDIO, LIVE_SAMPLE_RATE
from airband.ingest.udp import INGEST_STATS
from airband.stt.worker import TranscriptResult


@dataclass
class ChannelStatus:
    freq_mhz: float
    label: str
    role: str
    udp_port: int
    mode: str


class ChannelPatch(BaseModel):
    freq_mhz: float
    enabled: bool


class PlannerPatch(BaseModel):
    include_gps_airport: bool | None = None
    include_active_com: bool | None = None


class DebugPatch(BaseModel):
    live_audio: bool


class TranscriptStore:
    def __init__(self, max_items: int = 500) -> None:
        self._lock = threading.Lock()
        self._items: deque[TranscriptResult] = deque(maxlen=max_items)
        self._channels: list[ChannelStatus] = []
        self._sdr_running = False
        self._sdr_error = ""
        self._kingfisher_ok = False
        self._plan_mode = ""
        self._stt_ready = False
        self._stt_error = ""
        self._debug: dict[str, Any] = {}

    def add(self, t: TranscriptResult) -> None:
        with self._lock:
            self._items.append(t)

    def list_since(self, since_ns: int = 0) -> list[dict]:
        with self._lock:
            out = [asdict(t) for t in self._items if t.ts_ns >= since_ns]
        return out

    def get_audio_path(self, archive_dir: Path, audio_ref: str) -> Path | None:
        p = archive_dir / audio_ref
        if p.is_file():
            return p
        return None

    def set_channels(self, channels: list[ChannelStatus], plan_mode: str = "") -> None:
        with self._lock:
            self._channels = channels
            self._plan_mode = plan_mode

    def set_sdr_running(self, v: bool, error: str = "") -> None:
        with self._lock:
            self._sdr_running = v
            self._sdr_error = error

    def set_kingfisher_ok(self, v: bool) -> None:
        with self._lock:
            self._kingfisher_ok = v

    def set_stt_ready(self, ready: bool, error: str = "") -> None:
        with self._lock:
            self._stt_ready = ready
            self._stt_error = error

    def set_debug(self, debug: dict[str, Any]) -> None:
        with self._lock:
            self._debug = debug

    def health(self) -> dict:
        with self._lock:
            return {
                "ok": True,
                "sdr_running": self._sdr_running,
                "sdr_error": self._sdr_error,
                "stt_ready": self._stt_ready,
                "stt_error": self._stt_error,
                "ingest": {
                    "udp_packets": INGEST_STATS.udp_packets,
                    "udp_bytes": INGEST_STATS.udp_bytes,
                    "last_peak": round(INGEST_STATS.last_peak, 6),
                    "last_packet_ts_ns": INGEST_STATS.last_packet_ts_ns,
                    "segments_emitted": INGEST_STATS.segments_emitted,
                },
                "debug": self._debug,
                "kingfisher_ok": self._kingfisher_ok,
                "transcript_count": len(self._items),
                "plan_mode": self._plan_mode,
                "channels": [asdict(c) for c in self._channels],
                "ts_ns": time.time_ns(),
            }


def create_app(
    daemon: Any,
    archive_dir: Path,
    web_dir: Path,
) -> FastAPI:
    store = daemon.store
    app = FastAPI(title="kingfisher-airband", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict:
        store.set_debug(
            {
                "live_audio": daemon.cfg.debug.live_audio,
                "live_audio_continuous": daemon.cfg.debug.live_audio_continuous,
                "live_audio_port": daemon.cfg.debug.live_audio_port,
            }
        )
        return store.health()

    @app.get("/api/transcripts")
    def transcripts(since: int = 0) -> dict:
        return {"transcripts": store.list_since(since)}

    @app.get("/api/channels")
    def channels_active() -> dict:
        h = store.health()
        return {"channels": h["channels"], "plan_mode": h["plan_mode"]}

    @app.get("/api/channels/catalog")
    def channels_catalog() -> dict[str, Any]:
        return daemon.channel_catalog()

    @app.patch("/api/channels")
    def patch_channel(body: ChannelPatch) -> dict[str, Any]:
        try:
            return daemon.set_channel_enabled(body.freq_mhz, body.enabled)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.patch("/api/planner")
    def patch_planner(body: PlannerPatch) -> dict[str, Any]:
        return daemon.set_planner(
            include_gps_airport=body.include_gps_airport,
            include_active_com=body.include_active_com,
        )

    @app.patch("/api/debug")
    def patch_debug(body: DebugPatch) -> dict[str, Any]:
        return daemon.set_live_audio(body.live_audio)

    @app.websocket("/ws/live-audio")
    async def live_audio_ws(ws: WebSocket) -> None:
        if not daemon.cfg.debug.live_audio:
            await ws.close(code=1008, reason="live audio disabled in config")
            return
        await ws.accept()
        header = {
            "sample_rate": LIVE_SAMPLE_RATE,
            "format": "f32le",
            "channels": 1,
            "continuous": daemon.cfg.debug.live_audio_continuous,
        }
        await ws.send_text(json.dumps(header))
        q = LIVE_AUDIO.subscribe()
        loop = asyncio.get_running_loop()
        try:
            while True:
                chunk = await loop.run_in_executor(None, q.get)
                await ws.send_bytes(chunk)
        except WebSocketDisconnect:
            pass
        finally:
            LIVE_AUDIO.unsubscribe(q)

    @app.get("/api/audio/{path:path}")
    def audio(path: str) -> FileResponse:
        p = store.get_audio_path(archive_dir, path)
        if not p:
            raise HTTPException(404, "audio not found")
        return FileResponse(p, media_type="audio/flac")

    static = web_dir / "static"
    if static.is_dir():
        app.mount("/static", StaticFiles(directory=str(static)), name="static")

    index = web_dir / "index.html"

    @app.get("/")
    def index_page() -> HTMLResponse:
        if index.is_file():
            return HTMLResponse(index.read_text())
        return HTMLResponse("<h1>kingfisher-airband</h1><p>UI missing</p>")

    return app
