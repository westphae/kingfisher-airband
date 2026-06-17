from pathlib import Path

from airband.config import ChannelCfg, Config
from airband.planner.channels import PlannedChannel, RadioPlan, plan_channels
from airband.sdr.rtl_airband import render_conf


def test_plan_multichannel_when_close():
    cfg = Config(
        channels=[
            ChannelCfg(119.25, "TWR", "tower"),
            ChannelCfg(120.45, "GND", "ground"),
        ]
    )
    plan = plan_channels(cfg)
    assert plan.mode == "multichannel"
    assert len(plan.channels) == 2
    assert plan.channels[0].udp_port == cfg.udp_base_port
    assert plan.channels[1].udp_port == cfg.udp_base_port + 1


def test_plan_scan_when_wide():
    cfg = Config(
        channels=[
            ChannelCfg(118.325, "ATIS", "atis"),
            ChannelCfg(124.125, "TWR", "tower"),
        ]
    )
    plan = plan_channels(cfg)
    assert plan.mode == "scan"
    assert all(ch.udp_port == cfg.udp_base_port for ch in plan.channels)


def test_render_scan_conf_single_channel_block(tmp_path: Path):
    cfg = Config(
        channels=[ChannelCfg(118.325, "ATIS", "atis"), ChannelCfg(124.125, "TWR", "tower")]
    )
    plan = RadioPlan(
        mode="scan",
        channels=[
            PlannedChannel(124.125, "TWR", "tower", cfg.udp_base_port),
            PlannedChannel(118.325, "ATIS", "atis", cfg.udp_base_port),
        ],
    )
    conf = tmp_path / "rtl.conf"
    render_conf(cfg, plan, conf)
    text = conf.read_text()
    assert "mode = \"scan\"" in text
    assert "freqs = (" in text
    assert text.count("freq = ") == 0
    assert "index = 0" in text
    assert "dest_port = 7356" in text
