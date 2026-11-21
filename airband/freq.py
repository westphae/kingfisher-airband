"""Aviation VHF airband frequency helpers."""

from __future__ import annotations

# Civil COM band (118.000–136.975 MHz); covers guard at 121.5.
AIRBAND_MHZ_MIN = 118.0
AIRBAND_MHZ_MAX = 137.0

_HOWGOZIT_SCALERS = (1, 10, 100, 1000)


def is_valid_airband_mhz(freq: float) -> bool:
    return AIRBAND_MHZ_MIN <= freq <= AIRBAND_MHZ_MAX


def normalize_howgozit_freq_mhz(raw: float | str | None) -> float | None:
    """Return MHz if *raw* is already valid or scales to a civil airband COM freq.

    Howgozit pilots sometimes omit the decimal (e.g. 11970 instead of 119.7).
    Try the raw value, then divide by 10, 100, and 1000.
    """
    if raw is None:
        return None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    for scale in _HOWGOZIT_SCALERS:
        candidate = value / scale
        if is_valid_airband_mhz(candidate):
            return round(candidate, 3)
    return None
