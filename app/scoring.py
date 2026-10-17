"""Step 3: our own scoring. No AI here: every number can be traced to a fact and a weight.

For one roommate and one listing:
1. Each criterion gets a 0-1 score from the listing's facts (rules below).
2. The roommate's 0-5 weights are re-normalized to sum to 1.
3. A criterion whose fact is unknown is EXCLUDED and the remaining weights are re-normalized,
   so missing data is never guessed. The listing is flagged "partial data".
4. Score = 100 * sum(weight * criterion score), so it runs from 0 to 100.
"""
from typing import Optional

from .models import Listing, Roommate

CRITERIA = ["rent", "commute", "laundry", "parking", "bedrooms"]

# Rent per person is judged against the roommate's own budget (a user input):
# full marks at 75% of budget or less, zero at 125% of budget or more, straight line between.
RENT_BEST_SHARE_OF_BUDGET = 0.75
RENT_WORST_SHARE_OF_BUDGET = 1.25

# Commute is minutes to the roommate's own place by their own travel mode (walk to campus by
# default): full marks at 10 minutes or less, zero at 40 minutes or more.
COMMUTE_BEST_MINUTES = 10
COMMUTE_WORST_MINUTES = 40

LAUNDRY_SCORES = {"in_unit": 1.0, "shared": 0.4, "none": 0.0}
PARKING_SCORES = {"included": 1.0, "paid": 0.5, "none": 0.0}


def _linear(value: float, best: float, worst: float) -> float:
    """1.0 at `best` or better, 0.0 at `worst` or beyond, straight line in between."""
    return max(0.0, min(1.0, (worst - value) / (worst - best)))


def rent_per_person(listing: Listing, group_size: int) -> Optional[float]:
    """What each roommate pays per month.

    Whole-unit rent is split evenly (group size comes from the user, never the model).
    If the listing only states a per-bed or per-room price, each person pays that price.
    """
    if listing.rent_total_monthly is not None:
        return round(listing.rent_total_monthly / max(group_size, 1), 2)
    if listing.rent_per_person_listed is not None:
        return listing.rent_per_person_listed
    return None


def criterion_scores(listing: Listing, roommate: Roommate, group_size: int,
                     commute_minutes: Optional[float]) -> dict[str, tuple]:
    """(raw_value, 0-1 score) per criterion. Score is None when the fact is unknown."""
    rpp = rent_per_person(listing, group_size)
    b = roommate.budget
    beds = listing.bedrooms
    return {
        "rent": (rpp, None if rpp is None else
                 _linear(rpp, RENT_BEST_SHARE_OF_BUDGET * b, RENT_WORST_SHARE_OF_BUDGET * b)),
        "commute": (commute_minutes, None if commute_minutes is None else
                    _linear(commute_minutes, COMMUTE_BEST_MINUTES, COMMUTE_WORST_MINUTES)),
        "laundry": (listing.laundry, LAUNDRY_SCORES.get(listing.laundry)),
        "parking": (listing.parking, PARKING_SCORES.get(listing.parking)),
        # Enough bedrooms for everyone = 1.0, otherwise 0.0.
        "bedrooms": (beds, None if beds is None else (1.0 if beds >= group_size else 0.0)),
    }


_WALK_TO_CAMPUS = object()


def score_listing(listing: Listing, roommate: Roommate, group_size: int,
                  commute_minutes=_WALK_TO_CAMPUS) -> dict:
    """One roommate's 0-100 score for one listing, with the full breakdown.

    `commute_minutes` is this roommate's own commute (looked up by the caller from Google).
    If not given, the listing's walk to campus is used.

    Returns {roommate, score, breakdown, unknown, partial_data}. `score` is None only when
    nothing this roommate cares about is known for the listing.
    """
    if commute_minutes is _WALK_TO_CAMPUS:
        commute_minutes = listing.walk_minutes
    scores = criterion_scores(listing, roommate, group_size, commute_minutes)
    raw_weights = roommate.weights.model_dump()
    unknown = [c for c in CRITERIA if scores[c][1] is None]
    known_total = sum(raw_weights[c] for c in CRITERIA if c not in unknown)

    breakdown = []
    total = 0.0
    for c in CRITERIA:
        raw_value, s = scores[c]
        weight = raw_weights[c] / known_total if (s is not None and known_total) else 0.0
        contribution = 100 * weight * s if s is not None else 0.0
        total += contribution
        breakdown.append({
            "criterion": c,
            "factor": c,  # Same as "criterion"; kept because static/app.js reads it.
            "raw_value": raw_value,
            "criterion_score": None if s is None else round(s, 3),
            "weight": round(weight, 3),
            "contribution": round(contribution, 1),
            # Points this criterion cost compared with a perfect score on it.
            "points_lost": round(100 * weight * (1 - s), 1) if s is not None else 0.0,
            "unknown": s is None,
        })

    return {
        "roommate": roommate.name,
        "score": round(total, 1) if known_total else None,
        "breakdown": breakdown,
        "unknown": unknown,
        "partial_data": bool(unknown),
    }
