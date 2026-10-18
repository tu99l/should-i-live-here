"""iMessage bot and the shared group. Photon is a fake server (httpx.MockTransport): nothing is really sent.

Texts here use the short "laundry 5" style, read by plain code, and listings with no wishes to look
up, so no Gemini or Google calls happen either.
"""
import json

import httpx
import pytest

from app import cache, group_store, photon_bot
from app.models import Listing, Roommate, Weights

LISTINGS = [
    Listing(id="cheap", title="Cheap Place", rent_total_monthly=2400, bedrooms=2, walk_minutes=15,
            laundry="shared", parking="paid"),
    Listing(id="washer", title="Washer Place", rent_total_monthly=3000, bedrooms=2, walk_minutes=15,
            laundry="in_unit", parking="paid"),
]


def person(name, phone=None, me=False, connected=True, **weights):
    w = Weights(**{**dict(rent=3, commute=3, laundry=3, parking=3, bedrooms=3), **weights})
    return group_store.Person(name=name, me=me, phone=phone, connected=connected,
                              roommate=Roommate(name=name, budget=1500 if name == "Freddy" else 1900, weights=w))


@pytest.fixture(autouse=True)
def temp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(photon_bot, "STATE_FILE", tmp_path / "bot" / "state.json")
    monkeypatch.setattr(group_store, "GROUP_FILE", tmp_path / "group.local.json")
    monkeypatch.setattr(group_store, "OLD_ROSTER", tmp_path / "missing.json")
    with group_store.editing() as g:
        g.people = [person("Freddy", "+14245550100", me=True, rent=5, laundry=0),
                    person("Sam", rent=2, commute=5, parking=4)]
        g.listings, g.size = LISTINGS, 2


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


def fresh_state():
    return {"answered": [], "since": "2026-10-18T00:00:00Z"}


def quiet(*_):
    pass


# ---------- Texts change the shared group ----------

def test_a_text_saves_wishes_in_the_shared_group_and_replies_with_the_pick():
    reply = photon_bot.handle_text("Freddy", "laundry 5, rent 0")
    freddy = group_store.read().find("Freddy")
    assert freddy.roommate.weights.laundry == 5 and freddy.roommate.weights.rent == 0
    assert freddy.last_text == "laundry 5, rent 0"
    assert reply.startswith("Got it, Freddy: rent: don't care; laundry: must-have.")
    assert "Fairest pick for Freddy & Sam: Washer Place, $1,500 each." in reply  # The group's own listings.


def test_reset_and_pick_commands():
    photon_bot.handle_text("Freddy", "laundry 5")
    reply = photon_bot.handle_text("Freddy", "reset")
    assert group_store.read().find("Freddy").roommate.weights.laundry == 3 and reply.startswith("Cleared")
    assert photon_bot.handle_text("Freddy", "Pick?").startswith("Fairest pick")


def test_each_text_is_answered_once_with_an_idempotency_key():
    fake = FakePhoton([incoming("pho_msg_1", "laundry 5")])
    photon, state = bot(fake), fresh_state()
    assert photon_bot.process(photon, state, log=quiet) == 1
    assert photon_bot.process(photon, state, log=quiet) == 0  # Not again.
    key, body = fake.sent[0]
    assert key == "silh-reply:pho_msg_1"
    assert body["spaceId"] == "pho_spc_1" and body["senderId"] == "pho_usr_agent"
    assert all(r.headers["authorization"] == "Bearer fake-key" for r in fake.requests)


def test_answered_texts_survive_a_restart():
    fake = FakePhoton([incoming("pho_msg_1", "laundry 5")])
    photon_bot.process(bot(fake), fresh_state(), log=quiet)
    assert photon_bot.process(bot(fake), photon_bot.load_state(), log=quiet) == 0


def test_unknown_number_gets_a_polite_reply_and_no_changes():
    fake = FakePhoton([incoming("pho_msg_2", "laundry 5", handle="+19995550123")])
    photon_bot.process(bot(fake), fresh_state(), log=quiet)
    assert "don't know this number" in fake.sent[0][1]["content"]["text"]
    assert group_store.read().find("Freddy").roommate.weights.laundry == 0


def test_phone_numbers_match_whatever_the_formatting():
    fake = FakePhoton([incoming("pho_msg_3", "help", handle="+1 (424) 555-0100")])
    photon_bot.process(bot(fake), fresh_state(), log=quiet)
    assert fake.sent[0][1]["content"]["text"].startswith("Hi Freddy!")


