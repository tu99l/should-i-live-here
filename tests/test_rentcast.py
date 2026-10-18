"""RentCast search, the per-room trap, own bathrooms and commutes to any place. Nothing calls the internet."""
import httpx
import pytest

from app import cache, maps_lookup, rentcast
from app.group import decide
from app.models import Listing, Roommate, Want, Weights
from app.scoring import score_listing


@pytest.fixture(autouse=True)
def temp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("RENTCAST_API_KEY", "fake-key")


def rec(i, price, beds, baths=2, lat=34.07, lng=-118.44, line1=None, **kw):
    return {"id": f"{i} Test St, Los Angeles, CA 90024", "formattedAddress": f"{i} Test St, Los Angeles, CA 90024",
            "addressLine1": line1 or f"{i} Test St", "latitude": lat, "longitude": lng, "price": price,
            "bedrooms": beds, "bathrooms": baths, "propertyType": "Apartment", "squareFootage": 1000 + i, **kw}


# Twelve ordinary 3-bedrooms at $6,000 ($2,000 per bedroom), plus one big house at a one-room price.
AREA = [rec(i, 6000, 3, lat=34.07 + i * 0.001) for i in range(12)] + [rec(99, 1080, 7, baths=3)]


class FakeRentCast:
    def __init__(self, reply=AREA, status=200):
        self.reply, self.status, self.calls = reply, status, []

    def __call__(self, url, params, headers, timeout):
        self.calls.append(params)
        body = self.reply if self.status == 200 else {"message": "subscription inactive"}
        return httpx.Response(self.status, json=body, request=httpx.Request("GET", url))


def use(monkeypatch, fake):
    monkeypatch.setattr(rentcast.httpx, "get", fake)
    return fake


def test_one_room_price_on_a_big_place_is_flagged_not_split(monkeypatch):
    use(monkeypatch, FakeRentCast())
    out = rentcast.search(34.07, -118.44, 2)
    house = next(l for l in out["listings"] if l.bedrooms == 7)
    assert house.price_check == "possible_per_room"
    assert house.rent_total_monthly is None and house.listed_price == 1080  # Unknown, never $154 each.
    assert "may be for one room" in house.red_flags[0] and "$1,080 for 7 bedrooms" in house.red_flags[0]
    normal = next(l for l in out["listings"] if l.bedrooms == 3)
    assert normal.rent_total_monthly == 6000 and normal.price_check is None and normal.red_flags == []
    assert out["flagged_per_room"] == 1 and out["typical_rent_per_bedroom"] == 2000


def test_rentcast_listings_leave_laundry_and_parking_unknown(monkeypatch):
    use(monkeypatch, FakeRentCast())
    l = rentcast.search(34.07, -118.44, 2)["listings"][0]
    assert l.laundry == "unknown" and l.parking == "unknown" and l.source == "rentcast"
    assert l.id.startswith("rc-") and l.lat is not None and l.property_type == "Apartment"


def test_too_few_comparables_means_no_flag(monkeypatch):
    use(monkeypatch, FakeRentCast([rec(1, 6000, 3), rec(2, 1080, 7)]))
    out = rentcast.search(34.07, -118.44, 2)
    assert out["typical_rent_per_bedroom"] is None and out["flagged_per_room"] == 0  # Can't tell, so no claim.


def test_filters_dedupe_and_nearest_first(monkeypatch):
    twin = rec(3, 6000, 3, lat=34.073, line1="3 Test St")  # Same unit listed twice.
    pricey = rec(50, 9000, 3, lat=34.0705)                  # $3,000 per person.
    studio = rec(51, 2000, 0)
    use(monkeypatch, FakeRentCast(AREA + [twin, pricey, studio]))
    out = rentcast.search(34.07, -118.44, 2, min_bedrooms=3, max_rent_per_person=2500, limit=5)
    ids = [l.id for l in out["listings"]]
    assert len(ids) == len(set(ids)) == 5
    assert all(l.bedrooms >= 3 for l in out["listings"])
    assert all(l.title != "50 Test St" for l in out["listings"])
    assert any(l.price_check for l in out["listings"])  # Flagged ones are kept, with their warning.
    assert out["listings"][0].lat == 34.07  # Nearest first.


def test_each_area_is_requested_once_then_cached(monkeypatch):
    fake = use(monkeypatch, FakeRentCast())
    rentcast.search(34.07, -118.44, 2, min_bedrooms=3)
    rentcast.search(34.07, -118.44, 2, min_bedrooms=2, max_rent_per_person=1500)  # New filters, same area.
    assert len(fake.calls) == 1 and fake.calls[0]["limit"] == 500


