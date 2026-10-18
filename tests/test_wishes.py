"""Roommates' own words -> wishes. Gemini is faked, so these cost nothing and need no key."""
import json

import pytest

from app import cache, wishes
from app.models import Listing, Roommate, Want

GYM_TEXT = "i want to be close to a gym, laundry included, need gas and water included."


@pytest.fixture(autouse=True)
def temp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


def fake_gemini(monkeypatch, replies):
    """Make wishes._call_gemini return these replies in order, and count the calls."""
    calls = []

    def fake(prompt, schema):
        calls.append(prompt)
        return replies[len(calls) - 1]

    monkeypatch.setattr(wishes, "_call_gemini", fake)
    return calls


def gym_reply(**changes) -> str:
    data = {
        "core": [{"criterion": "laundry", "importance": "medium", "quote": "laundry included"}],
        "near": [{"place": "gym", "importance": "medium", "quote": "close to a gym"}],
        "features": [{"feature": "gas included", "importance": "must", "quote": "need gas and water included"},
                     {"feature": "water included", "importance": "must", "quote": "need gas and water included"}],
        "cannot_check": [],
    }
    data.update(changes)
    return json.dumps(data)


# ---------- Short texts: plain code ----------

def test_short_text_is_read_by_code_without_gemini(monkeypatch):
    calls = fake_gemini(monkeypatch, [])
    w = wishes.parse_wishes("Laundry 5, rent 3")
    assert w.weights == {"laundry": 5, "rent": 3}
    assert w.evidence["laundry"] == "Laundry 5"
    assert calls == []


def test_short_parser_hands_anything_else_to_gemini():
    assert wishes.quick_parse("laundry 5 and close to a gym") is None
    assert wishes.quick_parse("I need a big kitchen") is None
    assert wishes.quick_parse("walk: 4 & parking=0") is not None


# ---------- Long texts: Gemini extracts, code checks ----------

def test_free_text_becomes_weights_places_and_features(monkeypatch):
    fake_gemini(monkeypatch, [gym_reply()])
    w = wishes.parse_wishes(GYM_TEXT)
    assert w.weights == {"laundry": 4}  # "Wanted" counts for more than the starting 3.
    assert [(x.kind, x.what, x.weight) for x in w.wants] == [
        ("near", "gym", 4), ("feature", "gas included", 5), ("feature", "water included", 5)]
    assert w.strict == []  # "laundry included" doesn't say in-unit.
    assert w.not_understood == []


def test_quote_not_in_their_message_is_thrown_out(monkeypatch):
    bad = gym_reply(near=[{"place": "pool", "importance": "high", "quote": "near a pool"}])
    fake_gemini(monkeypatch, [bad, bad])
    w = wishes.parse_wishes(GYM_TEXT)
    assert all(x.what != "pool" for x in w.wants)
    assert "near a pool" in w.not_understood


def test_place_not_in_their_own_words_is_thrown_out(monkeypatch):
    # The quote is real, but they never said "pool": a made-up wish.
    bad = gym_reply(near=[{"place": "swimming pool", "importance": "high", "quote": "close to a gym"}])
    fake_gemini(monkeypatch, [bad, bad])
    w = wishes.parse_wishes(GYM_TEXT)
    assert all(x.kind != "near" for x in w.wants)


def test_budget_must_be_in_the_quote_and_is_not_a_rent_rating(monkeypatch):
    text = "my max is $1,400 and I need a balcony"
    reply = json.dumps({"budget": 1400, "budget_quote": "my max is $1,400",
                        "core": [{"criterion": "rent", "importance": "must", "quote": "my max is $1,400"}]})
    fake_gemini(monkeypatch, [reply])
    w = wishes.parse_wishes(text)
    assert w.budget == 1400
    assert "rent" not in w.weights  # A budget alone doesn't say how much price matters.

    made_up = json.dumps({"budget": 1500, "budget_quote": "my max is $1,400"})
    w = wishes.validate_wishes(made_up, text)
    assert w.budget is None


def test_dont_care_drops_a_wish_and_cannot_check_is_kept_only_if_said(monkeypatch):
    text = "dont need a gym anymore. want a quiet street"
    reply = json.dumps({"near": [{"place": "gym", "importance": "none", "quote": "dont need a gym"}],
                        "cannot_check": ["quiet street", "good vibes"]})
    fake_gemini(monkeypatch, [reply])
    w = wishes.parse_wishes(text)
    assert [x.what for x in w.drop] == ["gym"] and w.wants == []
    assert w.cannot_check == ["quiet street"]


def test_malformed_reply_retried_once_then_cached(monkeypatch):
    calls = fake_gemini(monkeypatch, ["not json", gym_reply()])
    first = wishes.parse_wishes(GYM_TEXT)
    assert len(calls) == 2 and first.wants
    assert wishes.parse_wishes(GYM_TEXT) == first
    assert len(calls) == 2  # Second time from the cache.


# ---------- Saving wishes on a roommate ----------

