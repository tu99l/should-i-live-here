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

## START HERE, Tu: latest state (Sat Oct 17, ~11:45 PM). Feature freeze: fixes and polish only from now
**The app, as it works now** (all tested on real phones with Freddy and Tu):
1. Welcome screen: "What are you looking for?" in your own words, where you go, how many people, your name.
2. Map with real rentals near that place (RentCast) plus the 12 demo listings. Pick shown and updated by itself.
3. "Your group": one card per person. Only your own card is editable. "+ Add a roommate" (name + phone; no email).
   They text the bot once from an iPhone (iMessage only, the bot can't text first); their texts fill their card.
4. Texting the bot: welcome with a checklist of what to mention; every later text adds or changes wishes;
   "pick" replies with the pick and the map link; when someone's text changes the pick, everyone else gets an
   "Update" text (at most one per person every 3 minutes, always the newest pick); photos get "I can only read text".
5. View-only map link for roommates' phones (`scripts/share_link.py`): pick, map, scores, ranking, who wants what.
6. Section 4 is now "Found a place somewhere else?" (collapsed): paste a listing to add laundry/parking/utilities facts.
7. Safety: removing someone, "Load demo group" and "Start over" all need a second click.
8. Scoring changes tonight: rent reaches zero at 2x the budget (budgets below market still matter); a stated max rent
   makes rent "important"; a pick missing rent/bedrooms/bathrooms gets a ⚠ and a fully known alternative.

**Oct 18, 8 AM (Freddy, in `static/app.js`, display only, scores unchanged):** map cards now list each person's own wishes
under their score ("Near grocery store: Bristol Farms, 4 min walk"), and the 🛒 line uses that measured store when the
listing has none (it was "unknown" for every RentCast listing). Known gap: wishes can only be added, not removed (Start over clears them).

**Stress-tested** (for the Devpost "how we built it"): 730 requests at once, two programs editing the group at the same
time (300 edits, none lost), hostile input, every route through the public link (only the results page answers),
a 100-text flood, Photon failures (no double texts, failed replies retried), no internet (the demo still works).
132 automated tests.

**Tu's to-do** (no code files need touching; restyle freely if you want):
- [ ] Devpost write-up: what it does, how it works (Gemini only reads words, our code scores, Google measures,
      RentCast finds listings, Photon carries texts), what's next (hosted multi-group version, laundry/parking data).
- [ ] Demo video (2–3 min): welcome text -> real listings -> add a roommate -> they text -> their card fills ->
      the pick flips and everyone gets the Update text -> they open the map link on their phone. Record a backup.
- [ ] README: Freddy set it up as our front page with a draft in each section, 4 real screenshots
      (docs/images/), a real bot conversation, and HIDDEN NOTES FOR TU under every heading (open README.md in an
      editor to see them; GitHub hides them) with everything we built: numbers, scoring rules, architecture,
      stress tests, demo moments, limits. Rewrite it in your voice; reuse it for the Devpost. Setup moved to
      docs/SETUP.md.
- [ ] Thumbnail (5:3).
- Demo moments to use: see "Demo moments (current...)" below. Older demo notes further down are outdated.

**Optional prize: MLH "Best Domain Name from GoDaddy Registry"** (from the brief; nothing done yet; whoever has time):
- [ ] Ask MLH (their table or the event Discord) for the free GoDaddy Registry domain code and the rules.
- [ ] Register a creative name (ideas, availability not checked: shouldilivehere, fairestpick, roomiefair, fairsplit).
- [ ] Our app runs on a laptop, so forward the domain to the GitHub page (https://github.com/tu99l/should-i-live-here)
      or the demo video, using the registrar's forwarding setting (no code).
- [ ] On Devpost, opt into the challenge and list the domain; add it to the README's Team section.

## Live demo script: Freddy + Tu with real phones (Tu, Oct 18). Record by ~9 AM, submit by 11 AM
**Setup (Freddy's laptop only: it has the keys, and the bot runs on one laptop).** Three terminal tabs, leave them running:
`.venv/bin/uvicorn app.main:app --port 8000` · `.venv/bin/python -m app.photon_bot` · `.venv/bin/python scripts/share_link.py`.
Hard refresh (Cmd+Shift+R), extensions off. Freddy = "you" (fills in the welcome screen, his card is editable).
Tu = the roommate who texts, from an iPhone (iMessage only).

**Rehearse first.** Live listings + real wishes don't always flip the pick. Do 1–2 practice runs and lock in a
second text that flips it reliably. Candidates: a new destination ("I bike to Santa Monica Pier"), a low budget
("my max is $1,200"), a must-have ("in-unit laundry is a must" / "parking is a must"). Use the SAME texts in the
real take: Gemini, Google and RentCast answers are cached, so repeats are instant and identical (and RentCast
fetches the area only once). Between takes: "Start over" (two clicks), redo the welcome screen, re-add Tu.
Fill in the locked texts here: first text: `______________` · flip text: `______________` · pick before/after: `____` → `____`

| # | On screen | Who does what | What we say (voice-over) |
| --- | --- | --- | --- |
| 1 | Welcome screen | Freddy types his wishes, place UCLA, People 2, his name, "Find our place" | "Finding a place with roommates means someone always gives something up. Just say what you want, in your own words." |
| 2 | Map with real listings | Pan the map, hover one listing | "These are real rentals near campus right now. Walk, bike and transit times come from Google Maps, nothing is guessed." |
| 3 | "Your group" | Freddy clicks "+ Add a roommate": Tu's name + phone (don't keep the full number on screen) | "Roommates don't need an app or an account. Add them by phone." |
| 4 | Tu's phone + Tu's card | Tu sends the first text; the bot replies with a checklist; Tu's card fills in | "Tu just texts what they want. Gemini only reads the words; our code checks every fact against the exact quote." |
| 5 | The pick | The pick updates by itself; open "See the math" | "The fair pick is the place where the least happy roommate is happiest, and it shows who gives up what." |
| 6 | The flip | Tu sends the flip text; the pick moves; Freddy's phone gets the "Update" text | "When anyone changes their mind, the pick re-runs and everyone gets told." |
| 7 | Phone map link | Tu opens the link on the phone: pick, both scores, ranking | "Everyone sees the same map and the same math on their phone." |
| 8 | Close | Back on the laptop | "Fair, not average: an average can hide one miserable roommate. We don't." |

**Recording.** Laptop: Cmd+Shift+5. Phone: iPhone screen recording, or plug in and use QuickTime → New Movie
Recording → iPhone so both are on one screen. Keep texts short (a long text can take Gemini up to a minute).
Cards show only the last 4 digits of phone numbers. **Backup:** also record the no-phones version ("Load demo
group": the pick, the scores, "See the math") in case live texting fails at judging.

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

## Demo moments (current, after the Oct 17 rent-scale change) — use these, older notes below are outdated
Rent now reaches zero at twice the budget (was 125%), so over-budget places still rank by how far over, and a stated
max rent ("my max is $1,000") makes rent "important". With **Load demo group** (Alex, Sam, Jordan):
- The pick is **547 Landfair**. Sam's laundry 3 -> 5 (or Sam texting "in-unit laundry is a must") moves it to
  **1824 Fairburn** (in-unit laundry).
- Alex's budget $1,500 -> $1,200 moves it to **424 Landfair**, the cheapest ($1,083 each): budgets matter now.
- If the fairest place doesn't state rent, bedrooms or bathrooms, it shows "⚠ The listing doesn't say its rent..."
  with the fairest fully known place next to it.
(Both moments are checked by `tests/test_group.py::test_changing_one_roommates_weights_can_flip_the_pick`.)

## View-only results link for roommates — done by Freddy (Tu: restyle `static/share.css` freely)
- Run the app, then `.venv/bin/python scripts/share_link.py` (needs `brew install cloudflared`). It prints a link like
  `https://<random>.trycloudflare.com/share/<secret>` and the page shows it under the pick ("Share with your group").
- Roommates open it on their phones: the pick, the map (tap dots), everyone's scores at the pick, all places ranked,
  who wants what. View only; refreshes by itself. Works only while the laptop runs the app and the script.
- Through the tunnel, only the share page answers; everything else (searches, invites, edits) is 404 (`app/share.py`).
- The bot adds the link to "pick" replies, and when someone's text changes the pick it texts everyone else who has
  texted the bot: "Update: Sam changed what they want, and the fairest pick is now X. See the map: <link>".
- For the demo: start `share_link.py` before judging; the link changes each time it starts (the secret part stays).

## Redesign: one group for the page and the bot — done by Freddy (Tu: pull, then restyle freely)
Problem: the page and the iMessage bot each had their own group (page: Alex/Sam/Jordan in the browser with 0–5 grids;
bot: roommates.local.json), so a roommate's texts never changed their card.
- **One group, saved by the backend** (`data/group.local.json`, git-ignored): people, their wishes, and the group's listings.
  The page and the bot both read and write it.
- **Cards come from people:** you (from the welcome box) + everyone you invite. An invited person's card says
  "Waiting for first text", then fills in by itself from their texts (wishes as chips, budget, commute). People without
  a phone can be typed in on the page ("What does Jordan want?").
- **No 0–5 grid as input.** Wishes set the weights. The math stays visible in the results and in "See the math" on each card.
- **The pick updates itself** when anyone texts or changes something. The bot uses the same listings as the map (RentCast results too).
- **"Load demo group"** fills Alex, Sam and Jordan with their usual wishes for judging (no phones needed).
- Built: `app/group_store.py` (one file, `data/group.local.json`, locked writes so the page and bot never overwrite
  each other), group endpoints in `main.py` (`/api/group`, `/me`, `/people`, `/people/{name}/wishes`, `/demo`, `/reset`,
  `/listings`, `/decide`), `static/group.js` (cards, invite, add without phone), sidebar is now 1 Where, 2 Your group,
  3 Fairest pick, 4 Add a listing. `invite.js` is gone (folded into group.js); `invite.css` is now `group.css`.
- Rent is split by the group's expected size (welcome screen "People") until everyone is added.
- Tested by clicking through in headless Chrome: load demo group, type a wish on a card, a change made like a text
  shows up on its own, add and remove someone. No JS errors.
- After this: feature freeze. Fixes, polish, demo video, Devpost.

## Welcome text box — done by Freddy (Tu: restyle freely)
- Welcome screen now asks "What are you looking for?" (own words), where you need to get to, how many people,
  your name. "Find our place →" reads the wishes (`/api/wishes`), makes them the first roommate's priorities,
  searches real listings near the place (`/api/search`), opens the map and runs the fair pick.
  "Skip, show the demo" keeps the old behavior. Code: `static/welcome.js`, `static/welcome.css`.
- Sidebar shows "<name> asked for" chips (hover a chip for the exact words), and each roommate card shows its wishes.
- Small `app.js` edits: hover cards stay hidden while a clicked listing's card is open (Freddy's request);
  roommate cards call `wishChips(r)` when it exists.

## Real listings near any place (RentCast) — done by Freddy
- "Find real listings near here" button under the destination box (`static/search.js`): `POST /api/search`
  `{place, radius_miles, min_bedrooms, max_rent_per_person, limit}` -> up to 40 nearest active rentals from RentCast
  (one request per area, cached in `cache/rentcast/`; free plan = 50 requests/month, so don't change the key or clear the cache).
  Each result has real walk/bike times to the place. Laundry and parking are always unknown (RentCast doesn't have them).
- **Per-room trap:** some listings show one room's price with the whole house's bedroom count ("7 bed, $1,080").
  If price per bedroom is under 40% of the area's typical (about $2,200 near UCLA), the listing gets
  `price_check: "possible_per_room"`, `rent_total_monthly: null` (rent per person unknown, never split), `listed_price`,
  and a red flag that the card shows. Flagged listings rank last and are never anyone's favorite.
- New listing fields: `source` ("demo"/"pasted"/"rentcast"), `listed_price`, `price_check`, `property_type`, `square_feet`, `commute_to`.
- **Hard cap:** at most 45 new-area RentCast searches per billing period (resets on the 17th, the plan's billing day),
  counted per laptop in `cache/rentcast/`. At the cap, new places are refused with a clear message; places already
  searched still work from the cache. The page shows "New-area searches this month: N of 45". Tu: if you get your own
  RentCast key, it has its own 50; if you use Freddy's, both laptops count separately, so be careful.
- "Own bathroom" wish (text: "my own bathroom"): enough bathrooms for everyone who asked, plus one shared for the rest.
- Open question for both of us: a pick with unknown laundry/parking can beat one with known shared laundry,
  because unknowns are excluded (the brief's rule). It is marked partial data. Change the rule or leave it?

## For Freddy: make it work anywhere, not just UCLA (from Tu) — done: 1 `/api/place`, 2 `destination` in `/api/parse`, 3 `commutes_for` only reuses minutes measured to the same place, 4 prompt says "campus, school or work". 5 (currency) left as a Devpost next step.
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
