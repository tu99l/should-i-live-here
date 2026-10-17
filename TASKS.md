# Tasks

Update this file when you start or finish something, then commit and push. Status: todo, doing, done.
Full plan and times: `docs/PROJECT_BRIEF.md`. Deadline 12:00 PM Sunday, target submit 11:00 AM.

| # | Step | Owner | Target | Status |
| --- | --- | --- | --- | --- |
| 1 | Repo, `.env`, `.gitignore`, CLAUDE.md; both can run the app locally | Both | 2:30 PM | Freddy: done. Tu: done |
| 2 | `extract.py`: pasted text to validated JSON with evidence quotes | Freddy | 4:00 PM | todo |
| 3 | `scoring.py`: weights sum to 1, breakdown, unknowns excluded, tests | Freddy | 5:00 PM | todo |
| 4 | `maps_lookup.py`: walk/bike time + groceries, cached, billing cap set | Freddy | 6:00 PM | todo |
| 5 | Map UI from `reference/UCLA-Apartment-Map.html`, demo listings load | Teammate | 5:00 PM | done (Tu) |
| 6 | `group.py`: maximin fair pick, who is least happy and why | Freddy | 8:00 PM | todo |
| 7 | Photon iMessage (gated: only after 2 to 5 work; cut at 7:00 PM if no reply) | Whoever is free | ~6:00 PM | todo |
| 8 | Design pass: palette, fonts, empty and loading states | Teammate | 10:00 PM | todo |
| 9 | Devpost draft, thumbnail (5:3), README | Teammate | 11:00 PM | todo |
| 10 | Sleep in shifts; stability fixes only | Both | 1:00 to 6:00 AM | todo |
| 11 | Feature freeze, tag the build | Both | 6:00 AM | todo |
| 12 | Demo video on YouTube | Teammate | 9:00 AM | todo |
| 13 | Devpost submitted with both teammates added | Both | 11:00 AM | todo |

## Code that must change to match the brief
The starter code was written before the brief, so it uses different names. Fix these as part of steps 2 to 6:
- `app/parser.py` becomes `app/extract.py`, with the brief's schema (`rent_total_monthly`, `utilities_included`, `available_from`, `evidence`).
- `app/commute.py` becomes `app/maps_lookup.py`, caching into `cache/` instead of `data/cache.json`.
- The group pick moves out of `app/scoring.py` into `app/group.py`.
- `app/models.py`: laundry `in_unit | shared | none | unknown`, parking `included | paid | none | unknown`.
- Scoring: weights re-normalized to sum to 1; criteria are rent per person, commute, laundry, parking, bedroom fit.
- `data/demo_listings.json`: rebuilt by Tu from the 12 listings in `reference/UCLA-Apartment-Map.html`, still in the current shape (`price` + `price_type`, laundry `in_building`, parking `extra_cost`). Freddy: convert it when `models.py` changes; `static/app.js` already reads `rent_total_monthly`, `shared`, `paid` and `available_from`.

## Missing inputs
- [ ] `data/samples/`: paste 3 to 4 real listing texts near UCLA (`listing1.txt`...), including one messy one.
- [x] Teammate: create `CLAUDE.local.md` with "I am <name> (UI and story)."
- [ ] The "How it works" diagram in the brief did not export; view it in the Claude Doc.
