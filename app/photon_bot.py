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

from . import group, group_store, maps_lookup, share, wishes
from .cache import CACHE_DIR
from .models import Listing, Roommate

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = CACHE_DIR / "bot" / "state.json"  # Which texts were answered. People and wishes: group_store.
API = "https://api.photon.codes/v1"
POLL_SECONDS = 2

HELP = ("Text me what you want in a place, in your own words: max rent, own bedroom or bathroom, laundry, parking, "
        "what you want nearby (gym, groceries, coffee, parks), where you go most days and how. "
        "Text again anytime to add or change something.\n"
        "\"pick\" = current pick, \"reset\" = clear your wishes.")


# ---------- The group (shared with the web page) and the bot's own bookkeeping ----------

def phone_key(handle: str) -> str:
    """Compare phone numbers by digits only, so "+1 (424) ..." and "+1424..." match."""
    digits = "".join(c for c in handle if c.isdigit())
    return digits if digits else handle.strip().casefold()


def normalize_phone(raw: str) -> str:
    """Any way people type a number -> "+14245550100" (the format Photon needs). US numbers may skip the +1."""
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 10 and not raw.strip().startswith("+"):
        digits = "1" + digits
    if not 8 <= len(digits) <= 15 or digits.startswith("0"):
        raise ValueError(f"That doesn't look like a phone number: {raw!r}")
    return "+" + digits


