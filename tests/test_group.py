"""Step 6 tests: maximin fair pick, tie-breaks, who is least happy and why, conflicts."""
import json
from pathlib import Path

from app.group import decide
from app.models import Listing, Roommate, Weights

ALL_ZERO = dict(rent=0, commute=0, laundry=0, parking=0, bedrooms=0)


def make_listing(**kw) -> Listing:
    base = dict(id="x", title="Test", rent_total_monthly=3000, bedrooms=2, walk_minutes=10,
                laundry="in_unit", parking="included")
    base.update(kw)
    return Listing(**base)


def person(name, budget=1500, **weights) -> Roommate:
    return Roommate(name=name, budget=budget, weights=Weights(**{**ALL_ZERO, **weights}))


WALKER = person("Walker", budget=2000, commute=5)
SAVER = person("Saver", budget=1300, rent=5)


def test_fairest_pick_protects_least_happy_roommate():
    # "close" is perfect for the walker and terrible for the saver; "fair" is decent for both.
    close = make_listing(id="close", rent_total_monthly=4000, walk_minutes=5)
    fair = make_listing(id="fair", rent_total_monthly=2600, walk_minutes=20)

    result = decide([close, fair], [WALKER, SAVER])
    assert result["pick"]["listing_id"] == "fair"
    assert result["favorites"] == {"Walker": "close", "Saver": "fair"}
    assert result["everyone_agrees"] is False
    assert any(c["listing_id"] == "close" for c in result["conflicts"])


def test_maximin_beats_a_higher_average():
    # "split" gives A 100 and B 30 (average 65); "even" gives both 50 (average 50). Maximin picks "even".
    split = make_listing(id="split", rent_total_monthly=1900, walk_minutes=31)
    even = make_listing(id="even", rent_total_monthly=2600, walk_minutes=25)
    a, b = person("A", budget=1300, rent=5), person("B", commute=5)
    result = decide([split, even], [a, b])
    by_id = {r["listing_id"]: r for r in result["ranking"]}
    assert by_id["split"]["avg_score"] == 65 and by_id["split"]["min_score"] == 30
    assert by_id["even"]["avg_score"] == 50 and by_id["even"]["min_score"] == 50
    assert result["pick"]["listing_id"] == "even"


def test_tie_goes_to_higher_average_then_more_known_facts():
    a = person("A", laundry=5)
    b = person("B", parking=5)
    # Both listings leave A at 0, so the minimum ties; B is happier with "high".
    same_min_low_avg = make_listing(id="low", laundry="none", parking="paid")   # A 0, B 50
    same_min_high_avg = make_listing(id="high", laundry="none", parking="included")  # A 0, B 100
    assert decide([same_min_low_avg, same_min_high_avg], [a, b])["pick"]["listing_id"] == "high"

    # Identical scores; "complete" knows all facts, "gaps" is missing bedrooms and commute.
    complete = make_listing(id="complete")
    gaps = make_listing(id="gaps", bedrooms=None, walk_minutes=None)
    for order in ([complete, gaps], [gaps, complete]):
        result = decide(order, [a, b])
        assert result["pick"]["listing_id"] == "complete"
        assert {r["listing_id"]: r["known_share"] for r in result["ranking"]} == {"complete": 1.0, "gaps": 0.6}


def test_least_happy_reasons_use_the_real_facts():
    listing = make_listing(id="p", laundry="shared", parking="paid")
    happy = person("Happy", commute=5)
    picky = person("Picky", laundry=3, parking=1)
    result = decide([listing], [happy, picky])

    lh = result["least_happy"]
    assert lh["roommate"] == "Picky"
    assert lh["gives_up_most_on"] == "laundry"
    assert lh["reasons"][0] == {"criterion": "laundry", "raw_value": "shared", "points_lost": 45.0}
    assert lh["reasons"][1]["criterion"] == "parking" and lh["reasons"][1]["raw_value"] == "paid"
    assert result["pick"]["scores"] == [{"roommate": "Happy", "score": 100.0}, {"roommate": "Picky", "score": 42.5}]


def test_perfect_pick_has_no_reasons():
    result = decide([make_listing()], [person("A", commute=5)])
    assert result["least_happy"]["reasons"] == []
    assert result["least_happy"]["gives_up_most_on"] is None
    assert result["everyone_agrees"] is True


