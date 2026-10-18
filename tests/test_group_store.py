"""The shared group (page + bot) and its API. Nothing calls the internet: wishes use the short
"laundry 5" style, which plain code reads."""
import json
import threading

import pytest
from fastapi.testclient import TestClient

from app import cache, group_store, photon_bot
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(group_store, "GROUP_FILE", tmp_path / "group.local.json")
    monkeypatch.setattr(group_store, "OLD_ROSTER", tmp_path / "old_roster.json")
    monkeypatch.setattr(group_store, "OLD_STATE", tmp_path / "old_state.json")
    monkeypatch.setattr(photon_bot, "STATE_FILE", tmp_path / "bot" / "state.json")


def test_every_change_bumps_the_version():
    v0 = group_store.read().version
    with group_store.editing() as g:
        g.place = "Santa Monica Pier"
    g = group_store.read()
    assert g.version == v0 + 1 and g.place == "Santa Monica Pier"


def test_changes_from_two_programs_at_once_are_both_kept():
    def add(name):
        with group_store.editing() as g:
            g.people.append(group_store.Person(name=name, roommate=group_store.starting_roommate(name)))
    threads = [threading.Thread(target=add, args=(f"P{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(p.name for p in group_store.read().people) == [f"P{i}" for i in range(8)]


def test_older_roster_and_texted_wishes_carry_over(tmp_path):
    group_store.OLD_ROSTER.write_text(json.dumps({"roommates": [
        {"name": "Freddy", "phone": "+14245550100", "line": "+16285550199", "budget": 1500},
        {"name": "Sam", "phone": None, "budget": 1900}]}))
    group_store.OLD_STATE.write_text(json.dumps({"connected": ["Freddy"], "roommates": {
        "Freddy": {"name": "Freddy", "budget": 1500, "wants": [{"kind": "near", "what": "gym", "weight": 4}]}}}))
    g = group_store.read()
    freddy = g.find("freddy")
    assert freddy.me and freddy.connected and freddy.roommate.wants[0].what == "gym"
    assert g.find("Sam").roommate.budget == 1900 and g.size == 2


def test_listings_default_to_the_demo_set():
    assert len(group_store.read().current_listings()) == 12


# ---------- API ----------

def test_welcome_sets_up_me_with_my_words():
    r = client.post("/api/group/me", json={"name": "Freddy", "text": "laundry 5, rent 4", "place": "UCLA", "size": 3})
    assert r.status_code == 200
    me = r.json()["group"]["people"][0]
    assert me["me"] and me["name"] == "Freddy" and me["last_text"] == "laundry 5, rent 4"
    assert me["roommate"]["weights"]["laundry"] == 5
    assert r.json()["understood"]["weights"] == {"laundry": 5, "rent": 4}
    again = client.post("/api/group/me", json={"name": "Fred"}).json()["group"]  # Same "me", renamed.
    assert [p["name"] for p in again["people"]] == ["Fred"]


def test_add_someone_without_a_phone_then_add_their_wishes():
    client.post("/api/group/me", json={"name": "Freddy"})
    assert client.post("/api/group/people", json={"name": "Jordan", "budget": 1700}).status_code == 200
    assert client.post("/api/group/people", json={"name": "jordan"}).status_code == 409
    r = client.post("/api/group/people/Jordan/wishes", json={"text": "laundry 5"})
    jordan = next(p for p in r.json()["group"]["people"] if p["name"] == "Jordan")
    assert jordan["roommate"]["weights"]["laundry"] == 5 and jordan["roommate"]["budget"] == 1700
    assert client.post("/api/group/people/Nobody/wishes", json={"text": "laundry 5"}).status_code == 404


def test_edit_and_remove_a_person():
    client.post("/api/group/people", json={"name": "Sam"})
    r = client.patch("/api/group/people/Sam", json={"budget": 1900, "place": "Santa Monica Pier", "travel_mode": "BICYCLE"})
    sam = r.json()["people"][0]["roommate"]
    assert (sam["budget"], sam["place"], sam["travel_mode"]) == (1900, "Santa Monica Pier", "BICYCLE")
    assert client.delete("/api/group/people/Sam").json()["people"] == []


def test_demo_group_and_decide_from_the_shared_group():
    view = client.post("/api/group/demo").json()
    assert [p["name"] for p in view["people"]] == ["Alex", "Sam", "Jordan"]
    assert all(p["last_text"] for p in view["people"])  # Each has a sentence that explains their priorities.
    d = client.post("/api/group/decide").json()
    assert d["pick"]["title"] and len(d["ranking"]) == 12  # Demo listings, saved walk times: no network.


def test_saved_listings_are_what_the_bot_picks_from():
    client.post("/api/group/demo")
    listing = {"id": "x", "title": "Only Place", "rent_total_monthly": 3000, "bedrooms": 3, "walk_minutes": 10}
    assert client.put("/api/group/listings", json={"listings": [listing]}).json() == {"saved": 1}
    assert client.post("/api/group/decide").json()["pick"]["title"] == "Only Place"
    assert "Only Place" in photon_bot.current_pick("Alex")


def test_decide_needs_someone_and_reset_clears_the_group():
    client.post("/api/group/demo")
    assert client.post("/api/group/reset").json()["people"] == []
    assert client.post("/api/group/decide").status_code == 400