def load_state() -> dict:
    """Which texts the bot already answered, and from when to look. The group itself is in group_store."""
    state = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            state = {}
    return {"answered": state.get("answered", []), "since": state.get("since")}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    old = {}
    if STATE_FILE.exists():  # Keep anything else in the file (older versions kept wishes here).
        try:
            old = json.loads(STATE_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            old = {}
    old.update(answered=state["answered"][-500:], since=state["since"])
    STATE_FILE.write_text(json.dumps(old, indent=2))


def with_group_place(roommates: list[Roommate], place: str) -> list[Roommate]:
    """Everyone without their own place commutes to the group's place (UCLA = the default campus)."""
    if not place or place.strip().casefold() == "ucla":
        return roommates
    return [r if (r.place or "").strip() else r.model_copy(update={"place": place}) for r in roommates]


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
    if reason.get("kind") == "bathroom":
        return f"only {raw:g} bathrooms when {reason.get('needed')} are needed for own bathrooms"
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
    name = row["criterion"].split(": ", 1)[-1]
    if row.get("kind") == "bathroom":
        if row["unknown"]:
            return "own bathroom: unknown"
        return f"own bathroom: {'yes' if row['criterion_score'] else 'no'} ({row['raw_value']:g} baths, {row.get('needed')} needed)"
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
    rent = f"{_money(row['rent_per_person'])} each" if row["rent_per_person"] is not None else "rent unknown"
    lines = [f"Fairest pick for {', '.join(names[:-1])} & {names[-1]}: {pick['title']}, {rent}."]
    if pick.get("warning"):
        lines.append(f"⚠ {pick['warning']}")
        alt = decision.get("alternate")
        if alt:
            alt_rent = f"{_money(alt['rent_per_person'])} each" if alt["rent_per_person"] is not None else "rent unknown"
            lines.append(f"Fairest place with rent, bedrooms and bathrooms all known: {alt['title']}, {alt_rent}.")
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


def run_decision(roommates: list[Roommate], listings: list[Listing], place: str = "UCLA",
                 group_size: Optional[int] = None) -> dict:
    """Our own scoring and fair pick, with facts from Google and the listing texts (cached)."""
    roommates = with_group_place(roommates, place)
    commutes = maps_lookup.commutes_for(listings, roommates)
    facts = wishes.want_facts_for(listings, roommates)
    return group.decide(listings, roommates, commutes, facts, group_size)


def current_pick(name: str) -> str:
    """The pick as text for one person, plus the map link when one is running. Notes pick changes (see changed_pick)."""
    g = group_store.read()
    decision = run_decision(g.roommates(), g.current_listings(), g.place, g.size)
    _pick_seen[name] = decision["pick"]
    text = pick_summary(decision, name)
    url = share.link()
    return text + (f"\nSee the map and everyone's scores: {url}" if url else "")


_pick_seen: dict[str, dict] = {}  # name -> the pick their latest reply showed.


def changed_pick(name: str) -> Optional[dict]:
    """If the pick shown to `name` differs from the one the group was last told about, record it and return it."""
    pick = _pick_seen.pop(name, None)
    if not pick:
        return None
    with group_store.editing() as g:
        if g.last_pick == pick["listing_id"]:
            return None
        first = g.last_pick is None
        g.last_pick = pick["listing_id"]
    return None if first else pick


def tell_group(photon: "Photon", changed_by: str, pick: dict, log=print) -> int:
    """Text everyone else who has texted the bot that the pick changed. Returns how many were told."""
    g = group_store.read()
    url = share.link()
    told = 0
    for p in g.people:
        if p.name == changed_by or not (p.space_id and p.agent_id):
            continue
        text = (f"Update: {changed_by} changed what they want, and the fairest pick is now {pick['title']}."
                + (f"\nSee the map: {url}" if url else "\nText \"pick\" for the details."))
        try:
            photon.send_to(p.space_id, p.agent_id, text, key=f"silh-pick:{g.version}:{p.name}")
            told += 1
            log(f"-> {p.name} (update): {text}")
        except httpx.HTTPError as e:
            log(f"!! couldn't tell {p.name}: {e!r}")
    return told


def handle_text(name: str, text: str) -> str:
    """One incoming text from a person in the group -> the reply. Saves their wishes in the shared group."""
    command = text.strip().casefold().rstrip("?!.")
    if command in ("help", "hi", "hello", "hey", "start"):
        return f"Hi {name}! " + HELP
    if command == "reset":
        with group_store.editing() as g:
            person = g.find(name)
            person.roommate = group_store.starting_roommate(person.name, person.roommate.budget)
            person.last_text = None
        return f"Cleared your wishes, {name}.\n\n" + current_pick(name)
    if command in ("pick", "status", "results"):
        return current_pick(name)

    w = wishes.parse_wishes(text)  # Slow (Gemini): done before taking the group's lock.
    if w.is_empty():
        return "Tell me what matters to you in a place. " + HELP
    with group_store.editing() as g:
        person = g.find(name)
        person.roommate = wishes.apply_wishes(person.roommate, w)
        person.last_text = text
    parts = [f"Got it, {name}: " + "; ".join(wishes.describe(w)) + "."] if wishes.describe(w) else []
    if w.cannot_check:
        parts.append("Can't check " + ", ".join(f'"{q}"' for q in w.cannot_check)
                     + ": no listing or map shows that, so it's not scored.")
    if w.not_understood:
        parts.append("Didn't catch " + ", ".join(f'"{q}"' for q in w.not_understood) + ".")
    parts.append(current_pick(name))
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
        self.send_to(incoming["space"]["id"], incoming["receivedBy"]["id"], text, key=f"silh-reply:{incoming['id']}")

    def send_to(self, space_id: str, agent_id: str, text: str, key: str) -> None:
        """Text someone in their conversation with the bot (allowed once they've texted the line)."""
        body = {"spaceId": space_id, "senderId": agent_id,
                "content": {"type": "text", "format": "plain", "text": text}}
        headers = {"Idempotency-Key": key}
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

    def assign(self, phone: str, first_name: str, email: Optional[str] = None) -> str:
        """Add someone to our shared iMessage line. Returns the number THEY should text.

        Each person can get a different number from Photon's pool. With an email, Photon also
        sends them an invite. Already added -> their existing number (no second seat used).
        """
        body = {"handle": phone, "firstName": first_name[:100]}
        if email:
            body["email"] = email
        r = self.http.post(f"/projects/{self.project}/platforms/imessage/assignments", json=body,
                           headers={"Idempotency-Key": f"silh-assign:{phone_key(phone)}"})
        if r.is_success:
            return r.json()["assignedPhoneNumber"]
        existing = self.assignment_for(phone)
        if existing:
            return existing
        r.raise_for_status()
        raise RuntimeError("Photon did not return a number.")

    def assignment_for(self, phone: str) -> Optional[str]:
        """The line number someone already has, or None."""
        r = self.http.get(f"/projects/{self.project}/platforms/imessage/assignments", params={"pageSize": 200})
        r.raise_for_status()
        for a in r.json().get("assignments", []):
            if phone_key(a.get("handle", "")) == phone_key(phone):
                return a.get("assignedPhoneNumber")
        return None

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


def greeting(name: str, group: group_store.Group) -> str:
    """The first text someone gets: who we are, and what to tell us (only things we can actually check)."""
    names = [p.name for p in group.people]
    group_names = ", ".join(names[:-1]) + " & " + names[-1] if len(names) > 1 else names[0]
    return (f"Hi {name}! I'm the apartment bot for {group_names}. I'll find the place that's fairest for everyone.\n"
            "Tell me in your own words, as much or as little as you like:\n"
            "• Your max rent per month\n"
            "• Own bedroom? Own bathroom?\n"
            "• Laundry (in-unit?) and parking (free?)\n"
            "• What you want nearby: gym, grocery store, coffee, parks…\n"
            "• Where you go most days and how (walk, bike, transit, drive)\n"
            "• Anything that's a deal-breaker\n"
            "You can text again anytime to add or change something. Text \"pick\" to see the current pick.")


def process(photon: Photon, state: dict, log=print) -> int:
    """Answer every new text once. Returns how many were answered."""
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
        group = group_store.read()  # Fresh for every text: the page or an earlier text may have changed it.
        phones = {phone_key(p.phone): p.name for p in group.people if p.phone}
        name = phones.get(phone_key(sender.get("handle", "")))
        log(f"<- {name or 'unknown number'}: {text}")
        if name is None:
            reply = "Hi! I don't know this number yet. Ask your group to add you to the roommate list."
        elif not group.find(name).connected:
            # Their first text (usually the pre-filled "Hi, it's Sam"): say hello and ask what they want.
            with group_store.editing() as g:
                person = g.find(name)
                person.connected = True
                person.space_id, person.agent_id = m["space"]["id"], m["receivedBy"]["id"]
            reply = greeting(name, group)
            if not wishes.quick_parse(text) and len(text.split()) > 6:  # They already said what they want.
                try:
                    reply += "\n\n" + handle_text(name, text)
                except Exception as e:
                    log(f"!! error handling text: {e!r}")
        else:
            photon.typing(m)
            try:
                reply = handle_text(name, text)
            except Exception as e:  # Never leave someone on read: say so and keep running.
                log(f"!! error handling text: {e!r}")
                reply = "Sorry, something went wrong looking that up. Try again in a minute."
        photon.send_text(m, reply)
        log(f"-> {reply}\n")
        answered += 1
        if name:
            person = group_store.read().find(name)
            if person and not person.space_id:  # Texted before we kept conversations: remember it now.
                with group_store.editing() as g:
                    g.find(name).space_id, g.find(name).agent_id = m["space"]["id"], m["receivedBy"]["id"]
            pick = changed_pick(name)
            if pick:
                tell_group(photon, name, pick, log)
    return answered


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    key, project = os.getenv("PHOTON_API_KEY"), os.getenv("PHOTON_PROJECT_ID")
    if not key or not project:
        sys.exit("Set PHOTON_API_KEY and PHOTON_PROJECT_ID in .env first.")
    state = load_state()
    if not state["since"]:  # First run: don't answer texts sent before the bot existed.
        state["since"] = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
        save_state(state)
    photon = Photon(key, project)
    names = ", ".join(p.name for p in group_store.read().people) or "nobody yet"
    print(f"Listening for texts to the Photon line. Group: {names}. Ctrl+C to stop.")
    while True:
        try:
            process(photon, state)
        except httpx.HTTPError as e:
            print(f"Photon error, will retry: {e}", file=sys.stderr)
        time.sleep(POLL_SECONDS)



# ---------- Adding a roommate from the website ----------

STARTER_TEXT = "Hi, it's {name}! Let's find our apartment."


def text_link(line: str, name: str) -> str:
    """Opens Messages with our number and a starter text filled in. "?&body=" works on iPhone and Android."""
    from urllib.parse import quote
    return f"sms:{line}?&body={quote(STARTER_TEXT.format(name=name))}"


def invite_roommate(photon: Photon, name: str, phone: str, email: Optional[str] = None,
                    budget: Optional[float] = None) -> dict:
    """Add (or update) a person: give them a seat on the iMessage line and add them to the shared group.

    They still send the first text (a shared line can't text first), but the website hands them a
    one-tap link with everything filled in, and Photon emails them an invite if we have their email.
    """
    name = " ".join(name.split())
    if not name:
        raise ValueError("Name is required.")
    phone = normalize_phone(phone)
    line = photon.assign(phone, name, email)
    with group_store.editing() as g:
        person = g.find(name) or next((p for p in g.people if p.phone and phone_key(p.phone) == phone_key(phone)), None)
        if person is None:
            person = group_store.Person(name=name, roommate=group_store.starting_roommate(name, budget or 1500))
            g.people.append(person)
        person.name = name
        person.roommate.name = name
        person.phone, person.line = phone, line
        if email:
            person.email = email
        if budget:
            person.roommate.budget = budget
    return {"name": name, "line": line, "text_link": text_link(line, name), "email_invite": bool(email),
            "starter_text": STARTER_TEXT.format(name=name)}


def roster_status() -> list[dict]:
    """Everyone in the group, as the page shows them (last 4 digits only)."""
    view = group_store.public_view(group_store.read(), text_link)
    return [{**p, "budget": p["roommate"]["budget"], "wants": p["roommate"]["wants"]} for p in view["people"]]


if __name__ == "__main__":
    main()