def test_listing_with_no_usable_score_cannot_win():
    # Nobody's weighted criteria are known for "blank", so its worst case is unknown.
    blank = make_listing(id="blank", rent_total_monthly=None)
    weak = make_listing(id="weak", rent_total_monthly=3900)
    result = decide([blank, weak], [person("A", budget=1500, rent=5)])
    assert result["pick"]["listing_id"] == "weak"
    assert next(r for r in result["ranking"] if r["listing_id"] == "blank")["min_score"] is None


def test_listing_with_red_flags_loses_to_clean_one():
    scam = make_listing(id="scam", rent_total_monthly=1000, red_flags=["Deposit by wire before viewing"])
    clean = make_listing(id="clean", rent_total_monthly=3000)
    result = decide([scam, clean], [Roommate(name="A", budget=1500), Roommate(name="B", budget=1500)])
    assert result["pick"]["listing_id"] == "clean"


def test_partial_data_is_flagged_in_the_ranking():
    result = decide([make_listing(id="a", laundry="unknown"), make_listing(id="b")],
                    [Roommate(name="A", budget=1500)])
    rows = {r["listing_id"]: r for r in result["ranking"]}
    assert rows["a"]["partial_data"] and rows["a"]["unknown"] == ["laundry"]
    assert not rows["b"]["partial_data"]
    assert [r["rank"] for r in result["ranking"]] == [1, 2]


def test_changing_one_roommates_weights_can_flip_the_pick():
    # The demo story with the map's default roommates and real Google walk times:
    # Sam raises "laundry" from 3 to 5, and the fair pick moves from 424 Landfair (shared laundry)
    # to 1824 Fairburn (in-unit laundry). If demo data changes, rerun the search and update this.
    data = json.loads((Path(__file__).parent.parent / "data" / "demo_listings.json").read_text())
    listings = [Listing(**d) for d in data]
    alex = person("Alex", budget=1500, rent=5, commute=2, laundry=3, parking=1, bedrooms=3)
    jordan = person("Jordan", budget=1700, rent=3, commute=3, laundry=5, parking=2, bedrooms=3)

    def pick(sam_laundry):
        sam = person("Sam", budget=1900, rent=2, commute=5, laundry=sam_laundry, parking=4, bedrooms=3)
        return decide(listings, [alex, sam, jordan])["pick"]["listing_id"]

    assert pick(3) == "landfair-424"
    assert pick(5) == "fairburn-1824"


def test_each_roommate_is_judged_on_their_own_commute():
    # Same two listings; the beach-goer's commute favours "west", the campus walker's favours "east".
    west = make_listing(id="west", walk_minutes=40)
    east = make_listing(id="east", walk_minutes=10)
    campus = person("Campus", commute=5)
    beach = Roommate(name="Beach", budget=1500, weights=Weights(**{**ALL_ZERO, "commute": 5}),
                     place="Santa Monica Pier", travel_mode="BICYCLE")
    commutes = {(0, 0): 40, (1, 0): 10,   # Campus walker: listing order west, east.
                (0, 1): 10, (1, 1): 40}   # Beach biker: west is close to the beach.
    result = decide([west, east], [campus, beach], commutes)
    assert result["favorites"] == {"Campus": "east", "Beach": "west"}
    beach_row = next(p for p in result["ranking"][0]["per_roommate"] if p["roommate"] == "Beach")
    assert beach_row["commute_to"] == "Santa Monica Pier" and beach_row["travel_mode"] == "BICYCLE"
    # Whoever is least happy, their commute reason names where they go and how.
    reason = result["least_happy"]["reasons"][0]
    assert reason["criterion"] == "commute" and "travel_mode" in reason


def test_unknown_commute_for_one_roommate_is_excluded_not_guessed():
    listing = make_listing(id="a", laundry="none")
    beach = Roommate(name="Beach", budget=1500, weights=Weights(**{**ALL_ZERO, "commute": 5, "laundry": 1}),
                     place="Somewhere Google can't route", travel_mode="DRIVE")
    result = decide([listing], [beach], {(0, 0): None})
    row = result["ranking"][0]["per_roommate"][0]
    assert row["unknown"] == ["commute"] and row["score"] == 0  # Judged on laundry (none) only.
