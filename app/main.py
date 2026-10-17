"""FastAPI backend. Run with:  .venv/bin/uvicorn app.main:app --reload"""
import json
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from . import commute, extract, scoring  # noqa: E402  (imports read .env, so load it first)
from .models import DecideRequest, Listing, ParseRequest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Should I Live Here?")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/demo")
def demo_listings() -> list[Listing]:
    """Pre-loaded listings for the demo, so judging never depends on a live API call."""
    return json.loads((ROOT / "data" / "demo_listings.json").read_text())


@app.post("/api/parse")
def parse_listing(req: ParseRequest) -> Listing:
    """Pasted listing text -> structured listing with real commute times."""
    try:
        facts = extract.extract_listing(req.text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not read the listing: {e}")

    listing = Listing(id=uuid.uuid4().hex[:8], evidence=facts.evidence, **extract.to_listing_fields(facts))
    if listing.address:
        listing.walk_minutes = commute.travel_minutes(listing.address, "WALK")
        listing.bike_minutes = commute.travel_minutes(listing.address, "BICYCLE")
    return listing


@app.post("/api/decide")
def decide(req: DecideRequest) -> dict:
    """Score every listing for every roommate and pick the fairest one."""
    if not req.listings or not req.roommates:
        raise HTTPException(status_code=400, detail="Need at least one listing and one roommate.")
    return scoring.decide(req.listings, req.roommates)


@app.post("/api/explain")
def explain(decision: dict) -> dict:
    """Plain-English summary of a decision that scoring.decide already made."""
    try:
        return {"text": extract.explain_decision(decision)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not write the explanation: {e}")
