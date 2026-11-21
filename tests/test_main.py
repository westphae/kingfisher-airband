"""Daemon orchestration tests."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from airband.config import ChannelCfg, Config, PlannerCfg
from airband.main import Daemon


def _daemon(tmp_path: Path) -> Daemon:
    cfg = Config(
        channels=[ChannelCfg(119.7, "DEP", "departure", enabled=True)],
        planner=PlannerCfg(include_gps_airport=False, include_active_com=False),
        data_dir=tmp_path / "data",
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("channels: []\n")
    d = Daemon(cfg, cfg_path)
    d.sdr = MagicMock()
    d.sdr.running = True
    d.sdr.last_error = ""
    d.kf = MagicMock()
    d.kf.fetch_gps.return_value = MagicMock(has_fix=False, lat=0, lon=0, speed_m_s=0)
    d.kf.fetch_aircraft.return_value = ""
    d.kf.latest_active_freq_mhz.return_value = 119.7
    return d


def test_poll_does_not_replan_when_active_com_disabled(tmp_path: Path):
    """include_active_com: false must ignore howgozit COM rows in the poll loop."""
    d = _daemon(tmp_path)
    d._apply_plan = MagicMock()  # type: ignore[method-assign]
    d._apply_plan()
    d._apply_plan.reset_mock()

    d._active_freq = None
    with patch.object(d, "_stop") as stop:
        stop.is_set.side_effect = [False, True]
        d._poll_kingfisher()

    d._apply_plan.assert_not_called()


def test_apply_plan_ignores_howgozit_com_when_disabled(tmp_path: Path):
    d = _daemon(tmp_path)
    d.sdr.start = MagicMock()
    d._stop_receivers = MagicMock()
    d._start_receivers = MagicMock()

    d._apply_plan()
    assert d._active_freq is None
    d.sdr.start.assert_called_once()

    d.sdr.start.reset_mock()
    d._apply_plan()
    d.sdr.start.assert_not_called()
