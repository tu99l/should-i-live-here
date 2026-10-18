"""The view-only results link: what the outside can reach, the secret code, and pick-change texts."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import cache, group_store, photon_bot, share
from app.main import app

client = TestClient(app)
OUTSIDE = {"host": "abc-def.trycloudflare.com", "cf-connecting-ip": "203.0.113.9"}


@pytest.fixture(autouse=True)
def temp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(group_store, "GROUP_FILE", tmp_path / "group.local.json")
    monkeypatch.setattr(group_store, "OLD_ROSTER", tmp_path / "none.json")
    monkeypatch.setattr(share, "SHARE_FILE", tmp_path / "share.local.json")
    monkeypatch.setattr(photon_bot, "STATE_FILE", tmp_path / "bot" / "state.json")
    with group_store.editing() as g:
        g.people = group_store.demo_people()
        g.people[0].phone, g.people[0].line = "+14245550100", "+16285550199"


def test_outside_requests_only_reach_the_share_page():
    code = share.code()
    assert client.get(f"/share/{code}", headers=OUTSIDE).status_code == 200
    assert client.get(f"/api/share/{code}", headers=OUTSIDE).status_code == 200
    assert client.get("/static/share.js", headers=OUTSIDE).status_code == 200
    for method, path in [("GET", "/"), ("GET", "/api/group"), ("GET", "/api/demo"), ("GET", "/static/app.js"),
                         ("POST", "/api/search"), ("POST", "/api/group/demo"), ("POST", "/api/roommates/invite"),
                         ("PUT", "/api/group/listings"), ("POST", "/api/decide"), ("GET", "/api/share")]:
        assert client.request(method, path, headers=OUTSIDE).status_code == 404, path
    assert client.get("/api/group").status_code == 200  # This laptop still has everything.


def test_wrong_code_gets_nothing():
    assert client.get("/share/guessing", headers=OUTSIDE).status_code == 404
    assert client.get("/api/share/guessing").status_code == 404


def test_shared_data_has_the_pick_but_no_phone_numbers():
    data = client.get(f"/api/share/{share.code()}").json()
    assert [p["name"] for p in data["people"]] == ["Alex", "Sam", "Jordan"]
    assert data["decision"]["pick"]["title"] and len(data["listings"]) == 12
    text = json.dumps(data)
    assert "4245550100" not in text and "0100" not in text and "6285550199" not in text


def test_the_code_is_kept_and_the_link_needs_a_running_tunnel():
    first = share.code()
    assert share.code() == first  # Links already texted keep working.
    assert share.link() is None
    share.set_public_url("https://abc-def.trycloudflare.com/")
    assert share.link() == f"https://abc-def.trycloudflare.com/share/{first}"
    share.set_public_url(None)
    assert share.link() is None


# ---------- The bot tells the others when the pick changes ----------

class FakePhoton:
    def __init__(self):
        self.sent = []

    def __call__(self, request):
        if request.method == "POST":
            body = json.loads(request.content)
            if body["content"]["type"] == "text":
                self.sent.append((body["spaceId"], body["content"]["text"], request.headers["idempotency-key"]))
        return httpx.Response(202, json={})


def photon(fake):
    return photon_bot.Photon("k", "p", http=httpx.Client(base_url=photon_bot.API, transport=httpx.MockTransport(fake)))


def test_pick_change_texts_everyone_else_who_has_texted_with_the_link():
    with group_store.editing() as g:
        for p, space in zip(g.people, ("s-alex", "s-sam", None)):
            p.space_id, p.agent_id = space, ("agent" if space else None)
    share.set_public_url("https://abc-def.trycloudflare.com")
    fake = FakePhoton()
    told = photon_bot.tell_group(photon(fake), "Alex", {"title": "1824 Fairburn Ave", "listing_id": "fairburn"}, log=lambda *_: None)
    assert told == 1  # Sam only: Alex made the change, Jordan never texted.
    space, text, key = fake.sent[0]
    assert space == "s-sam" and "Alex changed what they want" in text and "1824 Fairburn Ave" in text
    assert f"/share/{share.code()}" in text and key.startswith("silh-pick:")


def test_first_pick_is_remembered_quietly_then_changes_are_announced():
    photon_bot._pick_seen["Alex"] = {"listing_id": "a", "title": "A"}
    assert photon_bot.changed_pick("Alex") is None  # First pick: nothing "changed".
    photon_bot._pick_seen["Alex"] = {"listing_id": "a", "title": "A"}
    assert photon_bot.changed_pick("Alex") is None  # Same pick.
    photon_bot._pick_seen["Sam"] = {"listing_id": "b", "title": "B"}
    assert photon_bot.changed_pick("Sam")["title"] == "B"
    assert group_store.read().last_pick == "b"


def test_pick_reply_includes_the_link_when_sharing():
    share.set_public_url("https://abc-def.trycloudflare.com")
    assert f"See the map and everyone's scores: https://abc-def.trycloudflare.com/share/{share.code()}" in photon_bot.current_pick("Alex")


# ---------- From stress testing: no update spam, retried replies, photos ----------

def test_rapid_changes_send_one_update_then_the_newest_pick_later(monkeypatch):
    with group_store.editing() as g:
        for p, space in zip(g.people, ("s-alex", "s-sam", None)):
            p.space_id, p.agent_id = space, ("agent" if space else None)
    clock = [1000.0]
    monkeypatch.setattr(photon_bot, "_now", lambda: clock[0])
    fake, state = FakePhoton(), photon_bot.load_state()
    quiet = lambda *_: None
    photon_bot.tell_group(photon(fake), "Alex", {"title": "A", "listing_id": "a"}, quiet, state)
    for i, pick in enumerate(["B", "C", "D"]):  # Three more changes within a minute.
        clock[0] += 10
        photon_bot.tell_group(photon(fake), "Alex", {"title": pick, "listing_id": pick.lower()}, quiet, state)
    assert [t for _, t, _ in fake.sent] == [fake.sent[0][1]] and "now A" in fake.sent[0][1]  # Only the first went out.
    clock[0] += photon_bot.UPDATE_GAP
    photon_bot.flush_updates(photon(fake), state, quiet)
    assert len(fake.sent) == 2 and "now D" in fake.sent[1][1]  # Then one text with the newest pick.


def test_a_failed_reply_is_retried_with_the_same_key():
    from tests.test_photon_bot import incoming
    attempts = []

    def flaky(request):
        if request.method == "GET":
            return httpx.Response(200, json={"items": [incoming("m1", "laundry 5")]})
        body = json.loads(request.content)
        if body["content"]["type"] == "text":
            attempts.append(request.headers["idempotency-key"])
            if len(attempts) <= 2:  # The sender's own two tries both fail.
                return httpx.Response(500, json={})
        return httpx.Response(202, json={})
    with group_store.editing() as g:
        g.people[0].phone, g.people[0].connected = "+14245550100", True
    state = {"answered": [], "since": "2026-10-18T00:00:00Z"}
    bot = photon(flaky)
    photon_bot.process(bot, state, log=lambda *_: None)  # Photon fails: no crash, reply kept.
    assert len(state["unsent"]) == 1
    photon_bot.process(bot, state, log=lambda *_: None)  # Next check: retried and delivered.
    assert state["unsent"] == [] and set(attempts) == {"silh-reply:m1"} and len(attempts) == 3


def test_a_photo_gets_a_polite_text_only_reply():
    from tests.test_photon_bot import incoming
    with group_store.editing() as g:
        g.people[0].phone, g.people[0].connected = "+14245550100", True
    photo = {**incoming("m2", "x"), "content": {"type": "attachment", "attachmentId": "pho_att_x"}}
    fake = FakePhoton()

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"items": [photo]})
        return fake(request)
    photon_bot.process(photon(handler), {"answered": [], "since": "2026-10-18T00:00:00Z"}, log=lambda *_: None)
    assert fake.sent and fake.sent[0][1].startswith("I can only read text for now")
