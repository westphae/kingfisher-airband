#!/usr/bin/env bash
# Phase 0 spike: validate RTL-SDR dongle + rtl_airband multichannel UDP capture.
set -euo pipefail

SPIKE_DIR="${SPIKE_DIR:-/tmp/kingfisher-airband-spike}"
FREQ_MHZ="${FREQ_MHZ:-119.7}"
UDP_PORT="${UDP_PORT:-7356}"
GAIN="${GAIN:-25}"
RTL_AIRBAND="${RTL_AIRBAND:-/usr/local/bin/rtl_airband}"

mkdir -p "$SPIKE_DIR"

echo "== kingfisher-airband spike_sdr =="
echo "Output dir: $SPIKE_DIR"

if ! command -v rtl_test >/dev/null 2>&1; then
  echo "WARN: rtl_test not found — install librtlsdr (apt install rtl-sdr)"
else
  echo "-- rtl_test (5s) --"
  timeout 6 rtl_test -t 2>&1 | tee "$SPIKE_DIR/rtl_test.log" || true
fi

if ! lsusb 2>/dev/null | grep -qiE 'rtl|noeelec|realtek|0bda'; then
  echo "WARN: no RTL-SDR USB device detected — plug in NooElec SMArt v5 and re-run"
fi

if [[ ! -x "$RTL_AIRBAND" ]]; then
  echo "WARN: rtl_airband not at $RTL_AIRBAND — build from https://github.com/rtl-airband/RTLSDR-Airband"
  echo "Skipping live capture; spike config written to $SPIKE_DIR/rtl_airband.conf"
fi

CONF="$SPIKE_DIR/rtl_airband.conf"
CENTER=$(python3 -c "print(f'{$FREQ_MHZ:.3f}')")

cat >"$CONF" <<EOF
# Generated spike config — single channel UDP to localhost:$UDP_PORT
devices: ({
  type = "rtlsdr";
  gain = $GAIN;
  centerfreq = $CENTER;
  mode = "multichannel";
  channels: (
    {
      freq = $CENTER;
      modulation = "am";
      outputs: (
        {
          type = "udp_stream";
          dest_address = "127.0.0.1";
          dest_port = $UDP_PORT;
          continuous = false;
        },
        {
          type = "file";
          directory = "$SPIKE_DIR";
          filename_template = "spike";
          continuous = false;
        }
      );
    }
  );
});
EOF

echo "Wrote $CONF"

if [[ -x "$RTL_AIRBAND" ]] && lsusb 2>/dev/null | grep -qiE 'rtl|noeelec|realtek|0bda'; then
  echo "-- UDP capture 15s on port $UDP_PORT --"
  timeout 15 nc -u -l "$UDP_PORT" >"$SPIKE_DIR/capture.f32" &
  NC_PID=$!
  sleep 0.5
  timeout 14 "$RTL_AIRBAND" -f -c "$CONF" 2>"$SPIKE_DIR/rtl_airband.log" || true
  wait "$NC_PID" 2>/dev/null || true
  BYTES=$(wc -c <"$SPIKE_DIR/capture.f32" || echo 0)
  echo "Captured $BYTES bytes UDP PCM (f32le @ 8kHz when squelch open)"
  if [[ "$BYTES" -gt 1000 ]]; then
    echo "PASS: received UDP audio from rtl_airband"
  else
    echo "NOTE: low/no UDP data — normal if no traffic on $FREQ_MHZ MHz"
  fi
else
  echo "SKIP: live rtl_airband run (binary or dongle missing)"
fi

echo "Spike artifacts in $SPIKE_DIR"
