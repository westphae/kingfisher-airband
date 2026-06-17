#!/usr/bin/env python3
"""Phase 0 spike: benchmark faster-whisper ATC model on a WAV/FLAC segment."""
from __future__ import annotations

import argparse
import resource
import sys
import time
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Benchmark jacktol ATC whisper model")
    p.add_argument("audio", type=Path, help="WAV/FLAC/MP3 file (16 kHz mono preferred)")
    p.add_argument(
        "--model",
        default="jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper",
    )
    p.add_argument("--compute-type", default="int8")
    args = p.parse_args()

    if not args.audio.is_file():
        print(f"ERROR: {args.audio} not found", file=sys.stderr)
        return 1

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("Install: pip install faster-whisper", file=sys.stderr)
        return 1

    print(f"Loading model {args.model} ({args.compute_type})...")
    t0 = time.perf_counter()
    model = WhisperModel(args.model, device="cpu", compute_type=args.compute_type)
    load_s = time.perf_counter() - t0
    print(f"Model load: {load_s:.1f}s")

    t1 = time.perf_counter()
    segments, info = model.transcribe(
        str(args.audio),
        beam_size=1,
        language="en",
        vad_filter=True,
        initial_prompt="Aviation air traffic control radio.",
    )
    text_parts = []
    for seg in segments:
        text_parts.append(seg.text.strip())
    text = " ".join(text_parts).strip()
    infer_s = time.perf_counter() - t1
    duration = getattr(info, "duration", None)
    rusage = resource.getrusage(resource.RUSAGE_SELF)
    rss_mb = rusage.ru_maxrss / 1024  # Linux: KB

    print(f"Inference: {infer_s:.1f}s")
    if duration:
        print(f"Audio duration: {duration:.1f}s  RTF: {infer_s / duration:.2f}x")
    print(f"Peak RSS: {rss_mb:.0f} MB")
    print(f"Language: {info.language}  prob={info.language_probability:.2f}")
    print("--- transcript ---")
    print(text or "(empty)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
