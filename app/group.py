"""Group decision: score every listing for every roommate, then pick the fairest one.

Fair pick = the listing whose least-happy roommate is happiest (maximin), ties broken by the
higher average. Listings with red flags only win if every listing has one.
(Step 6 will extend this; the response shape is what static/app.js reads.)
"""
from .models import Listing, Roommate
from .scoring import rent_per_person, score_listing

CONFLICT_GAP = 25  # Roommate scores this far apart on one listing count as a disagreement.


def _rank_value(score):
    """For sorting only: a listing with no usable score ranks below every scored one."""
    return -1 if score is None else score


def decide(listings: list[Listing], roommates: list[Roommate]) -> dict:
    group_size = len(roommates)
    results = []
    for listing in listings:
        per_roommate = [score_listing(listing, r, group_size) for r in roommates]
        scores = [p["score"] for p in per_roommate]
        known = [s for s in scores if s is not None]
        results.append({
            "listing_id": listing.id,
            "title": listing.title or listing.address or listing.id,
            "rent_per_person": rent_per_person(listing, group_size),
            "min_score": min(known) if len(known) == len(scores) else None,
            "avg_score": round(sum(known) / len(known), 1) if known else None,
            "gap": round(max(known) - min(known), 1) if known else 0.0,
            "partial_data": any(p["partial_data"] for p in per_roommate),
            "red_flags": listing.red_flags,
            "per_roommate": per_roommate,
        })

    # Clean listings first, then maximin: best worst-case, then best average.
    results.sort(key=lambda r: (not r["red_flags"], _rank_value(r["min_score"]), _rank_value(r["avg_score"])),
                 reverse=True)
    pick = results[0]

    least_happy = min(pick["per_roommate"], key=lambda p: _rank_value(p["score"]))
    biggest_loss = max(least_happy["breakdown"], key=lambda b: b["points_lost"])

    # Each roommate's own favorite, to show where the group disagrees.
    favorites = {}
    for i, r in enumerate(roommates):
        best = max(results, key=lambda res: _rank_value(res["per_roommate"][i]["score"]))
        favorites[r.name] = best["listing_id"]

    return {
        "pick": {"listing_id": pick["listing_id"], "title": pick["title"]},
        "least_happy": {
            "roommate": least_happy["roommate"],
            "score": least_happy["score"],
            "gives_up_most_on": biggest_loss["criterion"],
        },
        "favorites": favorites,
        "conflicts": [
            {"listing_id": r["listing_id"], "title": r["title"], "gap": r["gap"]}
            for r in results if r["gap"] >= CONFLICT_GAP
        ],
        "ranking": results,
    }
