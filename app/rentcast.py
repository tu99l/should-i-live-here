"""Real rental listings near a place, from the RentCast API (an official data API, not scraping).

One RentCast request returns up to 500 active long-term rentals in a circle around a point.
Each search is cached in cache/rentcast/ by its exact parameters, so the same area is paid for
once (the free plan has 50 requests a month) and the demo works with no network.

What RentCast gives: address, map location, rent, bedrooms, bathrooms, property type, size.
What it does NOT give: laundry, parking, description, photos. Those stay "unknown"; we never guess.

The per-room trap: some listings show the price of ONE room in a shared house next to the whole
house's bedroom count ("7 bedrooms, $1,080"). Splitting that price would be badly wrong. So a
listing whose price per bedroom is far below the area's typical price per bedroom is flagged
(price_check = "possible_per_room"): its rent per person is left unknown, the listed price is kept
as listed_price, and a red flag tells the user to check it. Red-flagged listings only win the fair
pick if every listing has a flag (group.py).
"""
import json
import math
import os
import statistics
from typing import Optional

import httpx

from . import cache
from .models import Listing

API_URL = "https://api.rentcast.io/v1/listings/rental/long-term"
MAX_PER_REQUEST = 500

# Flag a listing when its price per bedroom is under this share of the area's typical (median)
# price per bedroom. Tuned on 500 real listings near UCLA (Oct 2026): typical was $2,209 per bedroom,
# and every listing under 40% of that ($880) was a big place at a one-room price.
PER_ROOM_SHARE = 0.4
MIN_COMPARABLES = 10  # Need at least this many 2+ bedroom listings to know what "typical" is.


class RentCastError(RuntimeError):
    pass


def _key() -> Optional[str]:
    return os.getenv("RENTCAST_API_KEY") or None


def search_raw(lat: float, lng: float, radius_miles: float) -> list[dict]:
    """Active rentals in a circle, straight from RentCast (cached). Raises RentCastError if it can't."""
    params = {"latitude": round(lat, 5), "longitude": round(lng, 5), "radius": radius_miles,
              "status": "Active", "limit": MAX_PER_REQUEST}
    key = "rental|" + json.dumps(params, sort_keys=True)
    hit = cache.get("rentcast", key)
    if hit is not None:
        return hit
    api_key = _key()
    if not api_key:
        raise RentCastError("RENTCAST_API_KEY is not set in .env.")
    try:
        r = httpx.get(API_URL, params=params, timeout=60,
                      headers={"X-Api-Key": api_key, "Accept": "application/json"})
    except httpx.HTTPError as e:
        raise RentCastError(f"Could not reach RentCast: {e}") from None
    if r.status_code != 200:
        try:
            msg = r.json().get("message") or r.text
        except ValueError:
            msg = r.text
        raise RentCastError(f"RentCast said {r.status_code}: {msg[:200]}")
    listings = r.json()
    cache.put("rentcast", key, listings)  # Only good replies are cached.
    return listings


def typical_price_per_bedroom(raw: list[dict]) -> Optional[float]:
    """Median monthly rent per bedroom among 2+ bedroom listings in the search, or None if too few."""
    per_bed = [x["price"] / x["bedrooms"] for x in raw
               if x.get("price") and (x.get("bedrooms") or 0) >= 2]
    return statistics.median(per_bed) if len(per_bed) >= MIN_COMPARABLES else None


def _miles(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * 3958.8 * math.asin(math.sqrt(a))


def to_listing(x: dict, typical_per_bed: Optional[float]) -> Listing:
    """One RentCast record -> our Listing. Missing facts stay None / "unknown"."""
    price = x.get("price")
    beds = x.get("bedrooms")
    street = x.get("addressLine1") or x.get("formattedAddress") or "Listing"
    title = street + (f" {x['addressLine2']}" if x.get("addressLine2") else "")
    listing = Listing(
        id="rc-" + str(x.get("id", title)).replace(" ", "-")[:80],
        title=title,
        address=x.get("formattedAddress"),
        rent_total_monthly=price,
        listed_price=price,
        bedrooms=beds,
        bathrooms=x.get("bathrooms"),
        lat=x.get("latitude"),
        lng=x.get("longitude"),
        property_type=x.get("propertyType"),
        square_feet=x.get("squareFootage"),
        source="rentcast",
        # Laundry, parking, utilities: RentCast doesn't say, so they stay unknown.
    )
    if price and beds and beds >= 2 and typical_per_bed and price / beds < PER_ROOM_SHARE * typical_per_bed:
        listing.rent_total_monthly = None  # Don't split a price that may be for one room.
        listing.price_check = "possible_per_room"
        listing.red_flags.append(
            f"Price may be for one room, not the whole place: ${price:,.0f} for {beds} bedrooms, "
            f"while a typical place nearby is about ${typical_per_bed * beds:,.0f}. Check the listing.")
    return listing


def search(lat: float, lng: float, radius_miles: float = 2, min_bedrooms: int = 1,
           max_rent_per_person: Optional[float] = None, limit: int = 40) -> dict:
    """Listings near a point for a group, nearest first.

    Filters (done here, on the cached reply, so changing them never costs a request):
    at least `min_bedrooms`, and rent per person (rent / bedrooms) at most `max_rent_per_person`.
    Flagged per-room listings are kept, with their warning, so the user sees them and decides.
    `limit` caps how many we return, which also caps the Google lookups each one triggers.
    """
    raw = search_raw(lat, lng, radius_miles)
    typical = typical_price_per_bedroom(raw)
    picked, seen = [], set()
    for x in raw:
        beds = x.get("bedrooms")
        if beds is None or beds < min_bedrooms or x.get("latitude") is None:
            continue
        # The same unit is sometimes listed twice ("10974 Strathmore Dr" and "... Apt A", same price and size).
        same = (x.get("addressLine1"), x.get("price"), beds, x.get("bathrooms"), x.get("squareFootage"))
        if same in seen:
            continue
        seen.add(same)
        listing = to_listing(x, typical)
        if (max_rent_per_person and listing.rent_total_monthly is not None
                and listing.rent_total_monthly / beds > max_rent_per_person):
            continue
        picked.append((_miles(lat, lng, listing.lat, listing.lng), listing))
    picked.sort(key=lambda p: p[0])
    shown = [listing for _, listing in picked[:limit]]
    return {
        "found": len(raw),
        "matching": len(picked),
        "shown": len(shown),
        "flagged_per_room": sum(1 for listing in shown if listing.price_check),
        "typical_rent_per_bedroom": round(typical) if typical else None,
        "listings": shown,
    }
