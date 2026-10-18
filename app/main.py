"""FastAPI backend. Run with:  .venv/bin/uvicorn app.main:app --reload"""
import json
import os
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from . import extract, group, maps_lookup, photon_bot, rentcast, wishes  # noqa: E402  (imports read .env, so load it first)
from .models import DecideRequest, Listing, ParseRequest  # noqa: E402
from .wishes import Wishes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Should I Live Here?")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.middleware("http")
async def always_fresh_page(request, call_next):
    """Make browsers re-check the page and its files on every load, so after a git pull
    nobody sees an old cached app.js or styles.css mixed with a new index.html."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


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

    listing = Listing(
        id=uuid.uuid4().hex[:8],
        title=facts.address or "Pasted listing",
        source_text=req.text,  # Kept so "does it have X?" wishes can quote it.
        source="pasted",
        **facts.model_dump(exclude={"rejected"}),
    )
    listing.listed_price = listing.rent_total_monthly or listing.rent_per_person_listed
    dest = (req.destination or "").strip() or None
    listing.commute_to = dest  # None = the default campus.
    if listing.address:
        # Distances, map position and groceries come from Google Maps, never from the model.
        for field, value in maps_lookup.lookup({"address": listing.address}, dest).items():
            setattr(listing, field, value)
    return listing


@app.post("/api/decide")
def decide(req: DecideRequest) -> dict:
    """Score every listing for every roommate and pick the fairest one."""
    if not req.listings or not req.roommates:
        raise HTTPException(status_code=400, detail="Need at least one listing and one roommate.")
    # Each roommate's commute to their own place, from Google (cached). Scoring itself makes no calls.
    commutes = maps_lookup.commutes_for(req.listings, req.roommates)
    # Facts for each roommate's own wishes ("near a gym", "gas included"): Google and listing quotes, cached.
    facts = wishes.want_facts_for(req.listings, req.roommates)
    return group.decide(req.listings, req.roommates, commutes, facts)


@app.post("/api/wishes")
def read_wishes(req: ParseRequest) -> Wishes:
    """A roommate's own words -> what they want (checked quotes). Same reader as the iMessage bot."""
    try:
        return wishes.parse_wishes(req.text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not read that: {e}")


@app.post("/api/explain")
def explain(decision: dict) -> dict:
    """Plain-English summary of a decision that group.decide already made."""
    try:
        return {"text": extract.explain_decision(decision)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not write the explanation: {e}")


# ---------- Roommates for the iMessage bot (app/photon_bot.py) ----------

class InviteRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    phone: str = Field(..., max_length=30)
    email: Optional[str] = Field(None, max_length=254)
    budget: Optional[float] = Field(None, gt=0)


def _photon() -> photon_bot.Photon:
    key, project = os.getenv("PHOTON_API_KEY"), os.getenv("PHOTON_PROJECT_ID")
    if not key or not project:
        raise HTTPException(status_code=503, detail="iMessage is not set up (PHOTON_API_KEY / PHOTON_PROJECT_ID).")
    return photon_bot.Photon(key, project)


@app.post("/api/roommates/invite")
def invite_roommate(req: InviteRequest) -> dict:
    """Add a roommate to the iMessage line. Returns the number they text and a one-tap link to start.

    A shared line can't text first, so they send one pre-filled text; the bot then greets them.
    """
    try:
        return photon_bot.invite_roommate(_photon(), req.name, req.phone, req.email or None, req.budget)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not add them to iMessage: {e}")


@app.get("/api/roommates")
def roommates() -> list[dict]:
    """The bot's group: who has a number, who has texted in ("connected"), and their wishes."""
    return photon_bot.roster_status()


# ---------- Finding a place and real listings near it ----------

@app.get("/api/place")
def place(q: str) -> dict:
    """Text like "UCLA" or "Santa Monica Pier" -> {name, formatted_address, lat, lng} from Google (cached)."""
    found = maps_lookup.find_place(q)
    if not found:
        raise HTTPException(status_code=404, detail=f"Couldn't find {q!r} on the map. Try a fuller name or address.")
    return found


class SearchRequest(BaseModel):
    place: str = Field("UCLA", max_length=200)  # Where the group needs to get to; listings are found around it.
    radius_miles: float = Field(2, gt=0, le=10)
    min_bedrooms: int = Field(1, ge=0, le=10)
    max_rent_per_person: Optional[float] = Field(None, gt=0)
    limit: int = Field(40, ge=1, le=100)  # Each listing shown triggers Google lookups, so keep it modest.


@app.post("/api/search")
def search_listings(req: SearchRequest) -> dict:
    """Real active rentals near the group's place, from RentCast (cached per area: changing the
    filters never costs a request). Laundry and parking come back unknown: RentCast doesn't have them.

    Listings whose price looks like ONE room's price are kept but flagged (price_check, red_flags),
    with rent per person left unknown. Walk and bike times to the place come from Google.
    """
    center = maps_lookup.find_place(req.place)
    if not center:
        raise HTTPException(status_code=404, detail=f"Couldn't find {req.place!r} on the map.")
    try:
        result = rentcast.search(center["lat"], center["lng"], req.radius_miles, req.min_bedrooms,
                                 req.max_rent_per_person, req.limit)
    except rentcast.RentCastError as e:
        raise HTTPException(status_code=502, detail=str(e))
    # Real walk and bike times from each listing to the place (Route Matrix, cached), for the cards.
    shown = result["listings"]
    origins = [{"lat": l.lat, "lng": l.lng} for l in shown]
    is_campus = req.place.strip().casefold() in ("ucla", maps_lookup.destination().casefold())
    dest = maps_lookup.destination() if is_campus else (center["formatted_address"] or req.place)
    for mode, field in (("WALK", "walk_minutes"), ("BICYCLE", "bike_minutes")):
        for listing, minutes in zip(shown, maps_lookup.commute_minutes(origins, dest, mode)):
            setattr(listing, field, minutes)
    for listing in shown:
        listing.commute_to = None if is_campus else dest  # None = the default campus.
    result["place"] = center
    return result
