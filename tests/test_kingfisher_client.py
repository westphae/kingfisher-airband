from unittest.mock import MagicMock, patch

from airband.config import Config, HowgozitCfg
from airband.kingfisher.client import KingfisherClient


def _client() -> KingfisherClient:
    cfg = Config(howgozit=HowgozitCfg(atc_radio_log_id="log-1"))
    return KingfisherClient(cfg)


def test_latest_active_freq_normalizes_missing_decimal():
    client = _client()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "rows": [{"values": {"freq_mhz": "11970"}}],
    }
    mock_http = MagicMock()
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)
    mock_http.get.return_value = mock_resp

    with patch.object(client, "_client", return_value=mock_http):
        assert client.latest_active_freq_mhz() == 119.7


def test_latest_active_freq_skips_invalid():
    client = _client()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "rows": [
            {"values": {"freq_mhz": "99999"}},
            {"values": {"freq_mhz": "124.125"}},
        ],
    }
    mock_http = MagicMock()
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)
    mock_http.get.return_value = mock_resp

    with patch.object(client, "_client", return_value=mock_http):
        assert client.latest_active_freq_mhz() == 124.125
