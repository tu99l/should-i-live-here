"""FastAPI backend. Run with:  .venv/bin/uvicorn app.main:app --reload"""
import json
import os
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from . import extract, group, group_store, maps_lookup, photon_bot, rentcast, share, wishes  # noqa: E402  (imports read .env, so load it first)
from .models import DecideRequest, Listing, ParseRequest, TravelMode  # noqa: E402
from .wishes import Wishes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NO_LISTINGS = "No places on the map yet. Search near your place, or paste a listing in step 4."
WISHES_DOWN = ("Couldn't reach Gemini to read that just now. Short texts like \"laundry 5, rent 3\" still work, "
               "or try again in a minute.")
app = FastAPI(title="Should I Live Here?")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.middleware("http")
async def only_share_page_from_outside(request, call_next):
    """Requests through the share tunnel may only see the view-only results (share.py). Everything else,
    including anything that costs API calls or changes the group, answers 404 to them."""
    if share.from_outside(request.headers.get("host", ""), request.headers) and \
            not share.allowed_from_outside(request.method, request.url.path):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return await call_next(request)


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
    return group.decide(req.listings, req.roommates, commutes, facts, req.group_size)


@app.post("/api/wishes")
def read_wishes(req: ParseRequest) -> Wishes:
    """A roommate's own words -> what they want (checked quotes). Same reader as the iMessage bot."""
    try:
        return wishes.parse_wishes(req.text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=WISHES_DOWN) from e


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
    try:
        found = maps_lookup.find_place(q)
    except maps_lookup.MapsUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
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
    try:
        center = maps_lookup.find_place(req.place)
    except maps_lookup.MapsUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
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


# ---------- The group: one list of people, shared with the iMessage bot (group_store.py) ----------

def _group_view() -> dict:
    return group_store.public_view(group_store.read(), photon_bot.text_link)


def _read_wishes(text: str) -> Optional[wishes.Wishes]:
    """Their words -> checked wishes, before taking the group's lock (Gemini can take a few seconds)."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return wishes.parse_wishes(text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=WISHES_DOWN) from e


def _apply(person: group_store.Person, w: Optional[wishes.Wishes], text: Optional[str]) -> None:
    if w is not None and not w.is_empty():
        person.roommate = wishes.apply_wishes(person.roommate, w)
        person.last_text = text


def _person_or_404(g: group_store.Group, name: str) -> group_store.Person:
    person = g.find(name)
    if person is None:
        raise HTTPException(status_code=404, detail=f"No one called {name!r} in the group.")
    return person


@app.get("/api/group")
def get_group() -> dict:
    """Everyone in the group, their wishes and texting status (last 4 phone digits only). `version` changes on every edit."""
    return _group_view()


class MeRequest(BaseModel):
    name: str = Field("You", min_length=1, max_length=40)
    text: Optional[str] = Field(None, max_length=600)
    place: Optional[str] = Field(None, max_length=120)
    size: Optional[int] = Field(None, ge=1, le=10)


@app.post("/api/group/me")
def set_me(req: MeRequest) -> dict:
    """The welcome screen: who you are, what you want (your words), where the group goes, how many of you."""
    w = _read_wishes(req.text)
    name = " ".join(req.name.split())
    with group_store.editing() as g:
        me = next((p for p in g.people if p.me), None)
        if me is None:
            me = group_store.Person(name=name, me=True, roommate=group_store.starting_roommate(name))
            g.people.insert(0, me)
        me.name = me.roommate.name = name
        _apply(me, w, req.text)
        if req.place and req.place.strip():
            g.place = req.place.strip()
        if req.size:
            g.size = req.size
    return {"group": _group_view(), "understood": w.model_dump() if w else None}


class PersonRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    text: Optional[str] = Field(None, max_length=600)
    budget: Optional[float] = Field(None, gt=0)


@app.post("/api/group/people")
def add_person(req: PersonRequest) -> dict:
    """Add someone without a phone (you type what they want). To invite by text, use /api/roommates/invite."""
    w = _read_wishes(req.text)
    name = " ".join(req.name.split())
    with group_store.editing() as g:
        if g.find(name):
            raise HTTPException(status_code=409, detail=f"{name} is already in the group.")
        person = group_store.Person(name=name, roommate=group_store.starting_roommate(name, req.budget or 1500))
        _apply(person, w, req.text)
        g.people.append(person)
        g.size = max(g.size, len(g.people))
    return {"group": _group_view(), "understood": w.model_dump() if w else None}


class WishText(BaseModel):
    text: str = Field(..., min_length=1, max_length=600)


@app.post("/api/group/people/{name}/wishes")
def add_wishes(name: str, req: WishText) -> dict:
    """Someone's words -> their wishes, added to what they already said (same reader as the bot)."""
    w = _read_wishes(req.text)
    with group_store.editing() as g:
        _apply(_person_or_404(g, name), w, req.text)
    return {"group": _group_view(), "understood": w.model_dump() if w else None}


class PersonEdit(BaseModel):
    budget: Optional[float] = Field(None, gt=0)
    place: Optional[str] = Field(None, max_length=200)  # "" = the group's place.
    travel_mode: Optional[TravelMode] = None