def test_apply_wishes_adds_replaces_and_drops():
    r = Roommate(name="A", budget=1500, wants=[Want(kind="near", what="gym", weight=3),
                                              Want(kind="feature", what="pets allowed", weight=4)])
    w = wishes.Wishes(weights={"laundry": 5},
                      wants=[Want(kind="near", what="Gym", weight=5)],
                      drop=[Want(kind="feature", what="pets allowed", weight=0)], budget=1200)
    out = wishes.apply_wishes(r, w)
    assert out.weights.laundry == 5 and out.weights.rent == 3  # Unmentioned stays.
    assert [(x.what, x.weight) for x in out.wants] == [("Gym", 5)]
    assert out.budget == 1200
    assert r.wants[0].weight == 3  # The original is not changed.


# ---------- "Does the listing have X?" ----------

LISTING_TEXT = "Pros: Cheap; landlord pays water/trash\nCons: window A/C; no pets"


def test_feature_answers_need_a_real_quote_from_the_listing():
    raw = json.dumps({"answers": [
        {"feature": "water included", "answer": "yes", "quote": "landlord pays water/trash"},
        {"feature": "pets allowed", "answer": "no", "quote": "no pets"},
        {"feature": "gas included", "answer": "yes", "quote": "gas paid by owner"},  # Not in the text.
    ]})
    out = wishes.validate_features(raw, LISTING_TEXT, ["water included", "pets allowed", "gas included", "balcony"])
    assert out["water included"] == {"value": True, "quote": "landlord pays water/trash"}
    assert out["pets allowed"]["value"] is False
    assert out["gas included"]["value"] is None  # Made-up quote -> unknown, never guessed.
    assert out["balcony"]["value"] is None       # Not answered -> unknown.


def test_no_listing_text_means_unknown_without_a_call(monkeypatch):
    calls = fake_gemini(monkeypatch, [])
    assert wishes.check_features(None, ["gas included"]) == {"gas included": {"value": None, "quote": None}}
    assert calls == []


def test_feature_answers_are_cached_one_by_one(monkeypatch):
    calls = fake_gemini(monkeypatch, [
        json.dumps({"answers": [{"feature": "pets allowed", "answer": "no", "quote": "no pets"}]}),
        json.dumps({"answers": [{"feature": "A/C", "answer": "yes", "quote": "window A/C"}]}),
    ])
    wishes.check_features(LISTING_TEXT, ["pets allowed"])
    out = wishes.check_features(LISTING_TEXT, ["pets allowed", "A/C"])
    assert len(calls) == 2 and '"A/C"' in calls[1] and "pets allowed" not in calls[1].split("Listing text")[0]
    assert out["A/C"]["value"] is True and out["pets allowed"]["value"] is False


def test_facts_are_looked_up_once_per_listing_and_lined_up_per_roommate(monkeypatch):
    looked_up = []
    monkeypatch.setattr(wishes.maps_lookup, "nearest_place",
                        lambda lat, lng, what: looked_up.append(what) or {"name": "Gym A", "walk_minutes": 7.0})
    monkeypatch.setattr(wishes, "check_features",
                        lambda text, feats: {f: {"value": True, "quote": "q"} for f in feats})
    listings = [Listing(id="a", lat=34.0, lng=-118.4, source_text="x")]
    roommates = [Roommate(name="A", budget=1, wants=[Want(kind="near", what="gym"),
                                                     Want(kind="feature", what="pets allowed")]),
                 Roommate(name="B", budget=1, wants=[Want(kind="near", what="gym")]),
                 Roommate(name="C", budget=1)]
    facts = wishes.want_facts_for(listings, roommates)
    assert looked_up == ["gym"]  # Asked by two roommates, looked up once.
    assert facts[(0, 0)] == [{"name": "Gym A", "walk_minutes": 7.0}, {"value": True, "quote": "q"}]
    assert facts[(0, 1)] == [{"name": "Gym A", "walk_minutes": 7.0}]
    assert facts[(0, 2)] == []


def test_specific_ask_needs_their_own_words():
    text = "would like in unit laundry so I don't have to leave. parking is fine"
    reply = json.dumps({"core": [
        {"criterion": "laundry", "importance": "medium", "quote": "in unit laundry", "specific": "in_unit_laundry"},
        {"criterion": "parking", "importance": "low", "quote": "parking is fine", "specific": "included_parking"},
    ]})
    w = wishes.validate_wishes(reply, text)
    assert w.weights == {"laundry": 4, "parking": 2}
    assert w.strict == ["in_unit_laundry"]  # "parking is fine" never said free/included.
    assert wishes.describe(w)[0] == "in-unit laundry: wanted"


def test_specific_ask_is_saved_and_replaced_when_they_change_their_mind():
    r = Roommate(name="A", budget=1500)
    r = wishes.apply_wishes(r, wishes.Wishes(weights={"laundry": 4}, strict=["in_unit_laundry"]))
    assert r.strict == ["in_unit_laundry"] and r.weights.laundry == 4
    r = wishes.apply_wishes(r, wishes.Wishes(weights={"laundry": 2}))  # "any laundry is fine"
    assert r.strict == []


def test_how_they_get_to_campus_is_read_only_from_their_own_words():
    text = "I go to school most days through transit"
    ok = json.dumps({"travel_mode": "TRANSIT", "travel_mode_quote": "through transit"})
    assert wishes.validate_wishes(ok, text).travel_mode == "TRANSIT"
    made_up = json.dumps({"travel_mode": "DRIVE", "travel_mode_quote": "through transit"})
    assert wishes.validate_wishes(made_up, text).travel_mode is None  # They never said drive.
