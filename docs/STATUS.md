# kingfisher-airband handoff

Last updated: 2026-11-20, 9:20 PM CST.

This note is for picking the project up after a pause. Setup steps in
[README.md](../README.md) are still the source of truth for first-time
install; this file records architecture, current machine state, and what
is left to do.

## Purpose

Airband is an ATC monitor for the Kingfisher airplane (and desk testing).
An RTL-SDR dongle and [RTLSDR-Airband](https://github.com/szpajder/RTLSDR-Airband)
demodulate VHF COM. Audio is transcribed with a fine-tuned ATC Whisper
model (`faster-whisper`). Transcripts show up in a small local web UI and
can be pushed into Howgozit. The planner can follow the nearest airport
from Kingfisher GPS and the active COM frequency from Howgozit.

Transcripts are advisory only. Clearances are verified by ear.

## Architecture

```
rtl_airband (SDR) --UDP PCM--> ingest  --> STT worker --> transcript store
                     |                      ^
                     +--> live audio hub    |
                            (debug WS)      |
Kingfisher HTTP  --> GPS + Howgozit COM ----+ planner --> rtl_airband conf
Browser  <--> FastAPI (transcripts, channel/planner/debug PATCH, /ws/live-audio)
```

| Piece | Path | Role |
| --- | --- | --- |
| Daemon | `airband/main.py` | Config, STT preload, HTTP, channel plan, SDR supervision, ingest |
| Planner | `airband/planner/channels.py` | Enabled static channels, optional GPS airport, optional Howgozit COM |
| SDR | `airband/sdr/rtl_airband.py` | Writes rtl_airband.conf (scan vs one continuous frequency) |
| Ingest | `airband/ingest/udp.py` | Squelch-gated segments for STT |
| Live audio | `airband/ingest/live.py` | Debug PCM fan-out to the browser |
| STT | `airband/stt/model.py`, `worker.py` | Offline model cache, preload, transcription |
| API / UI | `airband/api/server.py`, `web/` | Monitor page, channel toggles, live-audio debug |
| Kingfisher | `airband/kingfisher/client.py` | GPS, Howgozit `freq_mhz` (decimal-normalized), ATC log push |
| Freq helpers | `airband/freq.py` | Civil COM band check; `11970` → `119.7` |

Local config lives at `~/.config/kingfisher-airband/config.yaml` and is
**not** in git. Runtime prefs (channel `enabled`, planner source toggles,
debug live-audio) are written back to that file by the daemon. Default
data dir is `~/.local/share/kingfisher-airband/` (`models/`, recordings).

## How to run, test, and deploy on kf-pi

Repo: `~/go/src/github.com/westphae/kingfisher-airband`.

```bash
cd ~/go/src/github.com/westphae/kingfisher-airband
uv sync                 # uses the locked venv
uv run pytest           # unit tests, no SDR or model weights required
```

Download the STT model while the machine still has internet (~3 GB). The
daemon will not fetch weights in flight when `stt.local_files_only` is
true (the default):

```bash
./scripts/download-model.sh
# or: uv run airband-download-model -c ~/.config/kingfisher-airband/config.yaml
```

Manual run:

```bash
uv run airband -c ~/.config/kingfisher-airband/config.yaml
# UI: http://<kf-pi>:7355  (bind is set in config http_addr)
```

Systemd unit (repo file: `deploy/airband.service`):

- `User=eric`, `Group=plugdev`, `WorkingDirectory` is this repo
- `ExecStart=... uv run airband -c /home/eric/.config/kingfisher-airband/config.yaml`
- `After=` / `Wants=` `network-online.target`; `After=kingfisher.service`
- `Restart=on-failure`, `Nice=5`, `CPUQuota=70%`
- `WantedBy=multi-user.target` (system service, not a user unit)

Install when you actually want it running (it is **not** installed now):

```bash
sudo cp deploy/airband.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now airband.service
# logs: journalctl -u airband.service -f
```

Do not stop or restart `kingfisher.service` (the flight recorder) while
doing this. Udev rules for the dongle are in `deploy/99-rtl-sdr.rules`.

## What is done

- End-to-end receive, transcribe, and web feed, plus ATIS parsing and
  optional Howgozit push
- Offline STT: `local_files_only` default, `airband-download-model`,
  reject incomplete Hugging Face downloads, optional preload at startup
- Whisper VAD off by default (rtl_airband squelch already segments;
  VAD was stripping narrowband AM)
- Per-channel `enabled` flags and planner toggles
  (`include_gps_airport`, `include_active_com`), persisted to the YAML
  config; the UI can change them. The last enabled channel cannot be
  turned off
- A single enabled channel is tuned continuously instead of scanned
- Howgozit frequencies missing a decimal (`11970`) are normalized to MHz
- Debug live audio: extra rtl_airband UDP (continuous demod optional) and
  a WebSocket (`/ws/live-audio`) plus a browser toggle
- Example config pointed at KCXO, with most channels disabled and GPS /
  active-COM sources off, for desk testing
- Unit tests for freq helpers, model cache, API catalog/PATCH, planner,
  rtl_airband conf, ingest, Howgozit client, and daemon plan updates

## Current machine state (kf-pi, 2026-11-20, 9:20 PM CST)

- This repo's `airband` daemon is **not running** (no process, no systemd
  unit loaded). `deploy/airband.service` has not been installed under
  `/etc/systemd/system/`
- `kingfisher.service` (recorder) **is** active; leave it alone
- Local config exists at `~/.config/kingfisher-airband/config.yaml` and
  already has the new planner / STT / debug keys. That file stays private
- The model cache directory exists but is **empty**:
  `~/.local/share/kingfisher-airband/models/` (0 files). Download the
  weights with `./scripts/download-model.sh` while online before a flight
  or a real transcription run. Confirm there are no `*.incomplete` files
  after the download

## What is unfinished or easy to trip over

- Example config (and likely the live config) is in **bench mode**:
  `include_gps_airport` / `include_active_com` false, only one KCXO
  frequency enabled. Turn the planner sources back on and enable the
  frequencies you want before a flight
- Live audio is a debug aid. Continuous demod uses more CPU; it defaults
  off in the example. The UI toggle persists into config
- The RTL-SDR dongle was not re-checked in this handoff. If `rtl_test` or
  `rtl_airband` fails, start with udev group membership (`plugdev`) and
  the README troubleshooting section
- First-time model download is required now. An empty `models/` directory
  at startup is no longer acceptable when `local_files_only` is true
- The HTTP bind address is still whatever is in the local config (example
  historically used `127.0.0.1:7355`; change it to listen on the LAN or
  Tailscale if you want the UI from another machine)

## Next steps

1. Confirm the dongle still enumerates and that `eric` is in `plugdev`.
2. While online, run `./scripts/download-model.sh` and confirm there are
   no `*.incomplete` files under the models dir.
3. Edit `~/.config/kingfisher-airband/config.yaml` for flight: enable the
   needed KCXO (or other) frequencies and set `include_gps_airport` /
   `include_active_com` to true if you want auto-follow.
4. Do a desk run (`uv run airband -c …`) and check the web UI, channel
   toggles, and a known frequency.
5. When that looks right, install `deploy/airband.service` and enable it.
   Do not touch `kingfisher.service`.
6. Flight-test: transcripts, Howgozit COM follow (including values like
   `11970`), ATIS parse, and no attempt to download the model in the air.
7. Decide whether `config.example.yaml` should stay KCXO/bench-oriented
   or return to a more generic template.

## Safety and legal

See the README. This is not a substitute for listening to the radio.
Radio reception must follow local law.