def test_errors_are_explained_and_not_cached(monkeypatch):
    fake = use(monkeypatch, FakeRentCast(status=403))
    with pytest.raises(rentcast.RentCastError, match="subscription inactive"):
        rentcast.search(34.07, -118.44, 2)
    with pytest.raises(rentcast.RentCastError):
        rentcast.search(34.07, -118.44, 2)
    assert len(fake.calls) == 2
    monkeypatch.delenv("RENTCAST_API_KEY")
    with pytest.raises(rentcast.RentCastError, match="RENTCAST_API_KEY"):
        rentcast.search(1.0, 2.0, 2)


def test_flagged_listing_is_never_the_pick_or_a_favorite():
    flagged = Listing(id="room", title="Room", rent_total_monthly=None, listed_price=1080, bedrooms=7,
                      walk_minutes=5, laundry="in_unit", parking="included", red_flags=["may be one room"])
    normal = Listing(id="ok", title="OK", rent_total_monthly=4500, bedrooms=3, walk_minutes=20,
                     laundry="shared", parking="paid")
    people = [Roommate(name=n, budget=1500) for n in ("A", "B")]
    result = decide([flagged, normal], people)
    assert result["pick"]["listing_id"] == "ok"
    assert set(result["favorites"].values()) == {"ok"}


# ---------- Own bathroom ----------

def bath_fan(name):
    return Roommate(name=name, budget=1500, weights=Weights(rent=0, commute=0, laundry=0, parking=0, bedrooms=0),
                    wants=[Want(kind="bathroom", what="own bathroom", weight=5)])


def test_own_bathroom_needs_one_each_plus_one_shared():
    from app import wishes
    two_baths = Listing(id="2", bathrooms=2, lat=1, lng=1)
    three_baths = Listing(id="3", bathrooms=3, lat=1, lng=1)
    group = [bath_fan("John"), bath_fan("Jake"), Roommate(name="Freddy", budget=1500)]
    facts = wishes.want_facts_for([two_baths, three_baths], group)
    assert facts[(0, 0)] == [{"bathrooms": 2, "needed": 3}]  # John + Jake own, Freddy shares one.
    assert score_listing(two_baths, group[0], 3, want_facts=facts[(0, 0)])["score"] == 0
    row = score_listing(three_baths, group[0], 3, want_facts=facts[(1, 0)])
    assert row["score"] == 100 and row["breakdown"][-1]["criterion"] == "own bathroom"


def test_own_bathroom_unknown_when_listing_doesnt_say():
    out = score_listing(Listing(id="x"), bath_fan("John"), 2, want_facts=[{"bathrooms": None, "needed": 2}])
    assert "own bathroom" in out["unknown"] and out["score"] is None  # Nothing known: no score, no guess.


def test_reading_own_bathroom_needs_their_words(monkeypatch):
    import json
    from app import wishes
    text = "I need my own bathroom and to be near a gym"
    good = json.dumps({"own_bathroom": "must", "own_bathroom_quote": "my own bathroom"})
    w = wishes.validate_wishes(good, text)
    assert [(x.kind, x.what, x.weight) for x in w.wants] == [("bathroom", "own bathroom", 5)]
    made_up = json.dumps({"own_bathroom": "must", "own_bathroom_quote": "near a gym"})
    assert wishes.validate_wishes(made_up, text).wants == []


# ---------- Commutes to any place, and finding a place ----------

def test_saved_minutes_are_reused_only_for_the_same_place(monkeypatch):
    asked = []
    monkeypatch.setattr(maps_lookup, "commute_minutes",
                        lambda origins, dest, mode: asked.append((len(origins), dest)) or [12.0] * len(origins))
    demo = Listing(id="demo", walk_minutes=18.1, lat=1, lng=1)                      # Measured to campus.
    live = Listing(id="live", walk_minutes=None, lat=2, lng=2)                       # Not measured yet.
    other = Listing(id="sm", walk_minutes=5.0, commute_to="Santa Monica Pier", lat=3, lng=3)
    walker = Roommate(name="A", budget=1500)
    out = maps_lookup.commutes_for([demo, live, other], [walker])
    assert out[(0, 0)] == 18.1                       # Reused.
    assert out[(1, 0)] == 12.0 and out[(2, 0)] == 12.0  # Asked from Google.
    assert asked == [(2, maps_lookup.destination())]


def test_find_place_returns_googles_answer_or_none(monkeypatch):
    def fake(url, headers, json, timeout):
        body = {"places": [{"displayName": {"text": "Santa Monica Pier"}, "formattedAddress": "200 Santa Monica Pier",
                            "location": {"latitude": 34.0, "longitude": -118.5}}]} if "Pier" in json["textQuery"] else {}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "fake")
    monkeypatch.setattr(maps_lookup.httpx, "post", fake)
    assert maps_lookup.find_place("santa monica  Pier") == {
        "name": "Santa Monica Pier", "formatted_address": "200 Santa Monica Pier", "lat": 34.0, "lng": -118.5}
    assert maps_lookup.find_place("zzqx nowhere") is None
    assert maps_lookup.find_place("   ") is None
