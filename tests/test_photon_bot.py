"""iMessage bot tests. Photon is a fake server (httpx.MockTransport): nothing is really sent.

Texts here use the short "laundry 5" style, which is read by plain code, and listings with no
wishes to look up, so no Gemini or Google calls happen either.
"""
import json

import httpx
import pytest

from app import cache, photon_bot

ROSTER = {"roommates": [
    {"name": "Freddy", "phone": "+14245550100", "budget": 1500,
     "weights": {"rent": 5, "commute": 2, "laundry": 0, "parking": 1, "bedrooms": 2}},
    {"name": "Sam", "phone": None, "budget": 1900,
     "weights": {"rent": 2, "commute": 5, "laundry": 3, "parking": 4, "bedrooms": 3}},
]}
LISTINGS = [
    photon_bot.Listing(id="cheap", title="Cheap Place", rent_total_monthly=2400, bedrooms=2,
                       walk_minutes=15, laundry="shared", parking="paid"),
    photon_bot.Listing(id="washer", title="Washer Place", rent_total_monthly=3000, bedrooms=2,
                       walk_minutes=15, laundry="in_unit", parking="paid"),
]


@pytest.fixture(autouse=True)
def temp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(photon_bot, "STATE_FILE", tmp_path / "bot" / "state.json")


def incoming(msg_id, text, handle="+14245550100", created="2026-10-18T02:00:00Z"):
    return {"id": msg_id, "status": "received", "createdAt": created,
            "content": {"type": "text", "format": "plain", "text": text},
            "sentBy": {"id": "pho_usr_human", "kind": "human", "handle": handle},
            "receivedBy": {"id": "pho_usr_agent", "kind": "agent", "handle": "+16285550199"},
            "space": {"id": "pho_spc_1", "kind": "direct"}}


class FakePhoton:
    """Answers list, send and line assignments like Photon's API, and records every request."""

    def __init__(self, messages=(), assignments=()):
        self.messages, self.sent, self.requests = list(messages), [], []
        self.assignments = list(assignments)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if "assignments" in request.url.path:
            if request.method == "GET":
                return httpx.Response(200, json={"assignments": self.assignments})
            body = json.loads(request.content)
            if any(a["handle"] == body["handle"] for a in self.assignments):
                return httpx.Response(409, json={"title": "already assigned"})
            a = {"handle": body["handle"], "firstName": body["firstName"], "assignedPhoneNumber": "+16285550199"}
            self.assignments.append(a)
            return httpx.Response(201, json=a)
        if request.method == "GET":
            return httpx.Response(200, json={"items": self.messages})
        body = json.loads(request.content)
        if body["content"]["type"] == "text":
            self.sent.append((request.headers.get("idempotency-key"), body))
        return httpx.Response(202, json={"id": "pho_msg_out"})


def bot(fake):
    http = httpx.Client(base_url=photon_bot.API, transport=httpx.MockTransport(fake))
    return photon_bot.Photon("fake-key", "pho_prj_test", http=http)


def fresh_state(connected=("Freddy",)):
    state = photon_bot.load_state(ROSTER)
    state["since"] = "2026-10-18T00:00:00Z"
    state["connected"] = list(connected)  # Already said hello, so texts are read as wishes.
    return state


def test_a_text_changes_that_roommates_weights_and_replies_with_the_pick():
    state = fresh_state()
    reply = photon_bot.handle_text("Freddy", "laundry 5, rent 0", state, ROSTER, LISTINGS)
    assert state["roommates"]["Freddy"].weights.laundry == 5
    assert state["roommates"]["Freddy"].weights.rent == 0
    assert reply.startswith("Got it, Freddy: rent: don't care; laundry: must-have.")
    assert "Fairest pick for Freddy & Sam: Washer Place, $1,500 each." in reply


def test_reset_and_pick_commands():
    state = fresh_state()
    photon_bot.handle_text("Freddy", "laundry 5", state, ROSTER, LISTINGS)
    reply = photon_bot.handle_text("Freddy", "reset", state, ROSTER, LISTINGS)
    assert state["roommates"]["Freddy"].weights.laundry == 0 and reply.startswith("Cleared")
    assert photon_bot.handle_text("Freddy", "Pick?", state, ROSTER, LISTINGS).startswith("Fairest pick")


def test_each_text_is_answered_once_with_an_idempotency_key():
    fake = FakePhoton([incoming("pho_msg_1", "laundry 5")])
    photon, state = bot(fake), fresh_state()
    assert photon_bot.process(photon, state, ROSTER, LISTINGS, log=lambda *_: None) == 1
    assert photon_bot.process(photon, state, ROSTER, LISTINGS, log=lambda *_: None) == 0  # Not again.
    key, body = fake.sent[0]
    assert key == "silh-reply:pho_msg_1"
    assert body["spaceId"] == "pho_spc_1" and body["senderId"] == "pho_usr_agent"
    assert all(r.headers["authorization"] == "Bearer fake-key" for r in fake.requests)


def test_answered_texts_survive_a_restart():
    fake = FakePhoton([incoming("pho_msg_1", "laundry 5")])
    photon_bot.process(bot(fake), fresh_state(), ROSTER, LISTINGS, log=lambda *_: None)
    restarted = photon_bot.load_state(ROSTER)
    assert restarted["connected"] == ["Freddy"]
    assert photon_bot.process(bot(fake), restarted, ROSTER, LISTINGS, log=lambda *_: None) == 0
    assert restarted["roommates"]["Freddy"].weights.laundry == 5  # Wishes were saved too.


