"""Real walk and bike times from the Google Routes API, cached to data/cache.json.

Every response is cached by (address, destination, mode), so each lookup is paid for once
and the demo still works offline after one run.
"""
import json
import os
from pathlib import Path
from typing import Optional

import httpx

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "cache.json"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def travel_minutes(address: str, mode: str = "WALK", destination: Optional[str] = None) -> Optional[float]:
    """Minutes from address to the destination by WALK or BICYCLE. None if unavailable."""
    destination = destination or os.getenv("DESTINATION", "Royce Hall, UCLA, Los Angeles, CA")
    key = f"{address}|{destination}|{mode}"
    cache = _load_cache()
    if key in cache:
        return cache[key]

    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return None  # No key yet: the card shows "unknown" instead of a guess.

    response = httpx.post(
        ROUTES_URL,
        headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": "routes.duration"},
        json={
            "origin": {"address": address},
            "destination": {"address": destination},
            "travelMode": mode,
        },
        timeout=15,
    )
    response.raise_for_status()
    routes = response.json().get("routes", [])
    # Duration comes back as a string like "754s".
    minutes = round(int(routes[0]["duration"].rstrip("s")) / 60, 1) if routes else None

    cache[key] = minutes
    _save_cache(cache)
    return minutes
