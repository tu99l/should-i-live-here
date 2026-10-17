"""Our own scoring and group-decision code. No AI here: every number is explainable.

1. Each factor (rent, walk, laundry, parking, grocery) gets a 0-1 score per listing.
2. Each roommate's score for a listing = their weighted average of those factor scores, 0-100.
3. Fairest pick = the listing whose least-happy roommate is happiest (maximin).
   Ties go to the higher average score. Listings with red flags only win if every listing has one.
"""
from typing import Optional

from .models import Listing, Roommate

FACTORS = ["rent", "walk", "laundry", "parking", "grocery"]
UNKNOWN_SCORE = 0.5  # Missing facts count as neutral, and are reported as unknown.
CONFLICT_GAP = 25  # Roommate scores this far apart on one listing count as a disagreement.

LAUNDRY_SCORES = {"in_unit": 1.0, "in_building": 0.6, "none": 0.0}
PARKING_SCORES = {"included": 1.0, "extra_cost": 0.5, "none": 0.0}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _linear(value: float, best: float, worst: float) -> float:
    """1.0 at `best` or better, 0.0 at `worst` or beyond, straight line in between."""
    return _clamp((worst - value) / (worst - best))


def rent_per_person(listing: Listing, group_size: int) -> Optional[float]:
    if listing.price is None:
        return None
    if listing.price_type in ("per_room", "per_bed"):
        return listing.price
    if listing.price_type == "whole_unit":
        return round(listing.price / max(group_size, 1), 2)
    return None  # Price type unclear: don't guess how it splits.


def factor_scores(listing: Listing, roommate: Roommate, group_size: int) -> dict[str, Optional[float]]:
    """0-1 score per factor, or None when the fact is unknown."""
    rpp = rent_per_person(listing, group_size)
    b = roommate.budget
    return {
        # Full marks at 75% of budget, zero at 125% of budget.
        "rent": None if rpp is None else _linear(rpp, 0.75 * b, 1.25 * b),
        # Full marks at a 10-minute walk, zero at 40 minutes.
        "walk": None if listing.walk_minutes is None else _linear(listing.walk_minutes, 10, 40),
        "laundry": LAUNDRY_SCORES.get(listing.laundry),
        "parking": PARKING_SCORES.get(listing.parking),
        # Full marks at a 5-minute walk to groceries, zero at 25 minutes.
        "grocery": None if listing.grocery_walk_minutes is None else _linear(listing.grocery_walk_minutes, 5, 25),
    }


def score_for_roommate(listing: Listing, roommate: Roommate, group_size: int) -> dict:
    """One roommate's 0-100 score for one listing, with the breakdown shown on the card."""
    scores = factor_scores(listing, roommate, group_size)
    weights = roommate.weights.model_dump()
    total_weight = sum(weights.values())

    breakdown = []
    points_sum = 0.0
    for f in FACTORS:
        s = scores[f] if scores[f] is not None else UNKNOWN_SCORE
        points = 100 * weights[f] * s / total_weight if total_weight else 0
        points_sum += points
        breakdown.append({
            "factor": f,
            "weight": weights[f],
            "factor_score": None if scores[f] is None else round(scores[f], 2),
            "unknown": scores[f] is None,
            "points": round(points, 1),
            # Points lost compared with a perfect score on this factor.
            "points_lost": round(100 * weights[f] * (1 - s) / total_weight, 1) if total_weight else 0,
        })

    total = points_sum if total_weight else 50.0
    return {"roommate": roommate.name, "score": round(total, 1), "breakdown": breakdown}


def decide(listings: list[Listing], roommates: list[Roommate]) -> dict:
    group_size = len(roommates)
    results = []
    for listing in listings:
        per_roommate = [score_for_roommate(listing, r, group_size) for r in roommates]
        scores = [p["score"] for p in per_roommate]
        results.append({
            "listing_id": listing.id,
            "title": listing.title,
            "rent_per_person": rent_per_person(listing, group_size),
            "min_score": min(scores),
            "avg_score": round(sum(scores) / len(scores), 1),
            "gap": round(max(scores) - min(scores), 1),
            "red_flags": listing.red_flags,
            "per_roommate": per_roommate,
        })

    # Clean listings first, then maximin: best worst-case, then best average.
    results.sort(key=lambda r: (not r["red_flags"], r["min_score"], r["avg_score"]), reverse=True)
    pick = results[0]

    least_happy = min(pick["per_roommate"], key=lambda p: p["score"])
    biggest_loss = max(least_happy["breakdown"], key=lambda b: b["points_lost"])

    # Each roommate's own favorite, to show where the group disagrees.
    favorites = {}
    for r in roommates:
        best = max(results, key=lambda res: next(p["score"] for p in res["per_roommate"] if p["roommate"] == r.name))
        favorites[r.name] = best["listing_id"]

    return {
        "pick": {"listing_id": pick["listing_id"], "title": pick["title"]},
        "least_happy": {
            "roommate": least_happy["roommate"],
            "score": least_happy["score"],
            "gives_up_most_on": biggest_loss["factor"],
        },
        "favorites": favorites,
        "conflicts": [
            {"listing_id": r["listing_id"], "title": r["title"], "gap": r["gap"]}
            for r in results if r["gap"] >= CONFLICT_GAP
        ],
        "ranking": results,
    }
