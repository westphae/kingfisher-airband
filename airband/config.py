"""Configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _expand(path: str) -> str:
    return os.path.expanduser(path)


@dataclass
class KingfisherCfg:
    base_url: str = "http://127.0.0.1:8080"
    poll_interval_s: float = 10.0


@dataclass
class ChannelCfg:
    freq_mhz: float
    label: str = ""
    role: str = "comms"  # tower, ground, atis, approach, comms


@dataclass
class SDRCfg:
    enabled: bool = True
    rtl_airband_bin: str = "/usr/local/bin/rtl_airband"
    index: int = 0
    gain: int = 25
    correction_ppm: int = 0
    sample_rate: float = 2.4
    squelch_snr_threshold: float = 10.0


@dataclass
class PlannerCfg:
    multichannel_max_span_mhz: float = 2.4
    ground_speed_max_kt: float = 40.0
    atis_scan_dwell_s: float = 8.0
    atis_scan_interval_s: float = 90.0


@dataclass
class STTCfg:
    model: str = "jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper"
    compute_type: str = "int8"
    beam_size: int = 1
    language: str = "en"
    initial_prompt: str = "Aviation air traffic control radio."
    min_segment_s: float = 0.8
    max_segment_s: float = 30.0
    atis_min_duration_s: float = 25.0


@dataclass
class HowgozitCfg:
    atc_comms_log_id: str = ""
    atis_log_id: str = ""
    atc_radio_log_id: str = ""


@dataclass
class RecordCfg:
    enabled: bool = True
    format: str = "flac"
    retention_days: int = 30


@dataclass
class DevReplayCfg:
    enabled: bool = False
    wav_path: str = ""
    freq_mhz: float = 119.25
    interval_s: float = 30.0


@dataclass
class Config:
    http_addr: str = "127.0.0.1:7355"
    data_dir: Path = field(default_factory=lambda: Path(_expand("~/.local/share/kingfisher-airband")))
    kingfisher: KingfisherCfg = field(default_factory=KingfisherCfg)
    aircraft: dict[str, str] = field(default_factory=lambda: {"callsign": "N35B"})
    sdr: SDRCfg = field(default_factory=SDRCfg)
    channels: list[ChannelCfg] = field(default_factory=list)
    planner: PlannerCfg = field(default_factory=PlannerCfg)
    stt: STTCfg = field(default_factory=STTCfg)
    howgozit: HowgozitCfg = field(default_factory=HowgozitCfg)
    record: RecordCfg = field(default_factory=RecordCfg)
    dev_replay: DevReplayCfg = field(default_factory=DevReplayCfg)
    udp_base_port: int = 7356

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def archive_dir(self) -> Path:
        return self.data_dir / "archive"

    @property
    def airports_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "data" / "airports" / "frequencies.json"


def _parse_channels(raw: list[dict[str, Any]]) -> list[ChannelCfg]:
    out: list[ChannelCfg] = []
    for ch in raw or []:
        out.append(
            ChannelCfg(
                freq_mhz=float(ch["freq_mhz"]),
                label=str(ch.get("label", "")),
                role=str(ch.get("role", "comms")),
            )
        )
    return out


def load_config(path: str | Path) -> Config:
    p = Path(path)
    with p.open() as f:
        raw = yaml.safe_load(f) or {}

    kf_raw = raw.get("kingfisher") or {}
    sdr_raw = raw.get("sdr") or {}
    pl_raw = raw.get("planner") or {}
    stt_raw = raw.get("stt") or {}
    hgz_raw = raw.get("howgozit") or {}
    rec_raw = raw.get("record") or {}
    dev_raw = raw.get("dev_replay") or {}

    cfg = Config(
        http_addr=str(raw.get("http_addr", "127.0.0.1:7355")),
        data_dir=Path(_expand(str(raw.get("data_dir", "~/.local/share/kingfisher-airband")))),
        kingfisher=KingfisherCfg(
            base_url=str(kf_raw.get("base_url", "http://127.0.0.1:8080")),
            poll_interval_s=float(kf_raw.get("poll_interval_s", 10)),
        ),
        aircraft=dict(raw.get("aircraft") or {"callsign": "N35B"}),
        sdr=SDRCfg(
            enabled=bool(sdr_raw.get("enabled", True)),
            rtl_airband_bin=str(sdr_raw.get("rtl_airband_bin", "/usr/local/bin/rtl_airband")),
            index=int(sdr_raw.get("index", 0)),
            gain=int(sdr_raw.get("gain", 25)),
            correction_ppm=int(sdr_raw.get("correction_ppm", 0)),
            sample_rate=float(sdr_raw.get("sample_rate", 2.4)),
            squelch_snr_threshold=float(sdr_raw.get("squelch_snr_threshold", 10.0)),
        ),
        channels=_parse_channels(raw.get("channels") or []),
        planner=PlannerCfg(
            multichannel_max_span_mhz=float(pl_raw.get("multichannel_max_span_mhz", 2.4)),
            ground_speed_max_kt=float(pl_raw.get("ground_speed_max_kt", 40)),
            atis_scan_dwell_s=float(pl_raw.get("atis_scan_dwell_s", 8)),
            atis_scan_interval_s=float(pl_raw.get("atis_scan_interval_s", 90)),
        ),
        stt=STTCfg(
            model=str(stt_raw.get("model", STTCfg.model)),
            compute_type=str(stt_raw.get("compute_type", "int8")),
            beam_size=int(stt_raw.get("beam_size", 1)),
            language=str(stt_raw.get("language", "en")),
            initial_prompt=str(stt_raw.get("initial_prompt", STTCfg.initial_prompt)),
            min_segment_s=float(stt_raw.get("min_segment_s", 0.8)),
            max_segment_s=float(stt_raw.get("max_segment_s", 30)),
            atis_min_duration_s=float(stt_raw.get("atis_min_duration_s", 25)),
        ),
        howgozit=HowgozitCfg(
            atc_comms_log_id=str(hgz_raw.get("atc_comms_log_id", "")),
            atis_log_id=str(hgz_raw.get("atis_log_id", "")),
            atc_radio_log_id=str(hgz_raw.get("atc_radio_log_id", "")),
        ),
        record=RecordCfg(
            enabled=bool(rec_raw.get("enabled", True)),
            format=str(rec_raw.get("format", "flac")),
            retention_days=int(rec_raw.get("retention_days", 30)),
        ),
        dev_replay=DevReplayCfg(
            enabled=bool(dev_raw.get("enabled", False)),
            wav_path=str(dev_raw.get("wav_path", "")),
            freq_mhz=float(dev_raw.get("freq_mhz", 119.25)),
            interval_s=float(dev_raw.get("interval_s", 30)),
        ),
        udp_base_port=int(raw.get("udp_base_port", 7356)),
    )
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.models_dir.mkdir(parents=True, exist_ok=True)
    cfg.archive_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "kingfisher-airband" / "config.yaml"
