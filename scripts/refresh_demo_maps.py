"""Fill data/demo_listings.json with real Google Maps numbers (walk, bike, groceries).

Uses each listing's saved coordinates, so short or vague addresses can't land in the wrong place.
Every reply is cached in cache/, so running it again costs nothing.

Run:  .venv/bin/python scripts/refresh_demo_maps.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from app import maps_lookup  # noqa: E402

FIELDS = ["walk_minutes", "bike_minutes", "grocery_walk_minutes", "grocery_count", "nearest_grocery"]

path = ROOT / "data" / "demo_listings.json"
listings = json.loads(path.read_text())
print(f"{'listing':28} {'walk (old -> new)':>18} {'bike':>6} {'grocery':>8} {'#1km':>4}  nearest")
missing = 0
for d in listings:
    old_walk = d.get("walk_minutes")
    found = maps_lookup.lookup({"lat": d["lat"], "lng": d["lng"]})
    for f in FIELDS:
        d[f] = found[f]
    missing += any(found[f] is None for f in FIELDS[:3])
    print(f"{d['title'][:28]:28} {old_walk!s:>8} -> {d['walk_minutes']!s:<7} {d['bike_minutes']!s:>6} "
          f"{d['grocery_walk_minutes']!s:>8} {d['grocery_count']!s:>4}  {d['nearest_grocery']}")

path.write_text("[\n" + ",\n".join("  " + json.dumps(d) for d in listings) + "\n]\n")
print(f"\nSaved {len(listings)} listings. Listings with a missing value: {missing}.")
