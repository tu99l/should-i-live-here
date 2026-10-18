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
| 7 | Photon iMessage (gated: only after 2 to 5 work; cut at 7:00 PM if no reply) | Freddy | ~6:00 PM | done: real round-trip on Freddy's iPhone; free-text wishes (near X / listing has X) |
| 8 | Design pass: palette, fonts, empty and loading states | Teammate | 10:00 PM | doing (Tu): UCLA blue/gold, Nunito + Inter, empty and loading states done; waiting on review. UI now sends each roommate's place + travel mode, and per-bed prices show |
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
Demo move that flips the pick: Sam's "laundry" 3 -> 5 no longer flips it (re-tested 7 PM Sat after the newer scoring changes; 424 Landfair stays). Single changes that do flip it: Alex rent 5 -> 1 (1824 Fairburn), Alex rent 5 -> 0 (547 Landfair), Jordan rent 3 -> 0 or bedrooms 3 -> 0 (1824 Fairburn). Sam by bike to Santa Monica Pier still flips it to 1824 Fairburn.

## For Tu, from step 4
- Demo walk times are now real Google numbers to Royce Hall (most went up: 424 Landfair is 18 min, not 10). Several listings are now outside the 35-min walk circle.
- New listing fields: `grocery_count` (stores within 1 km, straight line) and `nearest_grocery` (store name). `grocery_walk_minutes` is the real walk to that store. Card idea: "Groceries: Ralphs, 17 min walk (0 within 1 km)".
- Pasted listings now get `lat`/`lng` from Google, so they appear on the map.
- To refresh demo numbers: `.venv/bin/python scripts/refresh_demo_maps.py` (cached, so free after the first run).

## For Tu: each roommate has their own place (new feature)
Each roommate can now say where they need to get to and how. The backend looks up real commute times with Google (cached) and scores each roommate on their own commute.
- Send two new optional fields per roommate in `/api/decide`: `place` (text, e.g. "Santa Monica Pier, Santa Monica, CA"; blank = UCLA) and `travel_mode` (`WALK` | `BICYCLE` | `TRANSIT` | `DRIVE`, default `WALK`). UI idea: a text box "Where do you need to get to?" and a small walk/bike/transit/drive picker under each roommate's name.
- Each `per_roommate` result now has `commute_to` and `travel_mode`; the `commute` breakdown row's `raw_value` is that roommate's minutes. Show it in the card's score table (e.g. "Sam: 31 min by bike to Santa Monica Pier").
- If the least happy roommate's reason is commute, the reason includes `commute_to` and `travel_mode`.
- Tell users to type a specific place ("Santa Monica Pier"), not just "the beach"; Google routes to whatever it thinks that text means.
- Demo moment (tested live): with the default roommates, setting Sam to "Santa Monica Pier, Santa Monica, CA" by bike moves the pick from 424 Landfair to 1824 Fairburn, and Alex becomes least happy (rent $1,517 each, 43 min walk to campus).

## For Tu: per-bed and per-room prices (new field)
- Listings can now have `rent_per_person_listed`: a price the listing states per bed or per room ("$1,150/bed"). Each person pays that amount; it is not split.
- In `static/app.js`, `rentPerPerson()` still checks the old `price`/`price_type`, which no longer exist. Change it to: `rent_total_monthly / roommates` if set, else `rent_per_person_listed`, else unknown. (Or use `rent_per_person` from each `/api/decide` ranking row, which already does this.)
- Card idea: "$1,150/person (listed per bed)" so users see why it isn't split.

