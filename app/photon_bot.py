"""Optional step 7: roommates text their wishes over iMessage (Photon) and get the fair pick back.

A roommate texts anything, e.g. "i want to be close to a gym, laundry included, need gas and
water included". The bot:
1. finds who sent it by phone number (data/roommates.local.json, git-ignored: phone numbers
   never go in the public repo),
2. reads the wishes (wishes.py: plain code for short texts, Gemini + quote checks for long ones),
3. saves them on that roommate, looks up the facts (Google Maps, listing quotes; all cached),
4. runs our own fair pick (group.py) for the whole group over the demo listings,
5. texts back what it understood, the pick, and who is least happy and why.

Photon is called over plain HTTPS from Python (httpx). Every reply is sent with an
idempotency key built from the incoming message ID, so a retry can never double-text.

Run it:  .venv/bin/python -m app.photon_bot
Needs PHOTON_API_KEY and PHOTON_PROJECT_ID in .env, and each roommate assigned to the shared
line in the Photon dashboard (and they must text the line first).
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

from . import group, maps_lookup, wishes
from .cache import CACHE_DIR
from .models import Listing, Roommate

ROOT = Path(__file__).resolve().parent.parent
ROSTER_FILE = ROOT / "data" / "roommates.local.json"      # Real numbers, git-ignored.
ROSTER_EXAMPLE = ROOT / "data" / "roommates.example.json"  # Fake numbers, committed.
STATE_FILE = CACHE_DIR / "bot" / "state.json"              # Saved wishes + answered message IDs.
API = "https://api.photon.codes/v1"
POLL_SECONDS = 2

HELP = ("Text me what you want in a place, in your own words, e.g. \"close to a gym, laundry included, "
        "need gas and water included\" or \"laundry 5, rent 3\". I'll find the fairest pick for the group.\n"
        "\"pick\" = current pick, \"reset\" = clear your wishes.")


# ---------- Roommates and saved state ----------

def load_roster() -> dict:
    """{"roommates": [{name, phone, budget, weights...}]}. Local file if present, else the example."""
    path = ROSTER_FILE if ROSTER_FILE.exists() else ROSTER_EXAMPLE
    return json.loads(path.read_text())


def phone_key(handle: str) -> str:
    """Compare phone numbers by digits only, so "+1 (424) ..." and "+1424..." match."""
    digits = "".join(c for c in handle if c.isdigit())
    return digits if digits else handle.strip().casefold()


def load_state(roster: dict) -> dict:
    state = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            state = {}
    saved = state.get("roommates", {})
    roommates = {}
    for entry in roster["roommates"]:
        base = Roommate(**{k: v for k, v in entry.items() if k != "phone"})
        roommates[base.name] = Roommate(**saved[base.name]) if base.name in saved else base
    return {"answered": state.get("answered", []), "since": state.get("since"), "roommates": roommates}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "answered": state["answered"][-500:],
        "since": state["since"],
        "roommates": {n: r.model_dump() for n, r in state["roommates"].items()},
    }, indent=2))


def demo_listings() -> list[Listing]:
    return [Listing(**d) for d in json.loads((ROOT / "data" / "demo_listings.json").read_text())]


# ---------- Turning a text into a reply (plain code; testable without Photon) ----------

def _money(x: Optional[float]) -> str:
    return "unknown" if x is None else f"${x:,.0f}"


_PLAIN = {("laundry", "shared"): "the shared laundry", ("laundry", "none"): "no laundry",
          ("parking", "paid"): "paying for parking", ("parking", "none"): "no parking"}


def _reason_text(reason: dict) -> str:
    """One reason in everyday words, e.g. "a 16-minute walk to Chipotle Mexican Grill"."""
    c, raw = reason["criterion"], reason["raw_value"]
    if reason.get("kind") == "near":
        return f"a {raw:.0f}-minute walk to {reason.get('place_name') or 'the nearest ' + c.split(': ', 1)[1]}"
    if reason.get("kind") == "feature":
        return f"no {c.split(': ', 1)[1]} (listing says \"{reason.get('evidence')}\")"
    if c == "rent":
        return f"rent at {_money(raw)} each"
    if c == "commute":
        return f"a {raw:.0f}-minute commute"
    if c == "bedrooms":
        return f"only {raw} bedrooms"
    return _PLAIN.get((c, raw), f"{c} ({raw})")


def _reasons_text(reasons: list[dict]) -> str:
    return " and ".join(_reason_text(r) for r in reasons) or "nothing big"


def _wish_status(row: dict) -> str:
    """How the pick does on one of this roommate's own wishes."""
    name = row["criterion"].split(": ", 1)[1]
    if row["unknown"]:
        return f"{name}: listing doesn't say" if row.get("kind") == "feature" else f"{name}: unknown"
    if row.get("kind") == "near":
        return f"{name}: {row.get('place_name')}, {row['raw_value']:g} min walk"
    return f"{name}: {'yes' if row['raw_value'] else 'no'} (\"{row.get('evidence')}\")"


