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


def test_tax_beats_transfer_channel():
    assert parse("NEFT/000483399203/ICIC/GST PAYMENT CHALLAN").category == "TAX"
    assert parse("TDS RECOVERY Q2 FY26").category == "TAX"


def test_charges_are_not_transfers():
    assert parse("IMPS charges").category == "BANK_CHARGES"


def test_word_boundaries_stop_false_positives():
    # a merchant called TAXI FOR SURE must not be classified as TAX
    assert parse("UPI-TAXI FOR SURE-XXXXXX8672-AUBL0002125-1032937").category != "TAX"


def test_unmatched_narration_is_not_forced_into_a_bucket():
    assert parse("SOMETHING ENTIRELY UNKNOWN 12345").category == "UNCATEGORISED"


def test_bank_charges_have_no_counterparty():
    # guards a real bug: the fallback rule ranked "MIN BAL PENALTY" as a vendor
    for d in ("IMPS charges", "MIN BAL PENALTY", "AMC FEE S123"):
        p = parse(d)
        assert p.counterparty is None, d
        assert p.parsed_by.startswith("no-counterparty")


def test_tax_and_cash_have_no_counterparty():
    assert parse("TDS 194C Q3 FY26").counterparty is None
    assert parse("ATM CASH WDL S518883172").counterparty is None


def test_placeholder_ref_is_stripped_from_the_name():
    # "NA" is our own stand-in for a missing reference id; it must not become
    # part of the vendor name and split the group.
    name = parse("EMI BAJAJ FINANCE LTD NA").counterparty
    assert name and not name.endswith("NA") and "BAJAJ FINANCE" in name
