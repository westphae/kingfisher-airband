"""HTTP API and transcript store."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from airband.stt.worker import TranscriptResult


@dataclass
class ChannelStatus:
    freq_mhz: float
    label: str
    role: str
    udp_port: int
    mode: str


class TranscriptStore:
    def __init__(self, max_items: int = 500) -> None:
        self._lock = threading.Lock()
        self._items: deque[TranscriptResult] = deque(maxlen=max_items)
        self._channels: list[ChannelStatus] = []
        self._sdr_running = False
        self._sdr_error = ""
        self._kingfisher_ok = False

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

    def set_channels(self, channels: list[ChannelStatus]) -> None:
        with self._lock:
            self._channels = channels

    def set_sdr_running(self, v: bool, error: str = "") -> None:
        with self._lock:
            self._sdr_running = v
            self._sdr_error = error

    def set_kingfisher_ok(self, v: bool) -> None:
        with self._lock:
            self._kingfisher_ok = v

    def health(self) -> dict:
        with self._lock:
            return {
                "ok": True,
                "sdr_running": self._sdr_running,
                "sdr_error": self._sdr_error,
                "kingfisher_ok": self._kingfisher_ok,
                "transcript_count": len(self._items),
                "channels": [asdict(c) for c in self._channels],
                "ts_ns": time.time_ns(),
            }


def create_app(store: TranscriptStore, archive_dir: Path, web_dir: Path) -> FastAPI:
    app = FastAPI(title="kingfisher-airband", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict:
        return store.health()

    @app.get("/api/transcripts")
    def transcripts(since: int = 0) -> dict:
        return {"transcripts": store.list_since(since)}

    @app.get("/api/channels")
    def channels() -> dict:
        return {"channels": store.health()["channels"]}

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
