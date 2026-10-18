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
    told = photon_bot.tell_group(photon(fake), "Alex", {"title": "1824 Fairburn Ave"}, log=lambda *_: None)
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