def pick_summary(decision: dict, roommate_name: str) -> str:
    pick, least = decision["pick"], decision["least_happy"]
    row = next(r for r in decision["ranking"] if r["listing_id"] == pick["listing_id"])
    names = [s["roommate"] for s in pick["scores"]]
    mine = next(p for p in row["per_roommate"] if p["roommate"] == roommate_name)
    lines = [f"Fairest pick for {', '.join(names[:-1])} & {names[-1]}: {pick['title']}, "
             f"{_money(row['rent_per_person'])} each."]
    my_score = mine["score"]
    lines.append(f"You: {my_score:g}/100." if my_score is not None else "You: not enough facts to score.")
    why = _reasons_text(least["reasons"])
    if least["roommate"] != roommate_name or len(names) == 1:
        score = "?" if least["score"] is None else f"{least['score']:g}"
        lines.append(f"Least happy: {least['roommate']} ({score}), mostly because of {why}.")
    else:
        lines.append(f"You're the least happy here, mostly because of {why}. "
                     "Every other place leaves someone worse off.")
    own = [b for b in mine["breakdown"] if b.get("kind")]
    if own:
        lines.append("Your wishes there: " + "; ".join(_wish_status(b) for b in own) + ".")
    return "\n".join(lines)


def run_decision(roommates: list[Roommate], listings: list[Listing]) -> dict:
    """Our own scoring and fair pick, with facts from Google and the listing texts (cached)."""
    commutes = maps_lookup.commutes_for(listings, roommates)
    facts = wishes.want_facts_for(listings, roommates)
    return group.decide(listings, roommates, commutes, facts)


def handle_text(name: str, text: str, state: dict, roster: dict, listings: list[Listing]) -> str:
    """One incoming text from a known roommate -> the reply. Updates state["roommates"]."""
    command = text.strip().casefold().rstrip("?!.")
    roommates = state["roommates"]
    if command in ("help", "hi", "hello", "hey", "start"):
        return f"Hi {name}! " + HELP
    if command == "reset":
        entry = next(e for e in roster["roommates"] if e["name"] == name)
        roommates[name] = Roommate(**{k: v for k, v in entry.items() if k != "phone"})
        return f"Cleared your wishes, {name}. Back to your starting priorities.\n\n" + \
            pick_summary(run_decision(list(roommates.values()), listings), name)
    if command in ("pick", "status", "results"):
        return pick_summary(run_decision(list(roommates.values()), listings), name)

    w = wishes.parse_wishes(text)
    if w.is_empty():
        return "I couldn't find any apartment wishes in that. " + HELP
    roommates[name] = wishes.apply_wishes(roommates[name], w)
    parts = [f"Got it, {name}: " + "; ".join(wishes.describe(w)) + "."] if wishes.describe(w) else []
    if w.cannot_check:
        parts.append("Can't check " + ", ".join(f'"{q}"' for q in w.cannot_check)
                     + ": no listing or map shows that, so it's not scored.")
    if w.not_understood:
        parts.append("Didn't catch " + ", ".join(f'"{q}"' for q in w.not_understood) + ".")
    parts.append(pick_summary(run_decision(list(roommates.values()), listings), name))
    return "\n\n".join(parts)


# ---------- Photon over HTTPS ----------

