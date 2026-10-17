# Should I Live Here?

Roommates paste apartment listings, each sets what matters to them, and the app picks the place
that is fairest for the whole group, with the math shown. Built for LA Hacks 2026 (Applied Intelligence).

## How it decides
1. **Gemini** reads pasted listing text and returns structured fields (rent, price type, laundry, parking, red flags). Missing facts stay "unknown".
2. **Google Routes API** gives real walk and bike times to campus. Results are cached.
3. **Our scoring code** gives each listing a 0–100 score per roommate from that roommate's own weights and budget.
4. **Fairest pick** = the listing where the least-happy roommate is happiest (maximin), with ties broken by average score. The app names who gives up the most and on what.

## Setup
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then add your own keys
.venv/bin/uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000. The demo listings work without any keys; pasting a new listing needs `GEMINI_API_KEY`.

On an Intel Mac, if `pip` fails building `cryptography`, run `.venv/bin/pip install --only-binary=cryptography cryptography` first.

## Tests
```bash
.venv/bin/python -m pytest -q
```

## Notes
The demo listings in `data/demo_listings.json` are sample data for the demo, not real listings.
Code was written with help from Claude Code.