def test_unknown_number_gets_a_polite_reply_and_no_changes():
    fake = FakePhoton([incoming("pho_msg_2", "laundry 5", handle="+19995550123")])
    state = fresh_state()
    photon_bot.process(bot(fake), state, ROSTER, LISTINGS, log=lambda *_: None)
    assert "don't know this number" in fake.sent[0][1]["content"]["text"]
    assert state["roommates"]["Freddy"].weights.laundry == 0


def test_phone_numbers_match_whatever_the_formatting():
    fake = FakePhoton([incoming("pho_msg_3", "help", handle="+1 (424) 555-0100")])
    photon_bot.process(bot(fake), fresh_state(), ROSTER, LISTINGS, log=lambda *_: None)
    assert fake.sent[0][1]["content"]["text"].startswith("Hi Freddy!")


def test_a_crash_while_looking_up_still_gets_a_reply(monkeypatch):
    def boom(*_):
        raise RuntimeError("Google is down")
    monkeypatch.setattr(photon_bot, "run_decision", boom)
    fake = FakePhoton([incoming("pho_msg_4", "laundry 5")])
    photon_bot.process(bot(fake), fresh_state(), ROSTER, LISTINGS, log=lambda *_: None)
    assert fake.sent[0][1]["content"]["text"].startswith("Sorry, something went wrong")


def test_the_example_roster_has_no_real_numbers():
    roster = json.loads(photon_bot.ROSTER_EXAMPLE.read_text())
    assert all(r["phone"] is None or r["phone"].startswith("+1555555") for r in roster["roommates"])


def test_first_text_gets_a_greeting_then_texts_are_wishes():
    fake = FakePhoton([incoming("pho_msg_5", "Hi, it's Freddy! Let's find our apartment.")])
    state = fresh_state(connected=())
    photon_bot.process(bot(fake), state, ROSTER, LISTINGS, log=lambda *_: None)
    reply = fake.sent[0][1]["content"]["text"]
    assert reply.startswith("Hi Freddy! I'm the apartment bot for Freddy & Sam.")
    assert state["connected"] == ["Freddy"] and state["roommates"]["Freddy"].weights.laundry == 0
    fake.messages.append(incoming("pho_msg_6", "laundry 5", created="2026-10-18T02:01:00Z"))
    photon_bot.process(bot(fake), state, ROSTER, LISTINGS, log=lambda *_: None)
    assert fake.sent[1][1]["content"]["text"].startswith("Got it, Freddy")


def test_phone_numbers_are_normalized_or_rejected():
    assert photon_bot.normalize_phone("(424) 555-0100") == "+14245550100"
    assert photon_bot.normalize_phone("+44 20 7946 0958") == "+442079460958"
    for bad in ("12345", "call me", ""):
        with pytest.raises(ValueError):
            photon_bot.normalize_phone(bad)


@pytest.fixture
def temp_roster(tmp_path, monkeypatch):
    path = tmp_path / "roommates.local.json"
    path.write_text(json.dumps(ROSTER))
    monkeypatch.setattr(photon_bot, "ROSTER_FILE", path)
    return path


def test_inviting_a_roommate_assigns_a_line_and_saves_them(temp_roster):
    fake = FakePhoton()
    out = photon_bot.invite_roommate(bot(fake), "Sam", "424-555-0177", email="sam@example.com")
    assert out["line"] == "+16285550199" and out["email_invite"] is True
    assert out["text_link"].startswith("sms:+16285550199?&body=Hi%2C%20it%27s%20Sam")
    post = next(r for r in fake.requests if r.method == "POST")
    assert json.loads(post.content) == {"handle": "+14245550177", "firstName": "Sam", "email": "sam@example.com"}
    assert post.headers["idempotency-key"] == "silh-assign:14245550177"
    saved = json.loads(temp_roster.read_text())["roommates"]
    sam = next(e for e in saved if e["name"] == "Sam")
    assert sam["phone"] == "+14245550177" and sam["weights"]["commute"] == 5  # Kept Sam's priorities.


def test_inviting_someone_already_on_the_line_reuses_their_number(temp_roster):
    fake = FakePhoton(assignments=[{"handle": "+14245550188", "assignedPhoneNumber": "+16285550111"}])
    out = photon_bot.invite_roommate(bot(fake), "Tu", "+1 424 555 0188", budget=1600)
    assert out["line"] == "+16285550111"
    tu = json.loads(temp_roster.read_text())["roommates"][-1]
    assert tu["name"] == "Tu" and tu["budget"] == 1600


def test_new_roommate_from_the_website_is_known_without_a_restart(temp_roster):
    state = fresh_state()
    photon_bot.invite_roommate(bot(FakePhoton()), "Tu", "4245550188")
    fake = FakePhoton([incoming("pho_msg_7", "hello", handle="+14245550188")])
    photon_bot.process(bot(fake), state, photon_bot.load_roster(), LISTINGS, log=lambda *_: None)
    assert fake.sent[0][1]["content"]["text"].startswith("Hi Tu! I'm the apartment bot for Freddy, Sam & Tu.")


def test_roster_status_never_shows_full_numbers(temp_roster):
    photon_bot.invite_roommate(bot(FakePhoton()), "Tu", "4245550188")
    status = photon_bot.roster_status()
    tu = next(r for r in status if r["name"] == "Tu")
    assert tu["phone_last4"] == "0188" and tu["connected"] is False and tu["text_link"]
    assert "4245550188" not in json.dumps(status)
