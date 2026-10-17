"""Group pick tests (moved from test_scoring.py; step 6 adds more)."""
from app.group import decide
from app.models import Listing, Roommate, Weights

ALL_ZERO = dict(rent=0, commute=0, laundry=0, parking=0, bedrooms=0)


def make_listing(**kw) -> Listing:
    base = dict(id="x", title="Test", rent_total_monthly=3000, bedrooms=2, walk_minutes=10,
                laundry="in_unit", parking="included")
    base.update(kw)
    return Listing(**base)


def test_fairest_pick_protects_least_happy_roommate():
    # "close" is perfect for the walker and terrible for the saver; "fair" is decent for both.
    close = make_listing(id="close", rent_total_monthly=4000, walk_minutes=5)
    fair = make_listing(id="fair", rent_total_monthly=2600, walk_minutes=20)
    walker = Roommate(name="Walker", budget=2000, weights=Weights(**{**ALL_ZERO, "commute": 5}))
    saver = Roommate(name="Saver", budget=1300, weights=Weights(**{**ALL_ZERO, "rent": 5}))

    result = decide([close, fair], [walker, saver])
    assert result["pick"]["listing_id"] == "fair"
    assert result["favorites"] == {"Walker": "close", "Saver": "fair"}
    assert any(c["listing_id"] == "close" for c in result["conflicts"])
    assert result["least_happy"]["gives_up_most_on"] in ("rent", "commute")


def test_listing_with_red_flags_loses_to_clean_one():
    scam = make_listing(id="scam", rent_total_monthly=1000, red_flags=["Deposit by wire before viewing"])
    clean = make_listing(id="clean", rent_total_monthly=3000)
    result = decide([scam, clean], [Roommate(name="A", budget=1500), Roommate(name="B", budget=1500)])
    assert result["pick"]["listing_id"] == "clean"


def test_partial_data_is_flagged_in_the_ranking():
    result = decide([make_listing(id="a", laundry="unknown"), make_listing(id="b")],
                    [Roommate(name="A", budget=1500)])
    flags = {r["listing_id"]: r["partial_data"] for r in result["ranking"]}
    assert flags == {"a": True, "b": False}
