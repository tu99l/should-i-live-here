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