def test_a_crash_while_looking_up_still_gets_a_reply(monkeypatch):
    def boom(*_):
        raise RuntimeError("Google is down")
    monkeypatch.setattr(photon_bot, "run_decision", boom)
    fake = FakePhoton([incoming("pho_msg_4", "laundry 5")])
    photon_bot.process(bot(fake), fresh_state(), log=quiet)
    assert fake.sent[0][1]["content"]["text"].startswith("Sorry, something went wrong")


def test_first_text_gets_a_greeting_and_marks_them_texting():
    with group_store.editing() as g:
        g.find("Freddy").connected = False
    fake = FakePhoton([incoming("pho_msg_5", "Hi, it's Freddy! Let's find our apartment."),
                       incoming("pho_msg_6", "laundry 5", created="2026-10-18T02:01:00Z")])
    photon_bot.process(bot(fake), fresh_state(), log=quiet)
    assert fake.sent[0][1]["content"]["text"].startswith("Hi Freddy! I'm the apartment bot for Freddy & Sam.")
    assert fake.sent[1][1]["content"]["text"].startswith("Got it, Freddy")  # Second text: not greeted again.
    assert group_store.read().find("Freddy").connected is True


def test_group_place_is_everyones_commute_unless_they_set_their_own():
    rs = [Roommate(name="A", budget=1), Roommate(name="B", budget=1, place="Santa Monica Pier")]
    out = photon_bot.with_group_place(rs, "Downtown LA")
    assert [r.place for r in out] == ["Downtown LA", "Santa Monica Pier"]
    assert photon_bot.with_group_place(rs, "UCLA") == rs  # UCLA = the default campus, nothing to fill in.


# ---------- Inviting from the page ----------

def test_phone_numbers_are_normalized_or_rejected():
    assert photon_bot.normalize_phone("(424) 555-0100") == "+14245550100"
    assert photon_bot.normalize_phone("+44 20 7946 0958") == "+442079460958"
    for bad in ("12345", "call me", ""):
        with pytest.raises(ValueError):
            photon_bot.normalize_phone(bad)


def test_inviting_adds_a_person_with_a_line_and_keeps_existing_wishes():
    fake = FakePhoton()
    out = photon_bot.invite_roommate(bot(fake), "Sam", "424-555-0177", email="sam@example.com")
    assert out["line"] == "+16285550199" and out["email_invite"] is True
    assert out["text_link"].startswith("sms:+16285550199?&body=Hi%2C%20it%27s%20Sam")
    post = next(r for r in fake.requests if r.method == "POST")
    assert json.loads(post.content) == {"handle": "+14245550177", "firstName": "Sam", "email": "sam@example.com"}
    assert post.headers["idempotency-key"] == "silh-assign:14245550177"
    sam = group_store.read().find("Sam")
    assert sam.phone == "+14245550177" and sam.roommate.weights.commute == 5  # Kept Sam's priorities.


def test_inviting_someone_already_on_the_line_reuses_their_number():
    fake = FakePhoton(assignments=[{"handle": "+14245550188", "assignedPhoneNumber": "+16285550111"}])
    out = photon_bot.invite_roommate(bot(fake), "Tu", "+1 424 555 0188", budget=1600)
    assert out["line"] == "+16285550111"
    tu = group_store.read().find("Tu")
    assert tu.roommate.budget == 1600 and tu.connected is False


def test_new_person_from_the_page_is_known_to_the_bot_right_away():
    photon_bot.invite_roommate(bot(FakePhoton()), "Tu", "4245550188")
    fake = FakePhoton([incoming("pho_msg_7", "hello", handle="+14245550188")])
    photon_bot.process(bot(fake), fresh_state(), log=quiet)
    assert fake.sent[0][1]["content"]["text"].startswith("Hi Tu! I'm the apartment bot for Freddy, Sam & Tu.")


def test_the_page_never_gets_full_phone_numbers():
    photon_bot.invite_roommate(bot(FakePhoton()), "Tu", "4245550188")
    view = group_store.public_view(group_store.read(), photon_bot.text_link)
    tu = next(p for p in view["people"] if p["name"] == "Tu")
    assert tu["phone_last4"] == "0188" and tu["connected"] is False and tu["text_link"]
    assert "4245550188" not in json.dumps(view)


def test_the_example_roster_has_no_real_numbers():
    roster = json.loads((photon_bot.ROOT / "data" / "roommates.example.json").read_text())
    assert all(r["phone"] is None or r["phone"].startswith("+1555555") for r in roster["roommates"])
