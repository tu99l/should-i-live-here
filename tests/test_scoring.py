from app.models import Listing, Roommate, Weights
from app.scoring import decide, rent_per_person, score_for_roommate


def make_listing(**kw) -> Listing:
    base = dict(id="x", title="Test", price=3000, price_type="whole_unit", walk_minutes=10,
                laundry="in_unit", parking="included", grocery_walk_minutes=5)
    base.update(kw)
    return Listing(**base)


def test_rent_per_person_splits_whole_unit_only():
    assert rent_per_person(make_listing(price=3000, price_type="whole_unit"), 2) == 1500
    assert rent_per_person(make_listing(price=1200, price_type="per_bed"), 2) == 1200
    assert rent_per_person(make_listing(price_type="unknown"), 2) is None


def test_score_changes_when_weights_change():
    listing = make_listing(walk_minutes=40)  # worst possible walk
    cares = Roommate(name="A", budget=1500, weights=Weights(walk=5))
    doesnt = Roommate(name="B", budget=1500, weights=Weights(walk=0))
    assert score_for_roommate(listing, cares, 2)["score"] < score_for_roommate(listing, doesnt, 2)["score"]


def test_unknown_facts_are_flagged_not_guessed():
    result = score_for_roommate(make_listing(laundry="unknown"), Roommate(name="A", budget=1500), 2)
    laundry = next(b for b in result["breakdown"] if b["factor"] == "laundry")
    assert laundry["unknown"] and laundry["factor_score"] is None


def test_fairest_pick_protects_least_happy_roommate():
    # "close" is perfect for the walker and terrible for the saver; "fair" is decent for both.
    close = make_listing(id="close", price=4000, walk_minutes=5)
    fair = make_listing(id="fair", price=2600, walk_minutes=20)
    walker = Roommate(name="Walker", budget=2000, weights=Weights(rent=0, walk=5, laundry=0, parking=0, grocery=0))
    saver = Roommate(name="Saver", budget=1300, weights=Weights(rent=5, walk=0, laundry=0, parking=0, grocery=0))

    result = decide([close, fair], [walker, saver])
    assert result["pick"]["listing_id"] == "fair"
    assert result["favorites"] == {"Walker": "close", "Saver": "fair"}
    assert any(c["listing_id"] == "close" for c in result["conflicts"])


def test_listing_with_red_flags_loses_to_clean_one():
    scam = make_listing(id="scam", price=1000, red_flags=["Deposit by wire before viewing"])
    clean = make_listing(id="clean", price=3000)
    result = decide([scam, clean], [Roommate(name="A", budget=1500), Roommate(name="B", budget=1500)])
    assert result["pick"]["listing_id"] == "clean"
