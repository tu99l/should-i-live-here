# Common Ground (formerly "Should I Live Here?")

LA Hacks AI Hackathon 2026 project. Track: Applied Intelligence. Two teammates, 24 hours, both new to hackathons.

## One-sentence pitch
Roommates paste apartment listings; the app turns them into a map of cards with real rent per person and real commute times, scores each place with our own weighted scoring code, and picks the fairest option for the whole group (roommate input over iMessage via Photon is an optional later step).

## Rules that matter most (judges penalize "API wrapper")
1. Gemini ONLY extracts structured fields from pasted listing text and writes plain-English explanations. Gemini never produces a score, a ranking, or a distance.
2. Scoring and the group decision are plain code we write and test (see "Scoring spec"). No model call may decide a score.
3. Every number shown comes from (a) the pasted text, (b) the user's inputs, or (c) Google Maps Platform. If a value is missing, show "unknown". Never guess or let the model fill it in.
4. Cache every Gemini and Google Maps response on disk (`cache/`, git-ignored) keyed by input. The demo must work from cache with no network.
5. No API keys in git, ever. Keys live in `.env` (git-ignored). Commit `.env.example` with fake values. The repo is PUBLIC for Devpost.
6. Do not scrape listing sites. Users paste listing text.
7. Keep it small: one language for the whole backend, no login system, no database (JSON files are fine), no features beyond the build order below.

## Stack (defaults; change only if there is a strong reason, and keep ONE backend language)
- Backend: Python 3.11+, FastAPI, `google-genai` (Gemini), `python-dotenv`, `httpx` or `requests` for Google Maps Platform, `pytest`.
- Frontend: one static `index.html` (+ `styles.css`, `app.js`) using Leaflet with OpenStreetMap tiles. No framework needed.
- Keys (all in `.env`): `GEMINI_API_KEY` (Google AI Studio), `GOOGLE_MAPS_API_KEY` (Google Cloud console; enable only the routing and places APIs we use; set a billing cap first), `PHOTON_API_KEY` (optional, later).
- Do NOT depend on any Claude Code plugin or MCP server at runtime (for example the banana-claude plugin). The app calls Google's SDKs directly so teammates and judges can run it.

## File ownership (avoid merge conflicts; tell Claude Code which person you are)
- Freddy (AI and backend): `app/extract.py`, `app/scoring.py`, `app/maps_lookup.py`, `app/group.py`, `tests/`
- Teammate (UI and story): `static/` (index.html, styles.css, app.js), `README.md`, Devpost text
- Shared, edit carefully: `app/main.py`, `data/demo_listings.json`, `CLAUDE.md`
Pull before you start, commit and push every 30 to 60 minutes: `git pull`, `git add .`, `git commit -m "msg"`, `git pull`, `git push`.

## Build order (do not skip ahead; each step must work before the next)
1. Repo skeleton, `.env.example`, `.gitignore`, app runs locally, health check works.
2. `extract.py`: pasted listing text to validated JSON (schema below).
3. `scoring.py`: weighted scoring with a visible per-criterion breakdown, plus unit tests.
4. `maps_lookup.py`: walk and bike time to the campus, nearby groceries, cached.
5. Map UI: Leaflet markers colored by rent per person, hover card with the facts and score breakdown, a walk-radius circle. Pre-load demo listings.
6. `group.py`: several roommates' priorities, fair pick, who is least happy.
7. (Optional, gated) Photon iMessage input. Start only after steps 2 to 5 work end to end; cut if no real text round-trip within 45 minutes.
Out of scope for now: Browser Use, scam-warning checks (stretch), payments, accounts.

## Extraction schema (step 2)
Return JSON only, validated in code (reject and retry once, else mark fields unknown):
```
{
  "address": str | null,
  "rent_total_monthly": number | null,
  "bedrooms": number | null,
  "bathrooms": number | null,
  "laundry": "in_unit" | "shared" | "none" | "unknown",
  "parking": "included" | "paid" | "none" | "unknown",
  "utilities_included": true | false | null,
  "available_from": "YYYY-MM-DD" | null,
  "evidence": { "<field>": "<exact quote from the listing text>" }
}
```
- Every non-null field must have an evidence quote that appears verbatim in the pasted text. If the quote is not in the text, set the field to null/unknown.
- Rent per person is computed in code: `rent_total_monthly / number_of_roommates` (roommate count comes from the user, not the model).

## Scoring spec (step 3)
Criteria and default weights (user can change weights; they are re-normalized to sum to 1):
- rent per person (lower is better), commute minutes by walk or bike (lower is better), laundry (in_unit 1.0, shared 0.4, none 0.0), parking (included 1.0, paid 0.5, none 0.0), bedrooms fit (matches roommate count 1.0, else 0.0).
- Normalize rent and commute with documented min/max or reference values (put them in constants with comments). Score = sum(weight * criterion_score), range 0 to 100.
- If a criterion is unknown, EXCLUDE it, re-normalize the remaining weights, and flag the listing as "partial data". Never impute.
- Return `{score, breakdown: [{criterion, raw_value, criterion_score, weight, contribution}], unknown: [...]}`.
- Write pytest cases: weights change the ranking; unknowns are excluded; same inputs give the same score.

## Group decision spec (step 6)
- Each roommate has their own weights. Compute each listing's score per roommate.
- Fair pick = listing that maximizes the MINIMUM roommate score (maximin); tie-break by highest average.
- Report, for the pick: each roommate's score, and who is least happy and why (their lowest-contribution criteria).

## Google Maps notes (step 4)
- Origin = listing address, destination = campus (default UCLA, configurable). Walking and bicycling durations, plus count of grocery stores within a short walk.
- Check which Maps APIs are enabled in the Cloud console, set a budget alert and quota cap BEFORE the first call, test one address, then cache.
- Never call Maps from the browser with the key exposed; call from the backend.

## Demo requirements
- `data/demo_listings.json` holds pre-parsed listings (reuse the 12 UCLA listings from the earlier apartment map file) so the demo loads instantly with no live API calls.
- One backup screen recording and cached results must exist before judging.

## Definition of done per step
Runs locally, has at least a smoke test, no secrets committed, README updated if setup changed.

## Background
Read docs/PROJECT_BRIEF.md for the full project brief. Reference material: reference/UCLA-Apartment-Map.html (earlier map to reuse) and data/samples/ (real listing texts for tests).

## Demo story (build toward this)
3 roommates, ~12 UCLA listings. Paste one real listing -> fields extracted live -> map shows rent per person and walk/bike time -> change one roommate's weights -> fair pick flips -> breakdown shows the math.

## Judging (what we are graded on)
Technical Depth, Product Thinking & Impact, Originality & Insight, Execution & Polish. Anything that is just "call an API and show the output" scores badly. Scoring, group pick, validation and caching are our own code.

## Defaults
Campus UCLA, 3 roommates, 35-minute walk circle.

## Do not use
banana-claude plugin, Base44, Paper, Fetch.ai, Browser Use, accounts, a database.

## Working rules
Edit only the files I own (see File ownership). Ask before adding a dependency. Run tests before saying a step is done. Explain each new file in plain English. Never ask me to paste a key into chat.

## Who am I talking to?
Each person keeps a git-ignored `CLAUDE.local.md` with one line, e.g. "I am Freddy (AI and backend)." If it is missing, ask which person you are working with before editing files.

## Current tasks
@TASKS.md