## For Tu: roommates' own wishes, by text or on the page (new, step 7)
Roommates can now ask for anything in their own words, by iMessage or (optionally) on the page:
"i want to be close to a gym, laundry included, need gas and water included".
- `POST /api/wishes` with `{"text": "..."}` returns what we understood: `weights` (only the built-in
  criteria they mentioned), `wants` (each `{kind: "near"|"feature", what, weight, quote}`), `budget`,
  `place`/`travel_mode`, `cannot_check` (their words we can't verify, like "quiet street").
- Send `wants` on each roommate in `/api/decide`; nothing else changes. Breakdown rows for wishes have
  `criterion` like `"near: gym"` or `"has: gas included"`, plus `kind`, `place_name` (near) or `evidence`
  (the listing's exact words, for features). Unknown wishes are excluded and flagged like other facts.
- Specific asks count strictly: "in-unit laundry" means shared laundry scores 0 for that roommate, "free parking"
  means paid parking scores 0 (roommate field `strict`). Saying you want something now weighs 4 (must 5, important 4.5),
  above the starting 3, so a text always moves things. Demo (tested): Freddy texts "would like in unit laundry"
  and the pick moves from 424 Landfair (shared laundry) to 1615 Greenfield (in-unit).
- Demo listings now have `source_text` (their notes from the old map), so "pets allowed", "water included",
  "A/C" get real yes/no answers with quotes. Gas is unknown everywhere: no listing mentions it.
- Run the iMessage bot: `.venv/bin/python -m app.photon_bot`. Needs `PHOTON_API_KEY` and `PHOTON_PROJECT_ID`
  in `.env`. Add roommates from the page (see the next section); they are saved in the git-ignored
  `data/roommates.local.json`. Commands by text: "pick", "reset", "help".

## "Invite by text" section on the page (done by Freddy, in `static/invite.js` + `static/invite.css`; Tu: restyle freely)
Goal: nobody touches the Photon dashboard or a config file. Our shared iMessage line can't text first
(only the $250/month Business plan can), so the roommate sends ONE pre-filled text; the bot replies right away.
- Built: form (name, phone, optional email and max rent), "last step" box with the number, the pre-filled
  message, an "Open in Messages" link and a copy button, and a live group list (polls every 4 s) with
  "Waiting for first text" / "Texting" and each person's texted wishes as chips. Not built: a QR code
  (would need a QR library, so ask first). `app.js` and `styles.css` were not touched; `index.html` got the section.
- Form fields: name, phone (any format), email (optional), max rent (optional).
- `POST /api/roommates/invite` with `{"name", "phone", "email"?, "budget"?}` returns
  `{name, line, text_link, starter_text, email_invite}`. Errors come back as `{"detail": "..."}` (400 bad number, 502 Photon).
- Show `text_link` as a big "Text to start" button AND a QR code of it (a laptop demo: they scan with their phone).
  QR idea: `qrcodejs` from cdnjs. The link opens Messages with our number and "Hi, it's Sam! Let's find our apartment." filled in.
  Also show `line` as text ("or text +1 628-316-6196"). Each person can get a different line number, so always use the one returned.
- If `email_invite` is true, say "Photon also emailed them an invite".
- `GET /api/roommates` lists the group: `{name, phone_last4, line, text_link, connected, budget, wants}`.
  `connected` turns true after their first text. Poll it every few seconds to flip "Waiting for Sam to text..." to "Sam is in".
  `wants` are what they've asked for by text (show as chips: "near a gym", "gas included").
- Inviting someone with an existing name (e.g. "Sam") keeps that roommate's priorities and adds the phone.
- The bot (`.venv/bin/python -m app.photon_bot`) must be running to answer; it picks up new roommates without a restart.

## Known risks (decided to leave as is)
- The page loads Leaflet (unpkg.com) and fonts (Google Fonts) from the internet. Ad blockers like uBlock Origin can block them and break the layout (seen on Freddy's browser; fixed by turning extensions off). Judges only use our laptops, so we left it. If someone else ever needs to run it: copy those files into `static/vendor/` and load them locally.
- Demo laptop: turn off browser extensions (or use a private window) before judging, and do one hard refresh (Cmd+Shift+R).

## Missing inputs
- [x] `data/samples/`: 3 real Zillow listings saved (phones removed). Still useful: one messy Craigslist/Facebook post or per-bed price.
- [x] Teammate: create `CLAUDE.local.md` with "I am <name> (UI and story)."
- [ ] The "How it works" diagram in the brief did not export; view it in the Claude Doc.

## For Freddy: make it work anywhere, not just UCLA (from Tu; backend, please review)
The page no longer assumes UCLA. Done in `static/` (works today, no backend change needed):
- New box "Where does your group need to get to most days?" (default "UCLA"). If it's not "UCLA", the page sends
  it as `place` for every roommate whose own "Going to" box is blank, so `/api/decide` already scores commutes
  to it with real Google times. Tested: "Santa Monica Pier, Santa Monica, CA" flips the pick to 1824 Fairburn.
- Marker colors now come from the group's own budgets (fits everyone / over someone's / over everyone's)
  instead of fixed LA prices. "Start fresh" link removes the 12 UCLA demo listings. Welcome page and copy say
  "for roommates anywhere". Demo data stays UCLA.

Backend asks, in priority order (none block the demo; the page already handles them being missing):
1. **Geocode route for the group's place**, so the map can show its badge and walk circle:
   `GET /api/place?q=<text>` -> `{"name", "formatted_address", "lat", "lng"}` (cached; 404 if not found).
   `static/app.js` `setHome()` already calls it and skips the badge if it 404s.
2. **Per-request destination in `/api/parse`.** `maps_lookup.lookup()` always uses `destination()` (Royce Hall),
   so a pasted listing in another city gets walk/bike times to UCLA (or none). Proposal: accept an optional
   `destination` in `ParseRequest`, pass it to `lookup()`, and return it on the listing as `commute_to`.
   The card already labels times with `l.commute_to || "UCLA"`, so it will show the right place once it's there.
   (Until then, the pick is still right: `/api/decide` uses each roommate's place; only the card's walk/bike
   line is to UCLA.)
3. **`commutes_for()` fallback:** when `place` is blank it reuses `walk_minutes`/`bike_minutes`. With item 2,
   those are to whatever destination the listing was parsed with; worth storing that on the listing and only
   reusing the saved minutes when it matches the roommate's destination.
4. **Wording in prompts:** `app/wishes.py` lines ~102-112 say "close to campus / UCLA / class". Suggest
   "close to campus, school or work" so texts from non-UCLA people read right.
5. **Money:** `extract.py` asks for "US dollars" and the page shows `$`. Fine for the US; other currencies would
   need a `currency` field. Probably out of scope for this weekend; flag it in the Devpost as a next step.
