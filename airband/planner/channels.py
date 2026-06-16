"""Frequency planner: static + GPS airport + howgozit active COM."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from airband.config import ChannelCfg, Config, PlannerCfg


@dataclass
class PlannedChannel:
    freq_mhz: float
    label: str
    role: str
    udp_port: int
    mode: str  # multichannel | scan


@dataclass
class GPSFix:
    lat: float
    lon: float
    speed_m_s: float = 0.0
    has_fix: bool = False


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3440.065  # earth radius nm
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_airports(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open() as f:
        return json.load(f)


def nearest_airport(lat: float, lon: float, airports: list[dict]) -> dict | None:
    best = None
    best_d = 1e9
    for ap in airports:
        d = _haversine_nm(lat, lon, ap["lat"], ap["lon"])
        if d < best_d:
            best_d = d
            best = ap
    if best is None or best_d > 50:
        return None
    return best


def channels_from_airport(ap: dict) -> list[ChannelCfg]:
    out: list[ChannelCfg] = []
    icao = ap.get("icao", "")
    for f in ap.get("frequencies", []):
        role = f.get("role", "comms")
        label = f.get("label") or f"{icao} {role.upper()}"
        out.append(ChannelCfg(freq_mhz=float(f["freq_mhz"]), label=label, role=role))
    return out


def merge_channels(*groups: list[ChannelCfg]) -> list[ChannelCfg]:
    seen: dict[float, ChannelCfg] = {}
    for g in groups:
        for ch in g:
            key = round(ch.freq_mhz, 3)
            if key not in seen:
                seen[key] = ch
    return sorted(seen.values(), key=lambda c: c.freq_mhz)


def plan_channels(
    cfg: Config,
    *,
    active_freq_mhz: float | None = None,
    gps: GPSFix | None = None,
    airports_path: Path | None = None,
) -> list[PlannedChannel]:
    """Build receive plan with UDP port assignments."""
    static = list(cfg.channels)
    dynamic: list[ChannelCfg] = []

    ap_path = airports_path or cfg.airports_path
    airports = load_airports(ap_path)
    if gps and gps.has_fix and airports:
        ap = nearest_airport(gps.lat, gps.lon, airports)
        if ap:
            dynamic.extend(channels_from_airport(ap))

    if active_freq_mhz and active_freq_mhz > 0:
        dynamic.append(
            ChannelCfg(freq_mhz=active_freq_mhz, label="ACTIVE COM", role="active")
        )

    merged = merge_channels(static, dynamic)
    if not merged:
        merged = [ChannelCfg(freq_mhz=121.5, label="GUARD", role="comms")]

    span = merged[-1].freq_mhz - merged[0].freq_mhz
    pl: PlannerCfg = cfg.planner
    use_multichannel = span <= pl.multichannel_max_span_mhz and len(merged) > 1

    # On ground: prefer tower+ground if in list
    on_ground = gps and gps.has_fix and (gps.speed_m_s * 1.94384) < pl.ground_speed_max_kt

    planned: list[PlannedChannel] = []
    for i, ch in enumerate(merged):
        mode = "multichannel" if use_multichannel else "scan"
        if not use_multichannel and on_ground and ch.role in ("tower", "ground", "active"):
            mode = "scan"
        planned.append(
            PlannedChannel(
                freq_mhz=ch.freq_mhz,
                label=ch.label or f"{ch.freq_mhz:.3f} MHz",
                role=ch.role,
                udp_port=cfg.udp_base_port + i,
                mode=mode,
            )
        )
    return planned
