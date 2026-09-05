from app.enrich import parse, normalise


def test_extracts_counterparty_from_each_narration_format():
    cases = {
        "FT -  95842568 -  50200013729069 - SELECTION ELECTRONICS": "SELECTION ELECTRONICS",
        "UPI-NAVYUG SELECTION-XXXXXX8672-AUBL0002125-103293775381-2605": "NAVYUG SELECTION",
        "NEFT/000483399203/ICIC/PARESH VIKRANT GHASE": "PARESH VIKRANT GHASE",
        "IMPS OW/507614422198/Gautam singh/SBIN/43292707719": "GAUTAM SINGH",
        "NEFT  - ICIC0001241 - 95584112 - 124105002702 - SELECTION MOBILE": "SELECTION MOBILE",
    }
    for desc, want in cases.items():
        assert parse(desc).counterparty == want, desc


def test_channel_detection():
    assert parse("UPI-X-Y").channel == "UPI"
    assert parse("NEFT/1/ICIC/ACME TRADERS").channel == "NEFT"
    assert parse("IMPS charges").channel == "IMPS"


def test_ifsc_and_numeric_tokens_are_never_counterparties():
    p = parse("NEFT/000483399203/ICIC0001241/AB")
    assert p.counterparty != "ICIC0001241"


def test_legal_suffixes_collapse_to_one_group_key():
    assert normalise("SELECTRICITY TWO PRIVATE LIMITED") == normalise("Selectricity Two Ltd")


def test_empty_description_is_not_invented():
    p = parse(None)
    assert p.counterparty is None and p.parsed_by == "empty"
