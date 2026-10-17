"""Step 4: real distances from Google Maps Platform (never from the model).

For a listing we look up:
- walk and bike minutes to campus (Routes API), plus the listing's coordinates for the map,
- grocery stores nearby (Places API): how many are within 1 km in a straight line,
  and the real walk time to the nearest one (Routes API).

Every reply is cached in cache/maps/ by its exact request, so each lookup is paid for once
and the demo works with no network. Calls happen only here, on the backend, so the key is
never sent to the browser. With no key, or if a call fails, the value stays None ("unknown").
"""
import json
import math
import os
from typing import Optional

import httpx

from . import cache

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
PLACES_URL = "https://places.googleapis.com/v1/places:searchNearby"
DEFAULT_DESTINATION = "Royce Hall, UCLA, Los Angeles, CA"

GROCERY_TYPES = ["grocery_store", "supermarket"]
GROCERY_SEARCH_METERS = 2000  # Look this far for the nearest store.
GROCERY_NEARBY_METERS = 1000  # "Nearby" count: stores within 1 km in a straight line (about a 12-minute walk).

Place = dict  # {"address": "..."} or {"lat": .., "lng": ..}


def _key() -> Optional[str]:
    return os.getenv("GOOGLE_MAPS_API_KEY") or None


def destination() -> str:
    return os.getenv("DESTINATION", DEFAULT_DESTINATION)


def _waypoint(place: Place) -> dict:
    if place.get("address"):
        return {"address": place["address"]}
    return {"location": {"latLng": {"latitude": place["lat"], "longitude": place["lng"]}}}


def _post(kind: str, url: str, field_mask: str, body: dict) -> Optional[dict]:
    """One cached Google call. Returns the JSON reply, or None with no key or on failure (not cached)."""
    cache_key = url + "|" + json.dumps(body, sort_keys=True)
    cached = cache.get(kind, cache_key)
    if cached is not None:
        return cached
    api_key = _key()
    if not api_key:
        return None
    try:
        r = httpx.post(url, headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": field_mask},
                       json=body, timeout=20)
        r.raise_for_status()
        reply = r.json()
    except (httpx.HTTPError, ValueError):
        return None  # Shown as "unknown"; a later request can try again.
    cache.put(kind, cache_key, reply)
    return reply


def route(origin: Place, dest: Place, mode: str) -> Optional[dict]:
    """{minutes, meters, origin_lat, origin_lng} for WALK or BICYCLE, or None."""
    reply = _post("maps", ROUTES_URL, "routes.duration,routes.distanceMeters,routes.legs.startLocation",
                  {"origin": _waypoint(origin), "destination": _waypoint(dest), "travelMode": mode})
    routes = (reply or {}).get("routes") or []
    if not routes or "duration" not in routes[0]:
        return None
    start = routes[0]["legs"][0]["startLocation"]["latLng"]
    return {
        "minutes": round(int(routes[0]["duration"].rstrip("s")) / 60, 1),  # Duration comes back like "1083s".
        "meters": routes[0].get("distanceMeters"),
        "origin_lat": start["latitude"],
        "origin_lng": start["longitude"],
    }


def _meters_between(lat1, lng1, lat2, lng2) -> float:
    """Straight-line distance on the Earth's surface (haversine), used only for the 1 km count."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def groceries(lat: float, lng: float) -> dict:
    """{grocery_count, nearest_grocery, grocery_walk_minutes} around a point. Values None if unknown."""
    out = {"grocery_count": None, "nearest_grocery": None, "grocery_walk_minutes": None}
    reply = _post("maps", PLACES_URL, "places.displayName,places.location", {
        # Main category only, so places merely tagged "grocery" (offices, bars) don't count.
        "includedPrimaryTypes": GROCERY_TYPES,
        "maxResultCount": 20,
        "rankPreference": "DISTANCE",
        "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lng},
                                           "radius": GROCERY_SEARCH_METERS}},
    })
    if reply is None:
        return out
    places = reply.get("places") or []
    out["grocery_count"] = sum(
        1 for p in places
        if _meters_between(lat, lng, p["location"]["latitude"], p["location"]["longitude"]) <= GROCERY_NEARBY_METERS
    )
    if places:
        nearest = places[0]
        out["nearest_grocery"] = nearest.get("displayName", {}).get("text")
        walk = route({"lat": lat, "lng": lng},
                     {"lat": nearest["location"]["latitude"], "lng": nearest["location"]["longitude"]}, "WALK")
        out["grocery_walk_minutes"] = walk["minutes"] if walk else None
    return out


def lookup(place: Place) -> dict:
    """Everything the map card needs from Google for one listing. Missing values stay None."""
    campus = {"address": destination()}
    walk = route(place, campus, "WALK")
    bike = route(place, campus, "BICYCLE")
    lat = place.get("lat") if place.get("lat") is not None else (walk or {}).get("origin_lat")
    lng = place.get("lng") if place.get("lng") is not None else (walk or {}).get("origin_lng")
    result = {
        "lat": lat,
        "lng": lng,
        "walk_minutes": walk["minutes"] if walk else None,
        "bike_minutes": bike["minutes"] if bike else None,
    }
    result.update(groceries(lat, lng) if lat is not None and lng is not None else
                  {"grocery_count": None, "nearest_grocery": None, "grocery_walk_minutes": None})
    return result
