"""Kingfisher REST client for howgozit and GPS status."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from airband.config import Config, HowgozitCfg
from airband.planner.channels import GPSFix

log = logging.getLogger(__name__)


class KingfisherClient:
    def __init__(self, cfg: Config) -> None:
        self._base = cfg.kingfisher.base_url.rstrip("/")
        self._hgz: HowgozitCfg = cfg.howgozit
        self._timeout = httpx.Timeout(5.0)
        self._log_ids: dict[str, str] = {}

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self._base, timeout=self._timeout)

    def fetch_gps(self) -> GPSFix:
        try:
            with self._client() as c:
                r = c.get("/api/status")
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            log.debug("kingfisher status: %s", e)
            return GPSFix(0, 0, has_fix=False)
        gps = data.get("gps") or {}
        if not gps.get("has_fix"):
            return GPSFix(0, 0, has_fix=False)
        speed = 0.0
        # gs not always in status; default 0
        return GPSFix(
            lat=float(gps.get("lat", 0)),
            lon=float(gps.get("lon", 0)),
            speed_m_s=speed,
            has_fix=True,
        )

    def fetch_aircraft(self) -> str:
        try:
            with self._client() as c:
                r = c.get("/api/status")
                r.raise_for_status()
                data = r.json()
                return str(data.get("aircraft") or "")
        except Exception:
            return ""

    def _resolve_log_id(self, template_id: str, pinned: str) -> str | None:
        if pinned:
            return pinned
        if template_id in self._log_ids:
            return self._log_ids[template_id]
        try:
            with self._client() as c:
                r = c.get("/api/howgozit/logs")
                r.raise_for_status()
                logs = r.json().get("logs") or []
        except Exception as e:
            log.debug("howgozit list logs: %s", e)
            return None
        for lg in logs:
            if lg.get("template_id") == template_id:
                lid = lg.get("log_id")
                if lid:
                    self._log_ids[template_id] = lid
                    return lid
        return None

    def ensure_log(self, template_id: str, name: str) -> str | None:
        lid = self._resolve_log_id(template_id, "")
        if lid:
            return lid
        try:
            with self._client() as c:
                r = c.post("/api/howgozit/logs", json={"template_id": template_id})
                if r.status_code == 409:
                    return self._resolve_log_id(template_id, "")
                r.raise_for_status()
                meta = r.json()
                lid = meta.get("log_id")
                if lid:
                    self._log_ids[template_id] = lid
                return lid
        except Exception as e:
            log.warning("ensure_log %s: %s", template_id, e)
            return None

    def insert_row(self, log_id: str, ts_ns: int, values: dict[str, str]) -> bool:
        try:
            with self._client() as c:
                r = c.post(
                    f"/api/howgozit/logs/{log_id}/rows",
                    json={"ts_ns": ts_ns, "values": values},
                )
                r.raise_for_status()
            return True
        except Exception as e:
            log.warning("insert_row %s: %s", log_id, e)
            return False

    def latest_active_freq_mhz(self) -> float | None:
        lid = self._resolve_log_id("atc_radio", self._hgz.atc_radio_log_id)
        if not lid:
            return None
        try:
            with self._client() as c:
                r = c.get(f"/api/howgozit/logs/{lid}/rows")
                r.raise_for_status()
                rows = r.json().get("rows") or []
        except Exception as e:
            log.debug("atc_radio rows: %s", e)
            return None
        for row in reversed(rows):
            vals = row.get("values") or {}
            f = vals.get("freq_mhz")
            if f is not None and str(f).strip():
                try:
                    return float(f)
                except ValueError:
                    continue
        return None

    def push_atc_comm(self, cfg: Config, result: Any) -> None:
        lid = self._resolve_log_id("atc_comms", cfg.howgozit.atc_comms_log_id)
        if not lid:
            lid = self.ensure_log("atc_comms", "ATC Comms")
        if not lid:
            return
        values = {
            "freq_mhz": f"{result.freq_mhz:.3f}",
            "facility": result.label,
            "transcript": result.text,
            "confidence": f"{result.confidence:.3f}",
            "direction": result.direction,
        }
        if result.audio_ref:
            values["audio_ref"] = result.audio_ref
        self.insert_row(lid, result.ts_ns, values)

    def push_atis(self, cfg: Config, ts_ns: int, values: dict[str, str]) -> None:
        lid = self._resolve_log_id("atis", cfg.howgozit.atis_log_id)
        if not lid:
            lid = self.ensure_log("atis", "ATIS")
        if not lid:
            return
        self.insert_row(lid, ts_ns, values)
