from lims_dq.censored import CensoredValue, parse_censored


def test_limit_operators():
    assert parse_censored("<0.01") == CensoredValue(kind="below", limit=0.01, raw="<0.01")
    assert parse_censored("> 100") == CensoredValue(kind="above", limit=100.0, raw="> 100")
    assert parse_censored("<=1.5").kind == "below"
    assert parse_censored(">=2").kind == "above"
    assert parse_censored("< 0.5 ").limit == 0.5


def test_qualifier_tokens():
    assert parse_censored("ND").kind == "not_detected"
    assert parse_censored("nd").kind == "not_detected"
    assert parse_censored("BQL").kind == "below"
    assert parse_censored("BLOQ").kind == "below"
    assert parse_censored("AQL").kind == "above"
    assert parse_censored("TNTC").kind == "too_numerous"
    assert parse_censored("tftc").kind == "too_numerous"


def test_tokens_have_no_limit():
    assert parse_censored("ND").limit is None


def test_plain_values_are_not_censored():
    assert parse_censored("12.5") is None
    assert parse_censored("SMP-000001") is None
    assert parse_censored("") is None
    assert parse_censored(None) is None
    assert parse_censored("   ") is None


def test_scientific_notation_limit():
    parsed = parse_censored("<1e-3")
    assert parsed is not None and parsed.limit == 0.001
