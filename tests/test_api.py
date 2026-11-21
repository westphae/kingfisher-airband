import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from airband.api.server import create_app
from airband.config import ChannelCfg, Config, PlannerCfg, load_config, persist_runtime_prefs
from airband.main import Daemon
from airband.planner.channels import plan_channels


def _daemon(tmp_path: Path) -> Daemon:
    cfg = Config(
        channels=[
            ChannelCfg(119.7, "DEP", "departure", enabled=True),
            ChannelCfg(124.125, "TWR", "tower", enabled=False),
        ],
        planner=PlannerCfg(include_gps_airport=False, include_active_com=False),
        data_dir=tmp_path / "data",
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("channels: []\n")
    d = Daemon(cfg, cfg_path)
    d.sdr = MagicMock()
    d.sdr.running = True
    d.sdr.last_error = ""
    d._apply_plan = MagicMock()  # type: ignore[method-assign]
    return d


def test_catalog_lists_static_channels(tmp_path):
    d = _daemon(tmp_path)
    cat = d.channel_catalog()
    assert len(cat["channels"]) == 2
    assert cat["channels"][0]["enabled"] is True
    assert cat["planner"]["include_gps_airport"] is False


def test_catalog_marks_howgozit_match_on_static_channel(tmp_path):
    d = _daemon(tmp_path)
    d.cfg.planner.include_active_com = True
    d._active_freq = 119.7
    d._last_plan = plan_channels(
        d.cfg,
        active_freq_mhz=d._active_freq,
    )
    cat = d.channel_catalog()
    dep = next(c for c in cat["channels"] if c["freq_mhz"] == 119.7)
    assert dep["enabled"] is True
    assert dep["active"] is True
    assert dep["via_howgozit"] is True
    assert dep["sources"] == ["static", "howgozit"]
    assert cat["auto"][0]["matched_static_label"] == "DEP"


def test_catalog_adds_howgozit_only_chip_when_not_in_static(tmp_path):
    d = _daemon(tmp_path)
    d.cfg.planner.include_active_com = True
    d._active_freq = 121.5
    d._last_plan = plan_channels(
        d.cfg,
        active_freq_mhz=d._active_freq,
    )
    cat = d.channel_catalog()
    hgz = next(c for c in cat["channels"] if c.get("source") == "howgozit")
    assert hgz["freq_mhz"] == 121.5
    assert hgz["active"] is True
    assert hgz["label"] == "ACTIVE COM"
    assert len(cat["channels"]) == 3


def test_catalog_howgozit_on_disabled_static_match(tmp_path):
    d = _daemon(tmp_path)
    d.cfg.channels[0].enabled = False
    d.cfg.channels[1].enabled = True
    d.cfg.planner.include_active_com = True
    d._active_freq = 119.7
    d._last_plan = plan_channels(
        d.cfg,
        active_freq_mhz=d._active_freq,
    )
    cat = d.channel_catalog()
    dep = next(c for c in cat["channels"] if c["freq_mhz"] == 119.7)
    assert dep["enabled"] is False
    assert dep["active"] is True
    assert dep["via_howgozit"] is True
    assert dep["sources"] == ["howgozit"]


def test_patch_channel_enabled(tmp_path):
    d = _daemon(tmp_path)
    web = Path(__file__).resolve().parent.parent / "web"
    client = TestClient(create_app(d, tmp_path / "archive", web))
    r = client.patch("/api/channels", json={"freq_mhz": 124.125, "enabled": True})
    assert r.status_code == 200
    body = r.json()
    twr = next(c for c in body["channels"] if c["freq_mhz"] == 124.125)
    assert twr["enabled"] is True
    d._apply_plan.assert_called()


def test_cannot_disable_last_channel(tmp_path):
    d = _daemon(tmp_path)
    web = Path(__file__).resolve().parent.parent / "web"
    client = TestClient(create_app(d, tmp_path / "archive", web))
    r = client.patch("/api/channels", json={"freq_mhz": 119.7, "enabled": False})
    assert r.status_code == 400


def test_persist_runtime_prefs(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "channels:\n  - freq_mhz: 119.7\n    label: DEP\n    enabled: true\n"
        "planner:\n  include_gps_airport: true\n  include_active_com: true\n"
    )
    cfg = load_config(cfg_path)
    cfg.channels[0].enabled = False
    cfg.planner.include_active_com = False
    persist_runtime_prefs(cfg_path, cfg)
    reloaded = load_config(cfg_path)
    assert reloaded.channels[0].enabled is False
    assert reloaded.planner.include_active_com is False
