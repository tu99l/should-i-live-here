# Should I Live Here? (LA Hacks 2026)

Helps student roommates agree on an apartment near UCLA. Pasted listings become map cards;
each roommate sets priorities; our code picks the fairest place and shows the math.

## Rules that matter for judging
- Gemini only extracts facts from pasted text (`app/parser.py`) and writes explanations. It never produces scores, distances or prices.
- All scores come from `app/scoring.py`. Distances come from Google Routes (`app/commute.py`) or the demo data.
- Missing facts stay `None` and show as "unknown". Never guess a value.
- Never commit keys. `.env` is gitignored; `.env.example` holds fake values. The repo is public.
- Cache every paid API response (`data/cache.json`).

## Layout
- `app/main.py`: FastAPI routes (`/api/demo`, `/api/parse`, `/api/decide`, `/api/explain`), serves `static/`
- `app/models.py`: Pydantic shapes for listings, roommates and weights
- `app/scoring.py`: factor scores, per-roommate scores, maximin group decision
- `static/index.html`: Leaflet map + roommate panel (placeholder until the earlier UCLA map is merged in)
- `data/demo_listings.json`: pre-loaded demo listings (sample data, not real listings)

## Commands
- Run: `.venv/bin/uvicorn app.main:app --reload` then open http://127.0.0.1:8000
- Test: `.venv/bin/python -m pytest -q`

## Team
Two people, deadline 12:00 PM Sunday (target submit 11:00 AM). Keep changes small and the demo path working.
