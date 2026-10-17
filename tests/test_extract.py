"""Tests for step 2. Gemini is replaced with fake replies, so these run with no key or network.

The listing text below is made up for testing.
"""
import json

import pytest

from app import cache, extract

LISTING = """Sunny 3 bed / 2 bath apartment at 1824 Fairburn Ave, Los Angeles.
Rent is $4,550/month. In-unit washer and dryer.
Parking: one space for $100/mo extra. Water and trash included.
Available 2027-08-15."""


def reply(**overrides) -> str:
    """A well-behaved Gemini reply for LISTING, with optional changes."""
    data = {
        "address": "1824 Fairburn Ave, Los Angeles",
        "rent_total_monthly": 4550,
        "bedrooms": 3,
        "bathrooms": 2,
        "laundry": "in_unit",
        "parking": "paid",
        "utilities_included": True,
        "available_from": "2027-08-15",
        "evidence": {
            "address": "1824 Fairburn Ave, Los Angeles",
            "rent_total_monthly": "Rent is $4,550/month",
            "bedrooms": "3 bed",
            "bathrooms": "2 bath",
            "laundry": "In-unit washer and dryer",
            "parking": "one space for $100/mo extra",
            "utilities_included": "Water and trash included",
            "available_from": "Available 2027-08-15",
        },
    }
    for k, v in overrides.items():
        if k == "evidence":
            data["evidence"].update(v)
        else:
            data[k] = v
    return json.dumps(data)


@pytest.fixture(autouse=True)
def temp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


def fake_gemini(monkeypatch, replies):
    """Make _call_gemini return these replies in order, and count the calls."""
    calls = []

    def fake(text):
        calls.append(text)
        return replies[len(calls) - 1]

    monkeypatch.setattr(extract, "_call_gemini", fake)
    return calls


def test_good_reply_keeps_every_fact():
    e = extract.validate_reply(reply(), LISTING)
    assert e.rent_total_monthly == 4550
    assert e.bedrooms == 3 and e.bathrooms == 2
    assert e.laundry == "in_unit" and e.parking == "paid"
    assert e.utilities_included is True
    assert e.available_from == "2027-08-15"
    assert set(e.evidence) == set(extract.FACT_FIELDS)
    assert e.rejected == []


def test_quote_not_in_text_becomes_unknown():
    e = extract.validate_reply(reply(evidence={"laundry": "Washer and dryer in every unit"}), LISTING)
    assert e.laundry == "unknown"
    assert "laundry" not in e.evidence
    assert "laundry" in e.rejected


def test_missing_quote_becomes_unknown():
    e = extract.validate_reply(reply(evidence={"parking": None}), LISTING)
    assert e.parking == "unknown"
    assert "parking" in e.rejected


def test_made_up_number_is_rejected_even_with_a_real_quote():
    # The quote is really in the text, but it says $4,550, not $4,000.
    e = extract.validate_reply(reply(rent_total_monthly=4000), LISTING)
    assert e.rent_total_monthly is None
    assert "rent_total_monthly" in e.rejected


def test_quote_matching_ignores_line_breaks_case_and_curly_quotes():
    assert extract.quote_in_text("RENT IS $4,550/MONTH.  IN-UNIT", LISTING)
    assert extract.quote_in_text("it’s quiet", "It's quiet here")


def test_number_words_and_studio_count():
    assert extract.value_matches_quote("bedrooms", 3, "three bedrooms")
    assert extract.value_matches_quote("bedrooms", 0, "Cozy studio")
    assert extract.value_matches_quote("bathrooms", 1.5, "1.5 baths")
    assert not extract.value_matches_quote("bedrooms", 4, "3 bed")


def test_nothing_stated_stays_unknown():
    e = extract.validate_reply(json.dumps({"evidence": {}}), "Nice place, DM me.")
    assert e.rent_total_monthly is None and e.laundry == "unknown"
    assert e.evidence == {} and e.rejected == []


def test_malformed_reply_is_retried_once(monkeypatch):
    calls = fake_gemini(monkeypatch, ["not json", reply()])
    e = extract.extract_listing(LISTING)
    assert len(calls) == 2
    assert e.rent_total_monthly == 4550


def test_two_malformed_replies_give_all_unknown(monkeypatch):
    calls = fake_gemini(monkeypatch, ["not json", '{"laundry": "yes please"}'])
    e = extract.extract_listing(LISTING)
    assert len(calls) == 2
    assert e.rent_total_monthly is None and e.laundry == "unknown"
    assert e.rejected == ["malformed_reply"]


def test_same_text_is_answered_from_cache(monkeypatch):
    calls = fake_gemini(monkeypatch, [reply(), reply()])
    first = extract.extract_listing(LISTING)
    second = extract.extract_listing(LISTING)
    assert len(calls) == 1
    assert first == second


def test_rent_per_person_is_computed_in_code():
    assert extract.rent_per_person(4550, 3) == 1516.67
    assert extract.rent_per_person(None, 3) is None
    with pytest.raises(ValueError):
        extract.rent_per_person(4550, 0)


def test_rejected_quote_triggers_one_retry_and_merges(monkeypatch):
    # First reply adds a word to the rent quote (seen live: "2 bed $7,150 hold"); second reply is clean.
    bad = reply(evidence={"rent_total_monthly": "Rent is $4,550/month hold"})
    calls = fake_gemini(monkeypatch, [bad, reply()])
    e = extract.extract_listing(LISTING)
    assert len(calls) == 2
    assert e.rent_total_monthly == 4550
    assert e.rejected == []


def test_fact_rejected_twice_stays_unknown(monkeypatch):
    bad = reply(evidence={"rent_total_monthly": "Rent is $4,550/month hold"})
    calls = fake_gemini(monkeypatch, [bad, bad])
    e = extract.extract_listing(LISTING)
    assert len(calls) == 2
    assert e.rent_total_monthly is None
    assert e.rejected == ["rent_total_monthly"]
    assert e.bedrooms == 3  # Other facts are still kept.


def test_explanation_is_cached(monkeypatch):
    calls = []

    class FakeModels:
        def generate_content(self, model, contents):
            calls.append(contents)
            return type("R", (), {"text": " Pick A. "})()

    monkeypatch.setattr(extract, "_client", lambda: type("C", (), {"models": FakeModels()})())
    decision = {"pick": {"title": "A"}, "least_happy": {"roommate": "B"}}
    assert extract.explain_decision(decision) == "Pick A."
    assert extract.explain_decision(decision) == "Pick A."
    assert len(calls) == 1
