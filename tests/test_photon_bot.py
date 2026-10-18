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
    """Answers list and send like Photon's API, and records every request."""

    def __init__(self, messages):
        self.messages, self.sent, self.requests = messages, [], []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"items": self.messages})
        body = json.loads(request.content)
        if body["content"]["type"] == "text":
            self.sent.append((request.headers.get("idempotency-key"), body))
        return httpx.Response(202, json={"id": "pho_msg_out"})


def bot(fake):
    http = httpx.Client(base_url=photon_bot.API, transport=httpx.MockTransport(fake))
    return photon_bot.Photon("fake-key", "pho_prj_test", http=http)


def fresh_state():
    state = photon_bot.load_state(ROSTER)
    state["since"] = "2026-10-18T00:00:00Z"
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
