# kingfisher-airband

Offline VHF airband monitor for the Kingfisher Pi: RTLSDR-Airband demod,
faster-whisper ATC transcription, FLAC archival, and howgozit integration.

## Quick start

Requires [uv](https://docs.astral.sh/uv/).

```bash
cd kingfisher-airband
uv sync

mkdir -p ~/.config/kingfisher-airband
cp config.example.yaml ~/.config/kingfisher-airband/config.yaml
# Edit channels / kingfisher.base_url

uv run airband
# UI: http://127.0.0.1:7355/
```

Development:

```bash
uv sync --group dev
uv run pytest
```

## Hardware

- NooElec SMArt v5 (or RTL-SDR Blog V3/V4)
- [RTLSDR-Airband](https://github.com/rtl-airband/RTLSDR-Airband) built and installed to `/usr/local/bin/rtl_airband`
- `librtlsdr` + udev rule in `deploy/99-rtl-sdr.rules`

## Spikes (Phase 0)

```bash
chmod +x scripts/spike_sdr.sh
./scripts/spike_sdr.sh

uv run python scripts/spike_stt.py /path/to/sample.wav
```

## Kingfisher integration

- Polls `GET /api/status` for GPS + aircraft callsign
- Polls howgozit `atc_radio` for active COM frequency
- Inserts rows into `atc_comms` and `atis` logs via `/api/howgozit/*`

Pilot workflow: create **ATC Comms** and **ATIS** logs in Howgozit (+ Log); log frequency changes in **ATC Radio**.

## Safety

Transcription is advisory only. Always verify altitudes, headings, and frequencies by ear.
