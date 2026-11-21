"""Tests for STT model cache helpers."""

from pathlib import Path
from unittest.mock import patch

import pytest

from airband.config import STTCfg
from airband.stt.model import ModelNotReadyError, download_model_assets, incomplete_downloads, verify_model_ready


def test_incomplete_downloads_finds_partial(tmp_path: Path):
    partial = tmp_path / "models--foo" / "blobs" / "abc.incomplete"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"x")
    assert incomplete_downloads(tmp_path) == [partial]


def test_verify_model_ready_rejects_incomplete(tmp_path: Path):
    partial = tmp_path / "x.incomplete"
    partial.write_bytes(b"")
    cfg = STTCfg()
    with pytest.raises(ModelNotReadyError, match="incomplete"):
        verify_model_ready(cfg, tmp_path)


def test_verify_model_ready_requires_cache(tmp_path: Path):
    cfg = STTCfg()
    with patch("airband.stt.model.download_model", side_effect=OSError("missing")):
        with pytest.raises(ModelNotReadyError, match="not found"):
            verify_model_ready(cfg, tmp_path)


def test_download_model_assets_checks_leftover_incomplete(tmp_path: Path):
    cfg = STTCfg()
    with patch("airband.stt.model.download_model", return_value="/cache/model"):
        partial = tmp_path / "left.incomplete"
        partial.write_bytes(b"")
        with pytest.raises(ModelNotReadyError, match="incomplete"):
            download_model_assets(cfg, tmp_path)
