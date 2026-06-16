# kingfisher-airband

Offline VHF airband monitor for the Kingfisher Pi: RTLSDR-Airband demodulates AM
tower/ground/ATIS channels, faster-whisper transcribes squelch-open segments, and
results appear in a local web UI (and optionally in Kingfisher howgozit logs).

**Transcription is advisory only** — always verify altitudes, headings, and
frequencies by ear.

---

## What you need

| Item | Notes |
|------|--------|
| Raspberry Pi 5 (8 GB recommended) | Runs alongside Kingfisher; STT is CPU-heavy |
| NooElec SMArt v5 (or compatible RTL-SDR) | TCXO dongle; no transmit capability |
| VHF airband antenna | Outside the cabin if possible; pigtail to SMA on the dongle |
| Kingfisher (optional) | GPS + howgozit integration; not required for the transcript UI |

Software (installed below): `librtlsdr`, [RTLSDR-Airband](https://github.com/rtl-airband/RTLSDR-Airband), [uv](https://docs.astral.sh/uv/), Python 3.11+.

---

## End-to-end setup

### 1. Install the dongle (hardware)

1. **Mount the antenna** where it can hear the airport(s) you care about. A wing
   root or external mount beats a dongle sitting in the cabin, but any antenna is
   better than the stub included with some kits.
2. **Connect antenna → dongle** (SMA). Do not power the Pi yet if you are still
   wiring.
3. **Plug the dongle into a Pi USB port** — prefer a direct port on the Pi 5, not
   a busy hub shared with other high-bandwidth devices.
4. Boot the Pi and confirm USB detection:

   ```bash
   lsusb | grep -iE 'rtl|realtek|0bda'
   # Typical: ID 0bda:2838 Realtek Semiconductor Corp. RTL2838 DVB-T ...
   ```

5. **Blacklist the DVB-T kernel driver** (if not already done on your image) so
   the SDR is not grabbed by TV software:

   ```bash
   echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/no-rtl.conf
   sudo modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true
   ```

### 2. Install system packages

On Raspberry Pi OS / Debian:

```bash
sudo apt update
sudo apt install -y \
  build-essential cmake git pkg-config \
  librtlsdr-dev rtl-sdr \
  libshout3-dev libmp3lame-dev libfftw3-dev \
  libconfig++-dev libpulse-dev \
  libsoapysdr-dev
```

Add your user to the `plugdev` group (needed for USB access without root):

```bash
sudo usermod -aG plugdev "$USER"
# Log out and back in (or reboot) before continuing
```

### 3. Install RTLSDR-Airband

RTLSDR-Airband demodulates airband AM and sends per-channel audio over UDP to
this daemon.

```bash
git clone https://github.com/rtl-airband/RTLSDR-Airband.git /tmp/RTLSDR-Airband
cd /tmp/RTLSDR-Airband
mkdir build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=/usr/local
make -j"$(nproc)"
sudo make install
which rtl_airband   # expect /usr/local/bin/rtl_airband
```

Quick dongle check:

```bash
rtl_test -t
# Should run ~5 s without "Failed to open rtlsdr device"
```

Optional spike script (writes test config, tries UDP capture for 15 s):

```bash
chmod +x scripts/spike_sdr.sh
./scripts/spike_sdr.sh
# Artifacts in /tmp/kingfisher-airband-spike/
```

### 4. Deploy udev rules (`deploy/99-rtl-sdr.rules`)

This file gives your user group access to the dongle and creates a stable
symlink `/dev/rtl_sdr`:

| File | Purpose |
|------|---------|
| `deploy/99-rtl-sdr.rules` | udev: `MODE=0664`, `GROUP=plugdev`, symlink `rtl_sdr` for Realtek 2832/2838 |
| `deploy/airband.service` | systemd unit to start the daemon at boot (see step 8) |

Install the udev rule:

```bash
sudo cp deploy/99-rtl-sdr.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
# Re-plug the dongle, then:
ls -l /dev/rtl_sdr
```

You should see `/dev/rtl_sdr` → `bus/usb/...` and your user in group `plugdev`.

### 5. Install uv and Python dependencies

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Clone this repo and sync the environment:

```bash
cd ~/go/src/github.com/westphae/kingfisher-airband   # or your clone path
uv sync
```

First `uv run airband` will download the ATC fine-tuned Whisper model (~hundreds
of MB) into `~/.local/share/kingfisher-airband/models/` (via Hugging Face cache).

### 6. Configure channels and Kingfisher URL

```bash
mkdir -p ~/.config/kingfisher-airband
cp config.example.yaml ~/.config/kingfisher-airband/config.yaml
```

Edit `~/.config/kingfisher-airband/config.yaml`:

1. **`channels`** — set frequencies you can actually hear (MHz). Example file
   defaults to KSBA tower/ground/ATIS. Change labels and freqs for your home
   airport; add entries to `data/airports/frequencies.json` for GPS-based
   planning near other fields.
2. **`kingfisher.base_url`** — URL of the running Kingfisher cockpit
   (default `http://127.0.0.1:8080`). If Kingfisher is not running, transcripts
   still work; howgozit inserts are skipped.
3. **`aircraft.callsign`** — your N-number (used for pilot vs ATC heuristic).
4. **`sdr.gain`** — start at `25`; raise if weak signal, lower if overload
   (breaks squelch).
5. **`sdr.rtl_airband_bin`** — path from `which rtl_airband` if not
   `/usr/local/bin/rtl_airband`.

To run **without a dongle** (STT/API/UI dev only): set `sdr.enabled: false`.

### 7. First run — live transcripts in the browser

Start Kingfisher first if you want GPS/howgozit integration (optional):

```bash
# In kingfisher repo, if you use it:
go run ./cmd/kingfisher
```

Start airband in the foreground to watch logs:

```bash
cd kingfisher-airband
uv run airband -c ~/.config/kingfisher-airband/config.yaml
```

On first start expect:

- `loading STT model ...` (one-time; may take 1–2 minutes on Pi 5)
- `started rtl_airband pid=...` when the dongle is present
- `UDP ingest listening on :7356 ...` per configured channel

Open the transcript UI on the Pi or from a tablet on the same LAN:

```
http://127.0.0.1:7355/
```

The page polls every 2 s. When someone transmits on a watched frequency and
squelch opens, you should see a card within **roughly 5–20 s after the
transmission ends** (STT runs on squelch-closed segments, not live streaming
text).

Each card shows time (UTC), channel label, frequency, direction heuristic
(`atc` / `pilot` / `unknown`), and transcript text. **Play** replays the FLAC
segment if recording is enabled.

Health check without the UI:

```bash
curl -s http://127.0.0.1:7355/api/health | python3 -m json.tool
curl -s 'http://127.0.0.1:7355/api/transcripts?since=0' | python3 -m json.tool
```

### 8. Install systemd service (`deploy/airband.service`)

For boot-time operation, edit the unit file **before** installing — paths and
user are site-specific:

```bash
# Review and adjust User=, WorkingDirectory=, ExecStart= uv path, config path
nano deploy/airband.service
```

Default values assume user `eric` and repo at
`/home/eric/go/src/github.com/westphae/kingfisher-airband`. Change `User=` and
`Group=plugdev` to your Pi login.

Install and enable:

```bash
sudo cp deploy/airband.service /etc/systemd/system/kingfisher-airband.service
sudo systemctl daemon-reload
sudo systemctl enable --now kingfisher-airband.service
sudo systemctl status kingfisher-airband.service
journalctl -u kingfisher-airband.service -f
```

The unit sets `After=kingfisher.service`, `Nice=5`, and `CPUQuota=70%` so STT
does not starve the flight recorder. Restart after config changes:

```bash
sudo systemctl restart kingfisher-airband.service
```

---

## How it works (short)

```
RTL-SDR dongle
  → rtl_airband (AM demod, multichannel or scan)
  → UDP PCM per channel (localhost)
  → VAD / segment assembly
  → faster-whisper (jacktol ATC model, CPU int8)
  → lexicon post-process
  → HTTP API + web UI (+ optional howgozit rows)
```

One dongle covers ~2.4 MHz simultaneously. Channels farther apart than that are
time-shared (scan mode). A second dongle removes that compromise.

---

## Kingfisher integration (optional)

When Kingfisher is running, airband:

- Polls `GET /api/status` for GPS position and aircraft callsign
- Polls howgozit **ATC Radio** log for the latest `freq_mhz` (active COM)
- Inserts transcript rows into **ATC Comms** and parsed ATIS into **ATIS** logs

Pilot workflow in the Kingfisher cockpit:

1. **+ Log** → create **ATC Comms** and **ATIS** logs (once per flight)
2. Log frequency changes in **ATC Radio** as you switch COM — airband prioritizes
   that frequency in the channel planner

Requires Kingfisher templates `atc_comms` / `atis` (added in a future Kingfisher
release if not present yet).

---

## Troubleshooting

| Symptom | Things to check |
|---------|-------------------|
| `Failed to open rtlsdr device` | udev rule installed? user in `plugdev`? re-login after `usermod`. Blacklist DVB driver. |
| No `/dev/rtl_sdr` | Re-plug dongle; `sudo udevadm trigger`. |
| `rtl_airband not found` | Build/install RTLSDR-Airband; set `sdr.rtl_airband_bin` in config. |
| UI loads but no transcripts | Traffic on configured freqs? Lower squelch via gain tuning. Check `journalctl -u kingfisher-airband`. |
| UDP capture empty in spike | Normal if no transmissions during the 15 s window; try a busy frequency or live ATIS cycle. |
| STT very slow | Expected on Pi CPU for `medium` model; first model load is slow. Segments queue; active COM channel is prioritized. |
| `kingfisher_ok: false` in `/api/health` | Kingfisher not running or wrong `base_url` — transcripts still work locally. |

STT-only test on a saved WAV:

```bash
uv run python scripts/spike_stt.py /path/to/sample.wav
```

---

## Development

```bash
uv sync --group dev
uv run pytest
```

---

## Safety and legal

Receiving airband is generally permitted in the US for monitoring; do not
rebroadcast audio. Recordings are for personal flight logs. AI transcription
makes mistakes — never rely on it for clearances without readback.
