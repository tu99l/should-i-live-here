"""Step 4 tests. Google is replaced with fake replies, so these cost nothing and need no key."""
import httpx
import pytest

from app import cache, maps_lookup

HOME = {"lat": 34.0697, "lng": -118.4526}
NEAR_STORE = {"latitude": 34.0705, "longitude": -118.4500}   # ~250 m away
FAR_STORE = {"latitude": 34.0610, "longitude": -118.4420}    # ~1.4 km away


class FakeGoogle:
    """Answers Routes and Places calls and counts them."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, url, headers, json, timeout):
        self.calls.append((url, json))
        if self.fail:
            raise httpx.ConnectError("no network")
        if "places" in url:
            body = {"places": [{"displayName": {"text": "Near Market"}, "location": NEAR_STORE},
                               {"displayName": {"text": "Far Foods"}, "location": FAR_STORE}]}
        else:
            seconds = {"WALK": 1083, "BICYCLE": 360}[json["travelMode"]]
            if "location" in json["destination"]:  # Walk to a grocery store.
                seconds = 240
            body = {"routes": [{"duration": f"{seconds}s", "distanceMeters": 1294,
                                "legs": [{"startLocation": {"latLng": {"latitude": HOME["lat"], "longitude": HOME["lng"]}}}]}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "fake-key")


def use(monkeypatch, fake):
    monkeypatch.setattr(maps_lookup.httpx, "post", fake)
    return fake


def test_lookup_fills_every_field(monkeypatch):
    use(monkeypatch, FakeGoogle())
    r = maps_lookup.lookup({"address": "424 Landfair Ave, Los Angeles, CA"})
    assert r["walk_minutes"] == 18.1 and r["bike_minutes"] == 6.0
    assert (r["lat"], r["lng"]) == (HOME["lat"], HOME["lng"])  # Taken from the route, for the map.
    assert r["nearest_grocery"] == "Near Market" and r["grocery_walk_minutes"] == 4.0
    assert r["grocery_count"] == 1  # Only the store within 1 km counts.


def test_every_reply_is_cached(monkeypatch):
    fake = use(monkeypatch, FakeGoogle())
    first = maps_lookup.lookup({"address": "424 Landfair Ave"})
    n = len(fake.calls)
    assert maps_lookup.lookup({"address": "424 Landfair Ave"}) == first
    assert len(fake.calls) == n  # Second lookup made no paid calls.


def test_no_key_means_unknown_not_guessed(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY")
    fake = use(monkeypatch, FakeGoogle())
    r = maps_lookup.lookup({"address": "424 Landfair Ave"})
    assert all(v is None for v in r.values())
    assert fake.calls == []


def test_network_failure_means_unknown_and_is_not_cached(monkeypatch):
    use(monkeypatch, FakeGoogle(fail=True))
    assert maps_lookup.lookup({"address": "424 Landfair Ave"})["walk_minutes"] is None
    use(monkeypatch, FakeGoogle())
    assert maps_lookup.lookup({"address": "424 Landfair Ave"})["walk_minutes"] == 18.1  # Retried later.


def test_known_coordinates_are_kept(monkeypatch):
    fake = use(monkeypatch, FakeGoogle())
    r = maps_lookup.lookup({"lat": 34.05, "lng": -118.43})
    assert (r["lat"], r["lng"]) == (34.05, -118.43)
    assert fake.calls[0][1]["origin"] == {"location": {"latLng": {"latitude": 34.05, "longitude": -118.43}}}


def test_straight_line_distance():
    # About 1.11 km per 0.01 degree of latitude.
    assert maps_lookup._meters_between(34.0, -118.0, 34.01, -118.0) == pytest.approx(1112, abs=5)


# ---------- Per-roommate commutes (Route Matrix) ----------

class FakeMatrix:
    """Answers Route Matrix calls: origin i takes (i + 1) * 10 minutes; origin 2 has no route."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, headers, json, timeout):
        assert "computeRouteMatrix" in url
        self.calls.append(json)
        out = []
        for i, _ in enumerate(json["origins"]):
            el = {"originIndex": i, "destinationIndex": 0, "status": {}}
            if i == 2:
                el["condition"] = "ROUTE_NOT_FOUND"
            else:
                el.update(condition="ROUTE_EXISTS", duration=f"{(i + 1) * 600}s")
            out.append(el)
        return httpx.Response(200, json=out, request=httpx.Request("POST", url))


def test_matrix_answers_each_origin_and_caches_each(monkeypatch):
    fake = use(monkeypatch, FakeMatrix())
    origins = [{"lat": 34.0, "lng": -118.0}, {"lat": 34.1, "lng": -118.1}, {"address": "Nowhere"}]
    assert maps_lookup.commute_minutes(origins, "Santa Monica Pier", "BICYCLE") == [10.0, 20.0, None]
    assert maps_lookup.commute_minutes(origins, "Santa Monica Pier", "BICYCLE") == [10.0, 20.0, None]
    assert len(fake.calls) == 1  # "No route" is cached too, so the second ask is free.
    maps_lookup.commute_minutes(origins[:1], "Santa Monica Pier", "DRIVE")
    assert len(fake.calls) == 2  # A different travel mode is a different question.


def test_matrix_error_for_one_pair_is_unknown_and_not_cached(monkeypatch):
    def broken(url, headers, json, timeout):
        body = [{"originIndex": 0, "destinationIndex": 0, "status": {"code": 5, "message": "NOT_FOUND"}}]
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))
    use(monkeypatch, broken)
    assert maps_lookup.commute_minutes([{"address": "x"}], "Pier", "WALK") == [None]
    use(monkeypatch, FakeMatrix())
    assert maps_lookup.commute_minutes([{"address": "x"}], "Pier", "WALK") == [10.0]


def test_commutes_for_reuses_saved_campus_times_and_groups_places(monkeypatch):
    from app.models import Listing, Roommate
    fake = use(monkeypatch, FakeMatrix())
    listings = [Listing(id="a", lat=34.0, lng=-118.0, walk_minutes=18, bike_minutes=8),
                Listing(id="b", lat=34.1, lng=-118.1, walk_minutes=40, bike_minutes=14)]
    roommates = [Roommate(name="Campus walker", budget=1500),
                 Roommate(name="Campus biker", budget=1500, travel_mode="BICYCLE"),
                 Roommate(name="Beach biker", budget=1500, place="Santa Monica Pier", travel_mode="BICYCLE"),
                 Roommate(name="Beach biker 2", budget=1500, place="Santa Monica Pier", travel_mode="BICYCLE")]
    c = maps_lookup.commutes_for(listings, roommates)
    assert c[(0, 0)] == 18 and c[(1, 0)] == 40   # Saved walk times, no call.
    assert c[(0, 1)] == 8 and c[(1, 1)] == 14    # Saved bike times, no call.
    assert c[(0, 2)] == 10 and c[(1, 2)] == 20   # From Google.
    assert c[(0, 3)] == 10
    assert len(fake.calls) == 1  # Both beach bikers share one call.
