"""edge_tts — Communicate 용 pitch(Hz) 변환. SSML 은 라이브러리가 감싸므로 여기서 넣지 않는다."""
from server.ai import edge_tts_synth as m


def test_pitch_hz_passthrough() -> None:
    assert m.pitch_setting_to_communicate_hz("+85Hz") == "+85Hz"
    assert m.pitch_setting_to_communicate_hz("-12Hz") == "-12Hz"


def test_pitch_semitone_to_hz() -> None:
    assert m.pitch_setting_to_communicate_hz("+3.5st") == "+105Hz"


def test_pitch_percent_to_hz() -> None:
    assert m.pitch_setting_to_communicate_hz("+10%") == "+45Hz"


def test_pitch_empty_or_invalid() -> None:
    assert m.pitch_setting_to_communicate_hz("") == "+0Hz"
    assert m.pitch_setting_to_communicate_hz("bogus") == "+0Hz"


def test_rate_valid_or_default() -> None:
    assert m.rate_setting_or_default("+8%") == "+8%"
    assert m.rate_setting_or_default("") == "+0%"
    assert m.rate_setting_or_default("bad") == "+0%"
