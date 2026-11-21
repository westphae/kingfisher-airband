"""UDP ingest tests."""

import struct

from airband.ingest.udp import SAMPLE_RATE_IN, SAMPLE_RATE_OUT, UDPSegmentReceiver


def test_sample_rate_constants():
    assert SAMPLE_RATE_IN == 8000
    assert SAMPLE_RATE_OUT == 16000


def test_udp_receiver_accepts_packet_without_crash():
    received: list = []

    rx = UDPSegmentReceiver(
        0,  # port 0 = ephemeral in _run — only test init constants used in _emit path
        119.7,
        "DEP",
        "departure",
        lambda seg: received.append(seg),
        min_segment_s=0.01,
        max_segment_s=1.0,
    )
    # Exercise _emit math without starting the socket thread.
    rx._buf = [0.1] * int(0.05 * SAMPLE_RATE_IN)
    rx._seg_start_ns = 1
    rx._emit()
    assert len(received) == 1
