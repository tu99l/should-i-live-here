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


SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
NEAR_SEARCH_METERS = 3000  # Look around the listing this far (a bias: Google may still return farther places).

# Common words -> Google place type, so "gym" finds gyms and not martial-arts schools.
# Anything else (a brand like "Trader Joe's", "dog park") is searched as plain text.
PLACE_TYPES = {
    "gym": "gym", "fitness center": "gym", "grocery store": "grocery_store", "grocery": "grocery_store",
    "supermarket": "supermarket", "park": "park", "cafe": "cafe", "coffee shop": "coffee_shop",
    "library": "library", "pharmacy": "pharmacy", "church": "church", "laundromat": "laundromat",
    "bar": "bar", "restaurant": "restaurant", "hospital": "hospital", "bank": "bank",
    "post office": "post_office", "train station": "train_station", "bus stop": "bus_stop",
}


def _place_type(what: str) -> Optional[str]:
    w = " ".join(what.casefold().split()).removeprefix("a ").removeprefix("the ")
    return PLACE_TYPES.get(w) or PLACE_TYPES.get(w.removesuffix("s"))


def nearest_place(lat: float, lng: float, what: str) -> Optional[dict]:
    """The nearest place matching any text ("gym", "Trader Joe's", "dog park") and the real walk there.

    Returns {name, walk_minutes} or None if Google found nothing or can't be reached.
    The search text is the roommate's own words; Google decides what matches, we never guess.
    """
    body = {
        "textQuery": what,
        "pageSize": 5,
        "rankPreference": "DISTANCE",
        "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng},
                                    "radius": NEAR_SEARCH_METERS}},
    }
    place_type = _place_type(what)
    if place_type:
        body.update(includedType=place_type, strictTypeFiltering=True)
    # Own cache folder ("near"), since this asks for primaryType too.
    reply = _post("near", SEARCH_TEXT_URL, "places.displayName,places.location,places.primaryType", body)
    places = (reply or {}).get("places") or []
    if place_type:
        # Prefer places whose MAIN category is the one asked for (a martial-arts school also tagged "gym" loses).
        places = [p for p in places if p.get("primaryType") == place_type] or places
    if not places:
        return None
    # Nearest in a straight line first, then the real walk to that one.
    nearest = min(places, key=lambda p: _meters_between(lat, lng, p["location"]["latitude"],
                                                        p["location"]["longitude"]))
    walk = route({"lat": lat, "lng": lng},
                 {"lat": nearest["location"]["latitude"], "lng": nearest["location"]["longitude"]}, "WALK")
    if walk is None:
        return None
    return {"name": nearest.get("displayName", {}).get("text"), "walk_minutes": walk["minutes"]}


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


# ---------- Per-roommate commutes (step 6b: each roommate has their own place and travel mode) ----------

MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
MATRIX_BATCH = 50  # Origins per call; Google allows up to 625 elements (100 for transit).


def commute_minutes(origins: list[Place], dest: str, mode: str) -> list[Optional[float]]:
    """Minutes from each origin to one destination by one travel mode. None where unknown.

    Uses Google's Route Matrix (many origins in one call). Each origin's answer is cached on
    its own, so adding a listing or changing a slider never re-pays for known routes.
    """
    keys = ["matrix|" + json.dumps({"o": _waypoint(o), "d": dest, "m": mode}, sort_keys=True) for o in origins]
    out: list[Optional[float]] = [None] * len(origins)
    missing = []
    for i, k in enumerate(keys):
        hit = cache.get("maps", k)
        if hit is not None:
            out[i] = hit["minutes"]
        else:
            missing.append(i)

    api_key = _key()
    for start in range(0, len(missing) if api_key else 0, MATRIX_BATCH):
        batch = missing[start:start + MATRIX_BATCH]
        body = {"origins": [{"waypoint": _waypoint(origins[i])} for i in batch],
                "destinations": [{"waypoint": {"address": dest}}],
                "travelMode": mode}
        try:
            r = httpx.post(MATRIX_URL, json=body, timeout=30, headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "originIndex,destinationIndex,duration,condition,status"})
            r.raise_for_status()
            elements = r.json()
        except (httpx.HTTPError, ValueError):
            continue  # Unknown for now; not cached, so a later request can try again.
        for el in elements:
            if (el.get("status") or {}).get("code"):
                continue  # Google reported an error for this pair: unknown, not cached.
            i = batch[el["originIndex"]]
            if el.get("condition") == "ROUTE_EXISTS" and "duration" in el:
                out[i] = round(int(el["duration"].rstrip("s")) / 60, 1)
            cache.put("maps", keys[i], {"minutes": out[i]})  # "No route" is a real answer, so it is cached too.
    return out


def commutes_for(listings, roommates) -> dict[tuple[int, int], Optional[float]]:
    """{(listing index, roommate index): minutes} for each roommate's own place and travel mode.

    A roommate with no place set uses the default destination (campus). For walking or biking
    there, the minutes already saved on each listing are reused, so the demo needs no calls.
    """
    default = destination()
    result: dict[tuple[int, int], Optional[float]] = {}
    groups: dict[tuple[str, str], list[int]] = {}
    for ri, r in enumerate(roommates):
        place = (r.place or "").strip()
        if not place and r.travel_mode in ("WALK", "BICYCLE"):
            field = "walk_minutes" if r.travel_mode == "WALK" else "bike_minutes"
            for li, l in enumerate(listings):
                result[(li, ri)] = getattr(l, field)
        else:
            groups.setdefault((place or default, r.travel_mode), []).append(ri)

    for (dest, mode), roommate_indexes in groups.items():
        located = [li for li, l in enumerate(listings) if (l.lat is not None and l.lng is not None) or l.address]
        origins = [{"lat": listings[li].lat, "lng": listings[li].lng} if listings[li].lat is not None
                   else {"address": listings[li].address} for li in located]
        minutes = dict(zip(located, commute_minutes(origins, dest, mode)))
        for ri in roommate_indexes:
            for li in range(len(listings)):
                result[(li, ri)] = minutes.get(li)
    return result
