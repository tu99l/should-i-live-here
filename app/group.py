"""Step 6: the group decision. Plain code, no AI.

1. Every roommate scores every listing with their own weights (scoring.py).
2. Fair pick = the listing whose LEAST happy roommate is happiest (maximin).
   Ties go to the higher average score, then to the listing with more known facts.
   Listings with red flags only win if every listing has one.
3. For the pick we report each roommate's score, who is least happy, and why:
   the criteria that cost them the most points, with the listing's actual facts.
4. Conflicts: listings where roommates' scores are far apart, and each roommate's own favorite.
"""
from typing import Optional

from .models import Listing, Roommate
from .scoring import CRITERIA, rent_per_person, score_listing

CONFLICT_GAP = 25  # Roommate scores this far apart (out of 100) on one listing count as a disagreement.
REASONS_SHOWN = 2  # How many "why" criteria to report for the least happy roommate.


def _rank_value(score):
    """For sorting only: a listing with no usable score ranks below every scored one."""
    return -1 if score is None else score


def _reasons(result: dict) -> list[dict]:
    """The criteria that cost this roommate the most points, biggest loss first."""
    lost = [b for b in result["breakdown"] if not b["unknown"] and b["points_lost"] > 0]
    lost.sort(key=lambda b: b["points_lost"], reverse=True)
    reasons = []
    for b in lost[:REASONS_SHOWN]:
        reason = {"criterion": b["criterion"], "raw_value": b["raw_value"], "points_lost": b["points_lost"]}
        if b["criterion"] == "commute":  # Say where to and how, e.g. 31 min by BICYCLE to Santa Monica Pier.
            reason["commute_to"] = result.get("commute_to")
            reason["travel_mode"] = result.get("travel_mode")
        for key in ("kind", "place_name", "evidence", "needed"):  # Their own wishes: which gym, which quote.
            if b.get(key) is not None:
                reason[key] = b[key]
        reasons.append(reason)
    return reasons


def decide(listings: list[Listing], roommates: list[Roommate],
           commutes: Optional[dict[tuple[int, int], Optional[float]]] = None,
           want_facts: Optional[dict[tuple[int, int], list]] = None) -> dict:
    """`commutes` maps (listing index, roommate index) to that roommate's commute minutes
    (from maps_lookup.commutes_for). Without it, everyone's commute is the walk to campus.
    `want_facts` maps the same pairs to the facts for that roommate's own wishes
    (from wishes.want_facts_for). Without it, every wish counts as unknown."""
    group_size = len(roommates)
    results = []
    for li, listing in enumerate(listings):
        per_roommate = []
        for ri, r in enumerate(roommates):
            facts = (want_facts or {}).get((li, ri))
            if commutes is None:
                p = score_listing(listing, r, group_size, want_facts=facts)
            else:
                p = score_listing(listing, r, group_size, commutes.get((li, ri)), want_facts=facts)
            p["commute_to"] = r.place or None  # None = the default campus.
            p["travel_mode"] = r.travel_mode
            per_roommate.append(p)
        scores = [p["score"] for p in per_roommate]
        known = [s for s in scores if s is not None]
        # Every fact missing for anyone (roommates' own wishes differ), in first-seen order.
        unknown = list(dict.fromkeys(c for p in per_roommate for c in p["unknown"]))
        all_criteria = {b["criterion"] for p in per_roommate for b in p["breakdown"]}
        results.append({
            "listing_id": listing.id,
            "title": listing.title or listing.address or listing.id,
            "rent_per_person": rent_per_person(listing, group_size),
            # If anyone has no usable score, the worst case is unknown, so it can't win on maximin.
            "min_score": min(known) if len(known) == len(scores) else None,
            "avg_score": round(sum(known) / len(known), 1) if known else None,
            "gap": round(max(known) - min(known), 1) if known else 0.0,
            "partial_data": bool(unknown),
            "unknown": unknown,
            "known_share": round(1 - len(unknown) / max(len(all_criteria), len(CRITERIA)), 2),
            "red_flags": listing.red_flags,
            "per_roommate": per_roommate,
        })

    # Clean listings first, then maximin, then average, then more known facts.
    results.sort(key=lambda r: (not r["red_flags"], _rank_value(r["min_score"]),
                                _rank_value(r["avg_score"]), r["known_share"]), reverse=True)
    for rank, r in enumerate(results, start=1):
        r["rank"] = rank
    pick = results[0]

    least_happy = min(pick["per_roommate"], key=lambda p: _rank_value(p["score"]))
    reasons = _reasons(least_happy)

    # Each roommate's own favorite (their highest score), to show where the group disagrees.
    favorites = {}
    for i, r in enumerate(roommates):
        # Same rule as the pick: a red-flagged listing (e.g. a price that may be for one room) is
        # nobody's favorite unless every listing has a flag.
        best = max(results, key=lambda res: (not res["red_flags"], _rank_value(res["per_roommate"][i]["score"])))
        favorites[r.name] = best["listing_id"]

    return {
        "pick": {
            "listing_id": pick["listing_id"],
            "title": pick["title"],
            "scores": [{"roommate": p["roommate"], "score": p["score"]} for p in pick["per_roommate"]],
            "min_score": pick["min_score"],
            "avg_score": pick["avg_score"],
            "partial_data": pick["partial_data"],
            "unknown": pick["unknown"],
        },
        "least_happy": {
            "roommate": least_happy["roommate"],
            "score": least_happy["score"],
            # Biggest single loss; None if they lost nothing (a perfect score).
            "gives_up_most_on": reasons[0]["criterion"] if reasons else None,
            "reasons": reasons,
        },
        "favorites": favorites,
        "everyone_agrees": len(set(favorites.values())) == 1,
        "conflicts": [
            {"listing_id": r["listing_id"], "title": r["title"], "gap": r["gap"]}
            for r in results if r["gap"] >= CONFLICT_GAP
        ],
        "ranking": results,
    }
