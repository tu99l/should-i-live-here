"""One group, shared by the web page and the iMessage bot.

Everything about the group lives in one git-ignored file, data/group.local.json:
- people: each person's name, contact details (phone numbers never leave the server whole),
  whether they've texted the bot yet, and their preferences as a Roommate (wishes, budget, commute),
- place: where the group needs to get to most days (commutes are measured there),
- size: how many people the group expects in total (for the bedroom filter before everyone is added),
- listings: the places on the map (None = the 12 demo listings),
- version: goes up by one on every change, so the page can tell when to refresh.

The web server and the bot are two separate programs. Every change goes through `editing()`, which
holds a file lock while it reads, changes and writes, and writes atomically (temp file + rename),
so neither program can overwrite the other's change or read a half-written file.
"""
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from pydantic import BaseModel, Field

from .cache import CACHE_DIR
from .models import Listing, Roommate, Weights

ROOT = Path(__file__).resolve().parent.parent
GROUP_FILE = ROOT / "data" / "group.local.json"
DEMO_LISTINGS = ROOT / "data" / "demo_listings.json"
# Files from before the shared store; read once to carry people and their wishes over.
OLD_ROSTER = ROOT / "data" / "roommates.local.json"
OLD_STATE = CACHE_DIR / "bot" / "state.json"


class Person(BaseModel):
    name: str
    me: bool = False                  # The person who started the group on the welcome screen.
    phone: Optional[str] = None       # E.164, server only.
    email: Optional[str] = None
    line: Optional[str] = None        # The Photon number this person texts.
    connected: bool = False           # Has texted the bot at least once.
    last_text: Optional[str] = None   # Their most recent wish text, shown on the card.
    # Their conversation with the bot (from their first text), so the bot can text them later.
    space_id: Optional[str] = None
    agent_id: Optional[str] = None
    roommate: Roommate


class Group(BaseModel):
    version: int = 0
    place: str = "UCLA"
    size: int = Field(3, ge=1, le=10)
    people: list[Person] = Field(default_factory=list)
    listings: Optional[list[Listing]] = None
    last_pick: Optional[str] = None  # The pick the group was last told about (the bot texts when it changes).

    def find(self, name: str) -> Optional[Person]:
        key = " ".join(name.split()).casefold()
        return next((p for p in self.people if p.name.casefold() == key), None)

    def roommates(self) -> list[Roommate]:
        return [p.roommate for p in self.people]

    def current_listings(self) -> list[Listing]:
        if self.listings is not None:
            return self.listings
        return [Listing(**d) for d in json.loads(DEMO_LISTINGS.read_text())]


def starting_roommate(name: str, budget: float = 1500) -> Roommate:
    """A new person before they've said anything: every built-in criterion at the neutral 3."""
    return Roommate(name=name, budget=budget)


# ---------- Reading and writing ----------

def _migrate() -> Group:
    """Build the group from the older roster + bot state files, if they exist (keeps texted wishes)."""
    group = Group()
    if not OLD_ROSTER.exists():
        return group
    try:
        roster = json.loads(OLD_ROSTER.read_text()).get("roommates", [])
        state = json.loads(OLD_STATE.read_text()) if OLD_STATE.exists() else {}
    except (OSError, json.JSONDecodeError):
        return group
    saved, connected = state.get("roommates", {}), set(state.get("connected", []))
    for i, e in enumerate(roster):
        base = {k: v for k, v in e.items() if k in Roommate.model_fields}
        roommate = Roommate(**saved[e["name"]]) if e["name"] in saved else Roommate(**base)
        group.people.append(Person(name=e["name"], me=(i == 0), phone=e.get("phone"), email=e.get("email"),
                                   line=e.get("line"), connected=e["name"] in connected, roommate=roommate))
    group.size = max(len(group.people), 1)
    return group


def read() -> Group:
    """The group as it is now. Safe without the lock: writes are atomic."""
    if not GROUP_FILE.exists():
        return _migrate()
    try:
        return Group.model_validate_json(GROUP_FILE.read_text())
    except (OSError, ValueError):
        return Group()


def _write(group: Group) -> None:
    GROUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=GROUP_FILE.parent, prefix=".group-", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(group.model_dump_json(indent=2))
    os.replace(tmp, GROUP_FILE)


@contextmanager
def editing() -> Iterator[Group]:
    """Change the group safely: `with editing() as g: ...`. Saved (version + 1) when the block ends."""
    GROUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GROUP_FILE.parent / ".group.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            group = read()
            yield group
            group.version += 1
            _write(group)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


# ---------- The demo group (for judging; no phones needed) ----------

def demo_people() -> list[Person]:
    """Alex, Sam and Jordan with the priorities the demo has always used, each with a sentence that explains them."""
    def person(name, budget, weights, said, **extra):
        r = Roommate(name=name, budget=budget, weights=Weights(**weights), **extra)
        return Person(name=name, last_text=said, roommate=r)
    return [
        person("Alex", 1500, dict(rent=5, commute=2, laundry=3, parking=1, bedrooms=2),
               "Cheap rent matters most to me, I can't go over $1,500. I don't have a car."),
        person("Sam", 1900, dict(rent=2, commute=5, laundry=3, parking=4, bedrooms=3),
               "I want a short walk to campus and somewhere to park."),
        person("Jordan", 1700, dict(rent=3, commute=3, laundry=5, parking=2, bedrooms=3),
               "Laundry is a deal-breaker for me, up to $1,700."),
    ]


def public_view(group: Group, link_for=None) -> dict:
    """The group for the web page. Phone numbers are cut to their last 4 digits."""
    people = []
    for p in group.people:
        people.append({
            "name": p.name, "me": p.me,
            "phone_last4": p.phone[-4:] if p.phone else None,
            "line": p.line,
            "text_link": link_for(p.line, p.name) if (link_for and p.line) else None,
            "connected": p.connected,
            "last_text": p.last_text,
            "roommate": p.roommate.model_dump(),
        })
    return {"version": group.version, "place": group.place, "size": group.size, "people": people,
            "listings_saved": group.listings is not None,
            "listing_count": len(group.listings) if group.listings is not None else None}
