"""FLAC segment archival."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf

log = logging.getLogger(__name__)


def write_flac(
    archive_dir: Path,
    *,
    freq_mhz: float,
    ts_ns: int,
    pcm_f32: np.ndarray,
    sample_rate: int = 16000,
) -> str:
    """Write segment; return relative path from archive_dir."""
    day = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).strftime("%Y%m%d")
    sub = archive_dir / day / f"{freq_mhz:.3f}"
    sub.mkdir(parents=True, exist_ok=True)
    name = f"{ts_ns}.flac"
    path = sub / name
    sf.write(path, pcm_f32, sample_rate, format="FLAC", subtype="PCM_16")
    rel = str(path.relative_to(archive_dir))
    log.debug("archived %s", rel)
    return rel
