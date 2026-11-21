from airband.freq import is_valid_airband_mhz, normalize_howgozit_freq_mhz


def test_is_valid_airband_mhz():
    assert is_valid_airband_mhz(118.0)
    assert is_valid_airband_mhz(119.7)
    assert is_valid_airband_mhz(121.5)
    assert is_valid_airband_mhz(136.975)
    assert not is_valid_airband_mhz(117.975)
    assert not is_valid_airband_mhz(137.1)
    assert not is_valid_airband_mhz(0)


def test_normalize_already_valid():
    assert normalize_howgozit_freq_mhz(119.7) == 119.7
    assert normalize_howgozit_freq_mhz("124.125") == 124.125


def test_normalize_missing_decimal():
    assert normalize_howgozit_freq_mhz(11970) == 119.7
    assert normalize_howgozit_freq_mhz(1197) == 119.7
    assert normalize_howgozit_freq_mhz(1180) == 118.0
    assert normalize_howgozit_freq_mhz(124125) == 124.125


def test_normalize_prefers_unscaled_when_valid():
    assert normalize_howgozit_freq_mhz(121.5) == 121.5


def test_normalize_rejects_out_of_band():
    assert normalize_howgozit_freq_mhz(99) is None
    assert normalize_howgozit_freq_mhz(99999) is None
    assert normalize_howgozit_freq_mhz("") is None
    assert normalize_howgozit_freq_mhz(None) is None