@app.patch("/api/group/people/{name}")
def edit_person(name: str, req: PersonEdit) -> dict:
    with group_store.editing() as g:
        r = _person_or_404(g, name).roommate
        if req.budget is not None:
            r.budget = req.budget
        if req.place is not None:
            r.place = req.place.strip() or None
        if req.travel_mode is not None:
            r.travel_mode = req.travel_mode
    return _group_view()


@app.delete("/api/group/people/{name}")
def remove_person(name: str) -> dict:
    """Take someone out of the group. Their seat on the iMessage line stays (Photon dashboard to release it)."""
    with group_store.editing() as g:
        person = _person_or_404(g, name)
        g.people.remove(person)
    return _group_view()


class GroupEdit(BaseModel):
    place: Optional[str] = Field(None, max_length=120)
    size: Optional[int] = Field(None, ge=1, le=10)


@app.patch("/api/group")
def edit_group(req: GroupEdit) -> dict:
    with group_store.editing() as g:
        if req.place is not None and req.place.strip():
            g.place = req.place.strip()
        if req.size is not None:
            g.size = req.size
    return _group_view()


@app.post("/api/group/demo")
def load_demo_group() -> dict:
    """Alex, Sam and Jordan with their usual priorities, the 12 demo listings, UCLA. For judging: no phones needed."""
    with group_store.editing() as g:
        g.people = group_store.demo_people()
        g.place, g.size, g.listings = "UCLA", 3, None
    return _group_view()


@app.post("/api/group/reset")
def reset_group() -> dict:
    """Start over: nobody in the group, demo listings, UCLA. Seats on the iMessage line are not released."""
    with group_store.editing() as g:
        g.people, g.place, g.size, g.listings = [], "UCLA", 3, None
    return _group_view()


class ListingsRequest(BaseModel):
    listings: list[Listing]


@app.get("/api/group/listings")
def group_listings() -> list[Listing]:
    """The places on the group's map: what was saved (searches, pasted), else the 12 demo listings."""
    return group_store.read().current_listings()


@app.put("/api/group/listings")
def save_listings(req: ListingsRequest) -> dict:
    """The places on the page's map, so the bot picks from the same ones (RentCast results, pasted listings)."""
    with group_store.editing() as g:
        g.listings = req.listings
    return {"saved": len(req.listings)}


@app.post("/api/group/decide")
def decide_for_group() -> dict:
    """The fair pick for the whole group over the group's listings: exactly what the bot texts back."""
    g = group_store.read()
    if not g.people:
        raise HTTPException(status_code=400, detail="Nobody in the group yet.")
    if not g.current_listings():
        raise HTTPException(status_code=400, detail=NO_LISTINGS)
    return photon_bot.run_decision(g.roommates(), g.current_listings(), g.place, g.size)


# ---------- View-only results link for roommates (share.py, scripts/share_link.py) ----------

_share_cache: dict = {}  # {group version: decision}, so phones refreshing don't redo the work.
_share_lock = __import__("threading").Lock()  # Many phones at once: the first computes, the rest reuse it.


def _check_code(code: str) -> None:
    if not secrets_equal(code, share.code()):
        raise HTTPException(status_code=404, detail="Not found")


def secrets_equal(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())


@app.get("/share/{code}")
def share_page(code: str):
    _check_code(code)
    return FileResponse(ROOT / "static" / "share.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/share/{code}")
def share_data(code: str) -> dict:
    """Everything the view-only page shows: the group (no phone numbers), the listings, the fair pick."""
    _check_code(code)
    g = group_store.read()
    people = [{"name": p.name, "me": p.me, "connected": p.connected, "invited": bool(p.line),
               "last_text": p.last_text, "roommate": p.roommate.model_dump(exclude={"place"}) | {"place": p.roommate.place}}
              for p in g.people]
    decision = None
    if g.people:
        with _share_lock:
            if g.version not in _share_cache:
                _share_cache.clear()
                _share_cache[g.version] = (photon_bot.run_decision(g.roommates(), g.current_listings(), g.place, g.size)
                                           if g.current_listings() else None)
            decision = _share_cache[g.version]
    listings = [l.model_dump(include={"id", "title", "address", "lat", "lng", "rent_total_monthly", "listed_price",
                                      "rent_per_person_listed", "bedrooms", "bathrooms", "laundry", "parking",
                                      "walk_minutes", "bike_minutes", "red_flags", "price_check", "property_type",
                                      "square_feet", "source"}) for l in g.current_listings()]
    if decision:
        # The page shows the full breakdown only for the pick; other places need just each person's score.
        # (Keeps the download small for phones on cellular: ~170 KB -> ~35 KB for 50 places.)
        decision = {**decision, "ranking": [
            r if r["listing_id"] == decision["pick"]["listing_id"] else
            {**r, "per_roommate": [{"roommate": p["roommate"], "score": p["score"]} for p in r["per_roommate"]]}
            for r in decision["ranking"]]}
    return {"version": g.version, "place": g.place, "size": g.size, "people": people,
            "listings": listings, "decision": decision}


@app.get("/api/share")
def share_status() -> dict:
    """For this laptop's page: the link to send roommates (None while no tunnel is running)."""
    return {"link": share.link()}
