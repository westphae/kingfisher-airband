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
from airband.config import Config, default_config_path, load_config
from airband.ingest.udp import AudioSegment, UDPSegmentReceiver
from airband.kingfisher.client import KingfisherClient
from airband.planner.channels import RadioPlan, plan_channels
from airband.record.flac import write_flac
from airband.sdr.rtl_airband import RTLAirbandProcess
from airband.stt.worker import STTWorker, TranscriptResult

log = logging.getLogger(__name__)


class Daemon:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.store = TranscriptStore()
        self.kf = KingfisherClient(cfg)
        self.sdr = RTLAirbandProcess(cfg)
        self._receivers: list[UDPSegmentReceiver] = []
        self._stop = threading.Event()
        self._active_freq: float | None = None
        self._callsign = cfg.aircraft.get("callsign", "")

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

    def _apply_plan(self) -> None:
        gps = self.kf.fetch_gps()
        cs = self.kf.fetch_aircraft()
        if cs:
            self._callsign = cs
            self.stt._callsign = cs
        self._active_freq = self.kf.latest_active_freq_mhz()
        plan = plan_channels(
            self.cfg,
            active_freq_mhz=self._active_freq,
            gps=gps,
        )
        self._stop_receivers()
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
        self.store.set_channels(ch_status)
        if plan.is_scan:
            rx = UDPSegmentReceiver(
                plan.channels[0].udp_port,
                0.0,
                "SCAN",
                "scan",
                lambda seg: self._on_segment(self._tag_scan_segment(seg, plan)),
                min_segment_s=self.cfg.stt.min_segment_s,
                max_segment_s=self.cfg.stt.max_segment_s,
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
                )
                rx.start()
                self._receivers.append(rx)
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
                freq = self.kf.latest_active_freq_mhz()
                if freq != self._active_freq:
                    log.info("active COM changed: %s -> %s", self._active_freq, freq)
                    self._active_freq = freq
                    self._apply_plan()
            except Exception:
                self.store.set_kingfisher_ok(False)
            self._stop.wait(self.cfg.kingfisher.poll_interval_s)

    def start_background(self) -> None:
        self.stt.start()
        self._apply_plan()
        threading.Thread(target=self._poll_kingfisher, name="kf-poll", daemon=True).start()

    def shutdown(self) -> None:
        self._stop.set()
        self._stop_receivers()
        self.sdr.stop()
        self.stt.stop()


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
    daemon = Daemon(cfg)

    web_dir = Path(__file__).resolve().parent.parent / "web"
    app = create_app(daemon.store, cfg.archive_dir, web_dir)

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
