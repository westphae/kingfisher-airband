"""STT model cache: verify, download (setup), and resolve local paths."""

from __future__ import annotations

import logging
from pathlib import Path

from faster_whisper.utils import download_model

from airband.config import STTCfg

log = logging.getLogger(__name__)


class ModelNotReadyError(RuntimeError):
    """Raised when the STT model is missing or only partially downloaded."""


def incomplete_downloads(models_dir: Path) -> list[Path]:
    """Return any Hugging Face partial download blobs under models_dir."""
    if not models_dir.is_dir():
        return []
    return sorted(models_dir.rglob("*.incomplete"))


def download_model_assets(cfg: STTCfg, models_dir: Path) -> str:
    """Download the configured model into models_dir (requires internet)."""
    models_dir.mkdir(parents=True, exist_ok=True)
    partial = incomplete_downloads(models_dir)
    if partial:
        log.info("resuming %d partial download(s) in %s", len(partial), models_dir)
    log.info("downloading STT model %s → %s", cfg.model, models_dir)
    path = download_model(
        cfg.model,
        cache_dir=str(models_dir),
        local_files_only=False,
    )
    leftover = incomplete_downloads(models_dir)
    if leftover:
        raise ModelNotReadyError(
            f"download finished but {len(leftover)} incomplete file(s) remain in {models_dir}"
        )
    log.info("STT model cached at %s", path)
    return path


def verify_model_ready(cfg: STTCfg, models_dir: Path) -> str:
    """Ensure the model is fully cached locally; never hits the network."""
    partial = incomplete_downloads(models_dir)
    if partial:
        raise ModelNotReadyError(
            f"STT model download incomplete ({len(partial)} partial file(s) in {models_dir}). "
            "While online, run: uv run airband-download-model"
        )
    try:
        path = download_model(
            cfg.model,
            cache_dir=str(models_dir),
            local_files_only=True,
        )
    except Exception as e:
        raise ModelNotReadyError(
            f"STT model {cfg.model!r} not found under {models_dir}. "
            "While online, run: uv run airband-download-model"
        ) from e
    return path


def load_whisper_model(cfg: STTCfg, models_dir: Path, *, local_files_only: bool):
    """Construct a faster-whisper WhisperModel from cfg."""
    from faster_whisper import WhisperModel

    kwargs: dict = {
        "device": "cpu",
        "compute_type": cfg.compute_type,
        "download_root": str(models_dir),
        "local_files_only": local_files_only,
    }
    return WhisperModel(cfg.model, **kwargs)
