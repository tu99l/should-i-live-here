# Tasks

Update this file when you start or finish something, then commit and push. Status: todo, doing, done.
Full plan and times: `docs/PROJECT_BRIEF.md`. Deadline 12:00 PM Sunday, target submit 11:00 AM.

| # | Step | Owner | Target | Status |
| --- | --- | --- | --- | --- |
| 1 | Repo, `.env`, `.gitignore`, CLAUDE.md; both can run the app locally | Both | 2:30 PM | Freddy: done. Tu: done |
| 2 | `extract.py`: pasted text to validated JSON with evidence quotes | Freddy | 4:00 PM | done |
| 3 | `scoring.py`: weights sum to 1, breakdown, unknowns excluded, tests | Freddy | 5:00 PM | done |
| 4 | `maps_lookup.py`: walk/bike time + groceries, cached, billing cap set | Freddy | 6:00 PM | done |
| 5 | Map UI from `reference/UCLA-Apartment-Map.html`, demo listings load | Teammate | 5:00 PM | done (Tu) |
| 6 | `group.py`: maximin fair pick, who is least happy and why | Freddy | 8:00 PM | done |
| 7 | Photon iMessage (gated: only after 2 to 5 work; cut at 7:00 PM if no reply) | Whoever is free | ~6:00 PM | todo |
| 8 | Design pass: palette, fonts, empty and loading states | Teammate | 10:00 PM | todo |
| 9 | Devpost draft, thumbnail (5:3), README | Teammate | 11:00 PM | todo |
| 10 | Sleep in shifts; stability fixes only | Both | 1:00 to 6:00 AM | todo |
| 11 | Feature freeze, tag the build | Both | 6:00 AM | todo |
| 12 | Demo video on YouTube | Teammate | 9:00 AM | todo |
| 13 | Devpost submitted with both teammates added | Both | 11:00 AM | todo |

## Code that must change to match the brief
The starter code was written before the brief, so it uses different names. Fix these as part of steps 2 to 6:
- Done: `app/parser.py` is now `app/extract.py` with the brief's schema. `/api/parse` still returns the old Listing shape (via `to_listing_fields`) plus a new `evidence` field, until step 3.
- Done: `app/commute.py` replaced by `app/maps_lookup.py` (cache in `cache/maps/`).
- Done: group pick moved to `app/group.py` (same response shape; step 6 extends it).
- Done: `app/models.py` uses the brief's names (`rent_total_monthly`, laundry `shared`, parking `paid`). `price`/`price_type` are gone.
- Done: scoring criteria are rent, commute, laundry, parking, bedrooms; weights re-normalized to sum to 1; unknowns excluded.
- Done: `data/demo_listings.json` converted to the brief's names (values unchanged).

## For Tu (map UI), from step 3
- Rename the "walk" slider to "commute". The backend still accepts `walk` for now.
- Replace the "grocery" slider with "bedrooms" (enough bedrooms for everyone). The backend ignores `grocery`, so that slider does nothing; until then the bedrooms weight defaults to 3.
- Breakdown rows now carry `criterion`, `raw_value`, `criterion_score`, `weight` (0-1), `contribution`, `points_lost`, `unknown`. `factor` still works but is the old name.
- Each roommate result and each ranking row has `partial_data: true` when some facts are unknown. Worth a small "partial data" badge on the card.
- `/api/parse` now returns the brief's names plus `evidence` (exact quotes). Showing the quote on hover would help with judges.

## For Tu, from step 6 (all optional; nothing existing changed)
New fields in `/api/decide`:
- `pick.scores`: each roommate's score for the pick. `pick.unknown` / `pick.partial_data`.
- `least_happy.reasons`: up to 2 of `{criterion, raw_value, points_lost}`, e.g. laundry "shared" cost Jordan 18.8 points. Nicer than `gives_up_most_on` alone. `gives_up_most_on` is `null` if the pick is perfect for them.
- `everyone_agrees`: true when every roommate's favorite is the same listing.
- Ranking rows: `rank`, `unknown`, `known_share` (0-1, share of the 5 facts known).
Demo move that flips the pick (tested, with real Google walk times): Sam's "laundry" slider 3 -> 5 changes the pick from 424 Landfair (shared laundry) to 1824 Fairburn (in-unit laundry).

## For Tu, from step 4
- Demo walk times are now real Google numbers to Royce Hall (most went up: 424 Landfair is 18 min, not 10). Several listings are now outside the 35-min walk circle.
- New listing fields: `grocery_count` (stores within 1 km, straight line) and `nearest_grocery` (store name). `grocery_walk_minutes` is the real walk to that store. Card idea: "Groceries: Ralphs, 17 min walk (0 within 1 km)".
- Pasted listings now get `lat`/`lng` from Google, so they appear on the map.
- To refresh demo numbers: `.venv/bin/python scripts/refresh_demo_maps.py` (cached, so free after the first run).

## Missing inputs
- [x] `data/samples/`: 3 real Zillow listings saved (phones removed). Still useful: one messy Craigslist/Facebook post or per-bed price.
- [x] Teammate: create `CLAUDE.local.md` with "I am <name> (UI and story)."
- [ ] The "How it works" diagram in the brief did not export; view it in the Claude Doc.
