"""Parse ATIS fields from transcribed text."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ATISFields:
    airport: str = ""
    information: str = ""
    time_z: str = ""
    wind: str = ""
    visibility_sm: str = ""
    weather: str = ""
    sky: str = ""
    temperature_c: str = ""
    dewpoint_c: str = ""
    altimeter_inhg: str = ""
    remark: str = ""
    raw: str = ""


_RE_INFO = re.compile(r"\bINFORMATION\s+([A-Z]+)\b", re.I)
_RE_TIME = re.compile(r"\b(\d{4})\s*Z\b")
_RE_WIND = re.compile(r"\b(\d{3}\d{2,3}G?\d{0,3}KT)\b", re.I)
_RE_VIS = re.compile(r"\b(\d+)\s*SM\b", re.I)
_RE_ALT = re.compile(r"\bALTIMETER\s+(\d{4})\b", re.I)
_RE_TEMP = re.compile(r"\bTEMPERATURE\s+(\d+)\b", re.I)
_RE_DEW = re.compile(r"\bDEW\s*POINT\s+(\d+)\b", re.I)
_RE_AIRPORT = re.compile(r"\b([A-Z]{4})\s+(?:AIRPORT|ATIS|ARRIVAL|DEPARTURE)\b")

_INFO_PHONETIC = {
    "ALPHA": "A",
    "BRAVO": "B",
    "CHARLIE": "C",
    "DELTA": "D",
    "ECHO": "E",
    "FOXTROT": "F",
    "GOLF": "G",
    "HOTEL": "H",
    "INDIA": "I",
    "JULIET": "J",
    "KILO": "K",
    "LIMA": "L",
    "MIKE": "M",
    "NOVEMBER": "N",
    "OSCAR": "O",
    "PAPA": "P",
    "QUEBEC": "Q",
    "ROMEO": "R",
    "SIERRA": "S",
    "TANGO": "T",
    "UNIFORM": "U",
    "VICTOR": "V",
    "WHISKEY": "W",
    "XRAY": "X",
    "YANKEE": "Y",
    "ZULU": "Z",
}


def _info_letter(token: str) -> str:
    t = token.upper()
    if len(t) == 1:
        return t
    return _INFO_PHONETIC.get(t, t[:1])


def parse_atis(text: str, *, default_airport: str = "") -> ATISFields:
    raw = text.strip()
    f = ATISFields(raw=raw)
    m = _RE_AIRPORT.search(raw)
    f.airport = (m.group(1) if m else default_airport).upper()
    m = _RE_INFO.search(raw)
    if m:
        f.information = _info_letter(m.group(1))
    m = _RE_TIME.search(raw)
    if m:
        f.time_z = m.group(1)
    m = _RE_WIND.search(raw)
    if m:
        f.wind = m.group(1).upper()
    m = _RE_VIS.search(raw)
    if m:
        f.visibility_sm = m.group(1)
    m = _RE_ALT.search(raw)
    if m:
        # 3012 → 30.12
        a = m.group(1)
        f.altimeter_inhg = f"{a[:2]}.{a[2:]}"
    m = _RE_TEMP.search(raw)
    if m:
        f.temperature_c = m.group(1)
    m = _RE_DEW.search(raw)
    if m:
        f.dewpoint_c = m.group(1)
    # Weather / sky: grab between wind and temp loosely
    if "CEILING" in raw.upper() or "SKY" in raw.upper() or "BROKEN" in raw.upper() or "FEW" in raw.upper():
        sky_m = re.search(r"\b((?:FEW|SCT|BKN|OVC)\d{3}(?:\s+(?:FEW|SCT|BKN|OVC)\d{3})*)\b", raw, re.I)
        if sky_m:
            f.sky = sky_m.group(1).upper()
    wx_m = re.search(r"\b((?:CLR|SKC|RA|SN|TS|FG|BR|HZ|FU)[A-Z0-9\s]*)\b", raw, re.I)
    if wx_m and not f.sky:
        f.weather = wx_m.group(1).upper()[:64]
    return f


def atis_to_howgozit_values(fields: ATISFields) -> dict[str, str]:
    out: dict[str, str] = {}
    if fields.airport:
        out["airport"] = fields.airport
    if fields.information:
        out["information"] = fields.information
    if fields.time_z:
        out["time"] = fields.time_z
    if fields.wind:
        out["wind"] = fields.wind
    if fields.visibility_sm:
        out["visibility"] = fields.visibility_sm
    if fields.weather:
        out["weather"] = fields.weather
    if fields.sky:
        out["sky"] = fields.sky
    if fields.temperature_c:
        out["temperature"] = fields.temperature_c
    if fields.dewpoint_c:
        out["dewpoint"] = fields.dewpoint_c
    if fields.altimeter_inhg:
        out["altimeter"] = fields.altimeter_inhg
    if fields.remark:
        out["rmk"] = fields.remark
    return out