class Photon:
    def __init__(self, key: str, project: str, http: Optional[httpx.Client] = None):
        self.project = project
        self.http = http or httpx.Client(base_url=API, timeout=30)
        self.http.headers["Authorization"] = f"Bearer {key}"

    def received_since(self, since: str) -> list[dict]:
        """iMessages people sent to our line since an RFC 3339 time, oldest first."""
        items, query = [], {"createdSince": since, "direction": "received", "order": "asc",
                            "pageSize": 100, "platform": "imessage"}
        while True:
            r = self.http.get(f"/projects/{self.project}/messages", params=query)
            r.raise_for_status()
            page = r.json()
            items += page.get("items", [])
            token = page.get("nextPageToken")
            if not isinstance(token, str):
                return items
            query["pageToken"] = token

    def send_text(self, incoming: dict, text: str) -> None:
        """Reply in the same conversation. Same idempotency key on retry = never sent twice."""
        body = {"spaceId": incoming["space"]["id"], "senderId": incoming["receivedBy"]["id"],
                "content": {"type": "text", "format": "plain", "text": text}}
        headers = {"Idempotency-Key": f"silh-reply:{incoming['id']}"}
        for attempt in range(2):
            try:
                r = self.http.post(f"/projects/{self.project}/messages", json=body, headers=headers)
                if r.status_code < 500:
                    r.raise_for_status()
                    return
            except httpx.TransportError:
                if attempt == 1:
                    raise
        r.raise_for_status()

    def typing(self, incoming: dict) -> None:
        """Show "..." while we look things up. Nice to have, so failures are ignored."""
        try:
            self.http.post(f"/projects/{self.project}/messages",
                           json={"spaceId": incoming["space"]["id"], "senderId": incoming["receivedBy"]["id"],
                                 "content": {"type": "space.typing.update", "typing": True}},
                           headers={"Idempotency-Key": f"silh-typing:{incoming['id']}"})
        except httpx.HTTPError:
            pass


def _text_of(message: dict) -> Optional[str]:
    content = message.get("content") or {}
    return content.get("text") if content.get("type") == "text" else None


def process(photon: Photon, state: dict, roster: dict, listings: list[Listing], log=print) -> int:
    """Answer every new text once. Returns how many were answered."""
    phones = {phone_key(e["phone"]): e["name"] for e in roster["roommates"] if e.get("phone")}
    answered = 0
    for m in photon.received_since(state["since"]):
        sender = (m.get("sentBy") or {})
        if m["id"] in state["answered"] or m.get("status") != "received" or sender.get("kind") != "human":
            continue
        text = _text_of(m)
        state["answered"].append(m["id"])  # Marked first: a crash mid-reply never causes a double answer.
        state["since"] = max(state["since"], m["createdAt"])
        save_state(state)
        if not text or (m.get("space") or {}).get("kind") != "direct":
            continue
        name = phones.get(phone_key(sender.get("handle", "")))
        log(f"<- {name or 'unknown number'}: {text}")
        if name is None:
            reply = "Hi! I don't know this number yet. Ask your group to add you to the roommate list."
        else:
            photon.typing(m)
            try:
                reply = handle_text(name, text, state, roster, listings)
                save_state(state)
            except Exception as e:  # Never leave someone on read: say so and keep running.
                log(f"!! error handling text: {e!r}")
                reply = "Sorry, something went wrong looking that up. Try again in a minute."
        photon.send_text(m, reply)
        log(f"-> {reply}\n")
        answered += 1
    return answered


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    key, project = os.getenv("PHOTON_API_KEY"), os.getenv("PHOTON_PROJECT_ID")
    if not key or not project:
        sys.exit("Set PHOTON_API_KEY and PHOTON_PROJECT_ID in .env first.")
    roster = load_roster()
    if not ROSTER_FILE.exists():
        print(f"Note: using {ROSTER_EXAMPLE.name} (fake numbers). Copy it to {ROSTER_FILE.name} with real ones.")
    state = load_state(roster)
    if not state["since"]:  # First run: don't answer texts sent before the bot existed.
        state["since"] = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
        save_state(state)
    photon = Photon(key, project)
    listings = demo_listings()
    print(f"Listening for texts to the Photon line. Roommates: {', '.join(state['roommates'])}. Ctrl+C to stop.")
    while True:
        try:
            process(photon, state, roster, listings)
        except httpx.HTTPError as e:
            print(f"Photon error, will retry: {e}", file=sys.stderr)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
