from airband.atis.parser import atis_to_howgozit_values, parse_atis
from airband.lexicon import postprocess


def test_postprocess_strips_hallucination():
    assert postprocess.postprocess("thank you for watching") == ""


def test_parse_atis_wind_alt():
    text = (
        "KSBA ARRIVAL INFORMATION ALPHA 2153Z WIND 27008KT VISIBILITY 10 "
        "FEW250 TEMPERATURE 18 DEW POINT 12 ALTIMETER 3012"
    )
    f = parse_atis(text, default_airport="KSBA")
    assert f.information == "A"
    assert f.wind == "27008KT"
    assert f.altimeter_inhg == "30.12"
    vals = atis_to_howgozit_values(f)
    assert vals["airport"] == "KSBA"
    assert vals["altimeter"] == "30.12"
