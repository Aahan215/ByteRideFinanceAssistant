"""Bank resolution. 273,528 SBI transactions were in the table while "SBI",
"SBIN" and "State bank of india" were all refused -- three different causes."""
from app.validator import resolve_bank
from app.coverage import unresolved


def test_every_way_people_say_sbi_resolves():
    for q in ["SBI", "sbi", "SBIN", "sbin", "State bank of india", "STATE BANK OF INDIA",
              "state bank", "SBI bank"]:
        name, _, how = resolve_bank(q)
        assert name == "STATE BANK OF INDIA", (q, how)


def test_abbreviations_and_codes_for_other_banks():
    assert resolve_bank("ICICI")[0] == "ICICI BANK LIMITED"
    assert resolve_bank("hdfc")[0] == "HDFC BANK LIMITED"
    assert resolve_bank("kotak")[0] == "KOTAK MAHINDRA BANK LIMITED"
    assert resolve_bank("axis")[0] == "AXIS BANK LIMITED"


def test_an_unknown_bank_is_refused_not_guessed():
    name, candidates, how = resolve_bank("Northwind Bank")
    assert name is None and how == "unknown"


def test_bank_codes_and_names_are_covered_vocabulary():
    for q in ["Are there any transactions with SBIN bank?", "spend via kotak",
              "how much through state bank of india"]:
        assert unresolved(q) == [], q
