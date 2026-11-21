"""Daemon entrypoint."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

import uvicorn

from airband.api.server import ChannelStatus, TranscriptStore, create_app
from airband.atis.parser import atis_to_howgozit_values, parse_atis
from airband.config import Config, default_config_path, load_config, persist_runtime_prefs
from airband.ingest.udp import AudioSegment, UDPSegmentReceiver
from airband.ingest.live import LiveAudioReceiver
from airband.kingfisher.client import KingfisherClient
from airband.planner.channels import RadioPlan, plan_channels
from airband.record.flac import write_flac
from airband.sdr.rtl_airband import RTLAirbandProcess
from airband.stt.worker import STTWorker, TranscriptResult
from airband.stt.model import ModelNotReadyError, download_model_assets, verify_model_ready

log = logging.getLogger(__name__)


class Daemon:
    def __init__(self, cfg: Config, config_path: Path) -> None:
        self.cfg = cfg
        self.config_path = config_path
        self.store = TranscriptStore()
        self.kf = KingfisherClient(cfg)
        self.sdr = RTLAirbandProcess(cfg)
        self._receivers: list[UDPSegmentReceiver] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._active_freq: float | None = None
        self._callsign = cfg.aircraft.get("callsign", "")
        self._last_plan: RadioPlan | None = None
        self._last_fingerprint: tuple | None = None
        self._live_rx: LiveAudioReceiver | None = None

        self.stt = STTWorker(
            cfg.stt,
            callsign=self._callsign,
            model_dir=str(cfg.models_dir),
            on_result=self._on_transcript,
        )

    def _on_segment(self, seg: AudioSegment) -> None:
        priority = 0 if seg.role in ("active", "tower") else 5
        if self.cfg.record.enabled:
            seg.audio_ref = write_flac(
                self.cfg.archive_dir,
                freq_mhz=seg.freq_mhz,
                ts_ns=seg.ts_ns,
                pcm_f32=seg.pcm_f32,
            )
        self.stt.enqueue(seg, priority=priority)

    def _on_transcript(self, result: TranscriptResult) -> None:
        self.store.add(result)
        try:
            self.kf.push_atc_comm(self.cfg, result)
        except Exception:
            log.exception("howgozit atc_comms push")
        if (
            result.role == "atis"
            or result.duration_s >= self.cfg.stt.atis_min_duration_s
        ):
            fields = parse_atis(result.text)
            vals = atis_to_howgozit_values(fields)
            if len(vals) >= 3:
                try:
                    self.kf.push_atis(self.cfg, result.ts_ns, vals)
                except Exception:
                    log.exception("howgozit atis push")

    def _active_freq_mhz(self) -> float | None:
        if not self.cfg.planner.include_active_com:
            return None
        return self.kf.latest_active_freq_mhz()

    def _plan_fingerprint(self, plan: RadioPlan) -> tuple:
        dbg = self.cfg.debug
        return (
            plan.mode,
            tuple(
                (round(ch.freq_mhz, 3), ch.udp_port, ch.label, ch.role)
                for ch in plan.channels
            ),
            dbg.live_audio,
            dbg.live_audio_port,
            dbg.live_audio_continuous,
        )

    def _mirror_live(self) -> bool:
        dbg = self.cfg.debug
        return bool(dbg.live_audio and not dbg.live_audio_continuous)

    def _sync_live_audio(self) -> None:
        dbg = self.cfg.debug
        if dbg.live_audio and dbg.live_audio_continuous:
            if self._live_rx is None:
                self._live_rx = LiveAudioReceiver(dbg.live_audio_port)
                self._live_rx.start()
        elif self._live_rx is not None:
            self._live_rx.stop()
            self._live_rx = None

    def _start_receivers(self, plan: RadioPlan) -> None:
        mirror = self._mirror_live()
        if plan.is_scan:
            rx = UDPSegmentReceiver(
                plan.channels[0].udp_port,
                0.0,
                "SCAN",
                "scan",
                lambda seg: self._on_segment(self._tag_scan_segment(seg, plan)),
                min_segment_s=self.cfg.stt.min_segment_s,
                max_segment_s=self.cfg.stt.max_segment_s,
                mirror_live=mirror,
            )
            rx.start()
            self._receivers.append(rx)
        else:
            for p in plan.channels:
                rx = UDPSegmentReceiver(
                    p.udp_port,
                    p.freq_mhz,
                    p.label,
                    p.role,
                    self._on_segment,
                    min_segment_s=self.cfg.stt.min_segment_s,
                    max_segment_s=self.cfg.stt.max_segment_s,
                    mirror_live=mirror,
                )
                rx.start()
                self._receivers.append(rx)

    def _apply_plan(self) -> None:
        gps = self.kf.fetch_gps()
        cs = self.kf.fetch_aircraft()
        if cs:
            self._callsign = cs
            self.stt._callsign = cs

        self._active_freq = self._active_freq_mhz()
        plan = plan_channels(
            self.cfg,
            active_freq_mhz=self._active_freq,
            gps=gps,
        )
        fp = self._plan_fingerprint(plan)
        plan_changed = fp != self._last_fingerprint
        if not plan_changed and self.sdr.running:
            self._last_plan = plan
            self._sync_live_audio()
            return

        self._last_fingerprint = fp
        self._last_plan = plan

        if plan_changed:
            self._stop_receivers()

        if plan_changed or not self.sdr.running:
            self.sdr.start(plan)

        self.store.set_sdr_running(self.sdr.running, self.sdr.last_error)
        ch_status = [
            ChannelStatus(
                freq_mhz=p.freq_mhz,
                label=p.label,
                role=p.role,
                udp_port=p.udp_port,
                mode=plan.mode,
            )
            for p in plan.channels
        ]
        self.store.set_channels(ch_status, plan_mode=plan.mode)

        if plan_changed or not self._receivers:
            self._start_receivers(plan)

        self._sync_live_audio()

        log.info(
            "plan: mode=%s freqs=%d active=%s sdr_running=%s",
            plan.mode,
            len(plan.channels),
            self._active_freq,
            self.sdr.running,
        )

    def _tag_scan_segment(self, seg: AudioSegment, plan: RadioPlan) -> AudioSegment:
        # Scan mode does not tag frequency in the UDP stream; keep audio, label as scan.
        seg.label = "SCAN"
        seg.role = "scan"
        return seg

    def _monitored_freqs(self) -> set[float]:
        if not self._last_plan:
            return set()
        return {round(ch.freq_mhz, 3) for ch in self._last_plan.channels}

    def _catalog_unlocked(self) -> dict:
        monitored = self._monitored_freqs()
        pl = self.cfg.planner
        active_key: float | None = None
        if self._active_freq and self._active_freq > 0:
            active_key = round(self._active_freq, 3)
        active_via_hgz = bool(pl.include_active_com and active_key is not None)

        channels: list[dict] = []
        static_keys: set[float] = set()
        for ch in self.cfg.channels:
            freq_key = round(ch.freq_mhz, 3)
            static_keys.add(freq_key)
            via_hgz = active_via_hgz and freq_key == active_key
            is_monitored = freq_key in monitored
            sources: list[str] = []
            if ch.enabled:
                sources.append("static")
            if via_hgz:
                sources.append("howgozit")
            channels.append(
                {
                    "freq_mhz": ch.freq_mhz,
                    "label": ch.label,
                    "role": ch.role,
                    "enabled": ch.enabled,
                    "monitored": is_monitored,
                    "active": is_monitored,
                    "via_howgozit": via_hgz,
                    "sources": sources,
                    "source": "static",
                }
            )

        # Howgozit COM not in static config — show as its own monitor chip.
        if active_via_hgz and active_key is not None and active_key not in static_keys:
            channels.append(
                {
                    "freq_mhz": self._active_freq,
                    "label": "ACTIVE COM",
                    "role": "active",
                    "enabled": False,
                    "monitored": active_key in monitored,
                    "active": active_key in monitored,
                    "via_howgozit": True,
                    "sources": ["howgozit"],
                    "source": "howgozit",
                }
            )

        auto: list[dict] = []
        if active_via_hgz and active_key is not None:
            matched = next(
                (c for c in self.cfg.channels if round(c.freq_mhz, 3) == active_key),
                None,
            )
            auto.append(
                {
                    "freq_mhz": self._active_freq,
                    "label": "ACTIVE COM",
                    "matched_static_label": matched.label if matched else None,
                    "role": "active",
                    "monitored": active_key in monitored,
                    "source": "howgozit",
                }
            )
        return {
            "plan_mode": self.store.health().get("plan_mode", ""),
            "planner": {
                "include_gps_airport": pl.include_gps_airport,
                "include_active_com": pl.include_active_com,
            },
            "channels": channels,
            "auto": auto,
            "debug": {
                "live_audio": self.cfg.debug.live_audio,
                "live_audio_continuous": self.cfg.debug.live_audio_continuous,
            },
        }

    def channel_catalog(self) -> dict:
        with self._lock:
            return self._catalog_unlocked()

    def set_channel_enabled(self, freq_mhz: float, enabled: bool) -> dict:
        with self._lock:
            target = None
            for ch in self.cfg.channels:
                if round(ch.freq_mhz, 3) == round(freq_mhz, 3):
                    target = ch
                    break
            if target is None:
                raise KeyError(f"unknown channel {freq_mhz} MHz")
            if not enabled:
                enabled_count = sum(1 for c in self.cfg.channels if c.enabled)
                if target.enabled and enabled_count <= 1:
                    raise ValueError("at least one static channel must stay enabled")
            target.enabled = enabled
            try:
                persist_runtime_prefs(self.config_path, self.cfg)
            except OSError as e:
                log.warning("could not persist config: %s", e)
        self._apply_plan()
        with self._lock:
            return self._catalog_unlocked()

    def set_planner(
        self,
        *,
        include_gps_airport: bool | None = None,
        include_active_com: bool | None = None,
    ) -> dict:
        with self._lock:
            if include_gps_airport is not None:
                self.cfg.planner.include_gps_airport = include_gps_airport
            if include_active_com is not None:
                self.cfg.planner.include_active_com = include_active_com
            try:
                persist_runtime_prefs(self.config_path, self.cfg)
            except OSError as e:
                log.warning("could not persist config: %s", e)
        self._apply_plan()
        with self._lock:
            return self._catalog_unlocked()

    def set_live_audio(self, enabled: bool) -> dict:
        with self._lock:
            self.cfg.debug.live_audio = enabled
            try:
                persist_runtime_prefs(self.config_path, self.cfg)
            except OSError as e:
                log.warning("could not persist config: %s", e)
        self._last_fingerprint = None
        self._apply_plan()
        with self._lock:
            return self._catalog_unlocked()

    def _stop_receivers(self) -> None:
        for rx in self._receivers:
            rx.stop()
        self._receivers.clear()

    def _poll_kingfisher(self) -> None:
        while not self._stop.is_set():
            try:
                if self.cfg.sdr.enabled and not self.sdr.running:
                    log.warning("rtl_airband not running — restarting")
                    self._apply_plan()
                gps = self.kf.fetch_gps()
                self.store.set_kingfisher_ok(gps.has_fix or True)
                freq = self._active_freq_mhz()
                if freq != self._active_freq:
                    log.info("active COM changed: %s -> %s", self._active_freq, freq)
                    self._active_freq = freq
                    self._apply_plan()
            except Exception:
                self.store.set_kingfisher_ok(False)
            self._stop.wait(self.cfg.kingfisher.poll_interval_s)

    def start_background(self) -> None:
        self.store.set_stt_ready(self.stt.ready)
        self.stt.start()
        self._apply_plan()
        threading.Thread(target=self._poll_kingfisher, name="kf-poll", daemon=True).start()

    def shutdown(self) -> None:
        self._stop.set()
        self._stop_receivers()
        if self._live_rx is not None:
            self._live_rx.stop()
            self._live_rx = None
        self.sdr.stop()
        self.stt.stop()


def download_model_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download kingfisher-airband STT model")
    p.add_argument("-c", "--config", type=Path, default=default_config_path())
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.config.is_file():
        log.error("config not found: %s", args.config)
        return 1

    cfg = load_config(args.config)
    try:
        download_model_assets(cfg.stt, cfg.models_dir)
    except Exception:
        log.exception("model download failed")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="kingfisher-airband ATC monitor")
    p.add_argument("-c", "--config", type=Path, default=default_config_path())
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.config.is_file():
        log.error("config not found: %s (copy config.example.yaml)", args.config)
        return 1

    cfg = load_config(args.config)

    try:
        model_path = verify_model_ready(cfg.stt, cfg.models_dir)
        log.info("STT model cached at %s", model_path)
    except ModelNotReadyError as e:
        log.error("%s", e)
        return 1

    daemon = Daemon(cfg, args.config)

    if cfg.stt.preload_at_startup:
        try:
            daemon.stt.preload()
            daemon.store.set_stt_ready(True)
        except Exception:
            log.exception("STT preload failed")
            daemon.store.set_stt_ready(False, "preload failed")
            return 1

    web_dir = Path(__file__).resolve().parent.parent / "web"
    app = create_app(daemon, cfg.archive_dir, web_dir)

    host, port_str = cfg.http_addr.rsplit(":", 1)
    port = int(port_str)

    def handle_sig(*_args: object) -> None:
        log.info("shutting down")
        daemon.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    daemon.start_background()
    log.info("HTTP on %s", cfg.http_addr)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
