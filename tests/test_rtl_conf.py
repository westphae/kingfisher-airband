from pathlib import Path

from airband.config import ChannelCfg, Config, PlannerCfg
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


def test_plan_single_enabled_channel():
    cfg = Config(
        channels=[
            ChannelCfg(119.7, "DEP", "departure", enabled=True),
            ChannelCfg(118.325, "ATIS", "atis", enabled=False),
        ],
        planner=PlannerCfg(include_gps_airport=False, include_active_com=False),
    )
    plan = plan_channels(cfg, active_freq_mhz=123.95)
    assert plan.mode == "multichannel"
    assert len(plan.channels) == 1
    assert plan.channels[0].freq_mhz == 119.7


def test_active_com_ignored_when_disabled():
    cfg = Config(
        channels=[ChannelCfg(119.7, "DEP", "departure", enabled=True)],
        planner=PlannerCfg(include_active_com=False),
    )
    plan = plan_channels(cfg, active_freq_mhz=123.95)
    assert len(plan.channels) == 1
    assert plan.channels[0].freq_mhz == 119.7


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
    assert 'mode = "scan"' in text
    assert "freqs = (" in text
    assert text.count("freq = ") == 0
    assert "index = 0" in text
    assert "dest_port = 7356" in text


def test_render_live_audio_udp_when_enabled(tmp_path: Path):
    from airband.config import DebugCfg

    cfg = Config(
        channels=[ChannelCfg(119.7, "DEP", "departure")],
        debug=DebugCfg(live_audio=True, live_audio_port=7357, live_audio_continuous=True),
    )
    plan = plan_channels(cfg)
    conf = tmp_path / "rtl.conf"
    render_conf(cfg, plan, conf)
    text = conf.read_text()
    assert "dest_port = 7357" in text
    assert "continuous = true" in text
