#!/usr/bin/env bash
# Download the STT model while online (run once before flight).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${1:-$HOME/.config/kingfisher-airband/config.yaml}"
cd "$ROOT"
exec uv run airband-download-model -c "$CONFIG"
