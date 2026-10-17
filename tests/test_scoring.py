"""Step 3 tests: weighted scoring with a visible breakdown, unknowns excluded, deterministic."""
import json
from pathlib import Path

import pytest

from app.models import Listing, Roommate, Weights
from app.scoring import CRITERIA, rent_per_person, score_listing

ALL_ZERO = dict(rent=0, commute=0, laundry=0, parking=0, bedrooms=0)


def make_listing(**kw) -> Listing:
    base = dict(id="x", title="Test", rent_total_monthly=3000, bedrooms=2, walk_minutes=10,
                laundry="in_unit", parking="included")
    base.update(kw)
    return Listing(**base)


def only(**weights) -> Weights:
    """Weights where only the named criteria count."""
    return Weights(**{**ALL_ZERO, **weights})


def test_rent_per_person_is_whole_unit_rent_split_evenly():
    assert rent_per_person(make_listing(rent_total_monthly=3000), 2) == 1500
    assert rent_per_person(make_listing(rent_total_monthly=None), 2) is None


def test_perfect_listing_scores_100_and_breakdown_adds_up():
    r = score_listing(make_listing(), Roommate(name="A", budget=2000), 2)
    assert r["score"] == 100
    assert [b["criterion"] for b in r["breakdown"]] == CRITERIA
    assert sum(b["contribution"] for b in r["breakdown"]) == pytest.approx(r["score"], abs=0.5)
    assert sum(b["weight"] for b in r["breakdown"]) == pytest.approx(1, abs=0.01)
    assert r["partial_data"] is False


def test_criterion_rules():
    roommate = Roommate(name="A", budget=1000)
    def s(c, **kw):
        r = score_listing(make_listing(**kw), roommate, 2)
        return next(b["criterion_score"] for b in r["breakdown"] if b["criterion"] == c)

    assert s("laundry", laundry="shared") == 0.4 and s("laundry", laundry="none") == 0.0
    assert s("parking", parking="paid") == 0.5 and s("parking", parking="none") == 0.0
    assert s("bedrooms", bedrooms=1) == 0.0 and s("bedrooms", bedrooms=3) == 1.0
    assert s("commute", walk_minutes=40) == 0.0 and s("commute", walk_minutes=25) == 0.5
    # $1,000 each = 100% of a $1,000 budget, halfway between 75% (full) and 125% (zero).
    assert s("rent", rent_total_monthly=2000) == 0.5


def test_weights_change_the_ranking():
    cheap_far = make_listing(id="cheap_far", rent_total_monthly=2000, walk_minutes=40)
    pricey_close = make_listing(id="pricey_close", rent_total_monthly=3600, walk_minutes=5)

    def best(weights):
        roommate = Roommate(name="A", budget=1500, weights=weights)
        return max([cheap_far, pricey_close], key=lambda l: score_listing(l, roommate, 2)["score"]).id

    assert best(only(rent=5, commute=1)) == "cheap_far"
    assert best(only(rent=1, commute=5)) == "pricey_close"


def test_unknowns_are_excluded_and_weights_renormalized():
    roommate = Roommate(name="A", budget=2000, weights=only(laundry=5, parking=5))
    r = score_listing(make_listing(laundry="unknown", parking="none"), roommate, 2)
    laundry = next(b for b in r["breakdown"] if b["criterion"] == "laundry")
    parking = next(b for b in r["breakdown"] if b["criterion"] == "parking")

    assert laundry["unknown"] and laundry["criterion_score"] is None and laundry["weight"] == 0
    assert parking["weight"] == 1.0  # All the weight moves to what is known.
    assert r["score"] == 0  # Judged only on parking (none), not on a guessed laundry value.
    assert r["unknown"] == ["laundry"] and r["partial_data"] is True


def test_nothing_known_gives_no_score_not_a_guess():
    roommate = Roommate(name="A", budget=2000, weights=only(laundry=5))
    r = score_listing(make_listing(laundry="unknown"), roommate, 2)
    assert r["score"] is None


def test_same_inputs_give_the_same_score():
    listing, roommate = make_listing(walk_minutes=23, rent_total_monthly=3333), Roommate(name="A", budget=1700)
    assert score_listing(listing, roommate, 2) == score_listing(listing, roommate, 2)


def test_old_slider_names_still_work():
    # static/app.js still sends "walk" and "grocery"; "walk" means commute, "grocery" is ignored.
    w = Weights.model_validate({"rent": 1, "walk": 4, "laundry": 2, "parking": 0, "grocery": 5})
    assert w.commute == 4 and w.bedrooms == 3 and not hasattr(w, "grocery")


def test_every_demo_listing_scores():
    data = json.loads((Path(__file__).parent.parent / "data" / "demo_listings.json").read_text())
    roommate = Roommate(name="A", budget=1500)
    for d in data:
        r = score_listing(Listing(**d), roommate, 3)
        assert r["score"] is None or 0 <= r["score"] <= 100


def test_per_bed_price_is_what_each_person_pays():
    per_bed = make_listing(rent_total_monthly=None, rent_per_person_listed=1150)
    assert rent_per_person(per_bed, 3) == 1150  # Not divided: each person pays the listed price.
    both = make_listing(rent_total_monthly=3000, rent_per_person_listed=1150)
    assert rent_per_person(both, 2) == 1500  # A whole-unit price wins when both are stated.
