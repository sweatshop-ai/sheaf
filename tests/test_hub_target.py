"""The target of a Tell is a session or an agent, and the person can change it (SPEC 9.8, 10.1, 10.6).

An agent target is kept with the token's stable `id`, so a revoked token, or a new one of the same name,
is never the old target. A door write with an agent's token makes that agent the target; a door read
changes nothing. In proxy mode each member has a target of their own, never the hub person's."""
import os
import pwd
import threading

import pytest

import sheafmd.comments as rdc
from helpers import BEA, CAL, FRONT, call, comment, hub_rows, ok, page_meta, refused
from sheafmd.hub import proxy
from sheafmd.hub.state import Tokens

DOC = "work/plan.md"
URL = "/work/plan.md"
SESSION = {"agent": "claude-code", "session": "s-1", "name": "Cosima"}
REVOKED = "{agent} can no longer reach this hub: its token was revoked. Pick another target."


@pytest.fixture
def talk(plan):
    comment(plan)
    return plan


def render(browser, plan, target=SESSION):
    r = browser.post("/_/render", {"path": str(plan), "settings": {}, "target": target}, key=True, cookie=False)
    assert r.status == 200, r.text


def stored(browser):
    return browser.hub.docs.get(DOC)


def agent(name, id_):
    return {"kind": "agent", "token": name, "id": id_}


def members(work, other=None, bea=(), cal=()):
    table = {BEA: {"name": "Bea", "roots": [str(work)], "tokens": list(bea)}}
    if other is not None:
        table[CAL] = {"name": "Cal", "roots": [str(other)], "tokens": list(cal)}
    return proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                        "proxy_user": pwd.getpwuid(os.getuid()).pw_name, "members": table}, "the test")


def row(name):
    return next(r for r in Tokens().list() if r.name == name)


def pick(client, target, doc=DOC):
    return client.post("/_/target", {"doc": doc, "target": target})


# ── a door write makes the agent the target, a door read changes nothing ─────

def test_a_reply_with_an_agents_token_makes_that_agent_the_target_and_keeps_the_session(browser, talk):
    token = Tokens().add("ada-chatgpt", client="ChatGPT")
    render(browser, talk)
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=token)
    assert stored(browser)["target"] == agent("ada-chatgpt", row("ada-chatgpt").id)
    assert stored(browser)["session"]["session"] == "s-1"


@pytest.mark.parametrize("tool,args", [("reply", {"id": "c1", "text": "Done."}), ("resolve", {"id": "c1"})])
def test_reply_and_resolve_are_door_writes(browser, talk, tool, args):
    token = Tokens().add("ada-chatgpt", client="ChatGPT")
    ok(browser, tool, doc=DOC, token=token, **args)
    assert stored(browser)["target"]["token"] == "ada-chatgpt"


def test_create_and_update_are_door_writes(browser, talk):
    token = Tokens().add("ada-chatgpt", client="ChatGPT", write=True)
    made = ok(browser, "create", doc="work/new.md", text="# New\n\nText.\n", token=token)
    assert browser.hub.docs.get("work/new.md")["target"]["token"] == "ada-chatgpt"
    other = Tokens().add("ada-claude", client="Claude", write=True)
    ok(browser, "update", doc="work/new.md", text="# New\n\nMore.\n", expected_hash=made["hash"], token=other)
    assert browser.hub.docs.get("work/new.md")["target"]["token"] == "ada-claude"


def tabs_hear(browser, doc=DOC):
    """[(event, the document's stored target when the tabs were told)] of `doc`: what a tab that fetches /_/doc the
    moment it hears reads (ticket 12, row 18)."""
    live = browser.hub.entry(doc).live
    heard, real = [], live._publish

    def publish(name, data):
        heard.append((name, browser.hub.docs.get(doc).get("target")))
        real(name, data)
    live._publish = publish
    return heard


@pytest.mark.parametrize("tool,args", [("reply", {"id": "c1", "text": "Done."}), ("resolve", {"id": "c1"})])
def test_the_tabs_hear_of_a_comment_write_after_its_agent_is_the_target(browser, talk, tool, args):
    token = Tokens().add("ada-chatgpt", client="ChatGPT")
    render(browser, talk)
    heard = tabs_hear(browser)
    ok(browser, tool, doc=DOC, token=token, **args)
    told = [target for name, target in heard if name == "changed"]
    assert told and all(t == agent("ada-chatgpt", row("ada-chatgpt").id) for t in told)


def test_the_tabs_hear_of_an_update_after_its_agent_is_the_target(browser, talk):
    token = Tokens().add("ada-chatgpt", client="ChatGPT", write=True)
    render(browser, talk)
    heard = tabs_hear(browser)
    ok(browser, "update", doc=DOC, text=talk.read_text() + "\nMore.\n", token=token,
       expected_hash=ok(browser, "read", doc=DOC, token=token)["hash"])
    told = [target for name, target in heard if name == "changed"]
    assert told and all(t == agent("ada-chatgpt", row("ada-chatgpt").id) for t in told)


def test_a_reply_that_the_target_cannot_follow_still_stands(browser, talk, monkeypatch):
    token = Tokens().add("ada-chatgpt", client="ChatGPT")
    render(browser, talk)

    def boom(*a, **k):
        raise RuntimeError("docs.json is gone")
    monkeypatch.setattr("sheafmd.hub.targets.note_write", boom)
    heard = tabs_hear(browser)
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=token)
    assert "Done." in talk.read_text() and [n for n, _ in heard].count("changed") == 1
    assert [r["kind"] for r in hub_rows("target-failed")] == ["target-failed"]


def test_documents_threads_and_read_change_nothing(browser, talk):
    token = Tokens().add("ada-chatgpt", client="ChatGPT", write=True)
    render(browser, talk)
    before = stored(browser)
    ok(browser, "documents", token=token)
    ok(browser, "threads", doc=DOC, token=token)
    ok(browser, "read", doc=DOC, token=token)
    assert stored(browser) == before


def test_a_read_of_a_page_with_no_entry_leaves_none(browser, talk):
    token = Tokens().add("ada-chatgpt", client="ChatGPT", write=True)
    ok(browser, "read", doc=DOC, token=token)
    assert stored(browser).get("target") is None and "targets" not in stored(browser)


def test_a_write_that_is_refused_changes_nothing(browser, talk):
    token = Tokens().add("ada-chatgpt", client="ChatGPT")
    refused(browser, "reply", doc=DOC, id="c9", text="Done.", token=token)
    assert stored(browser).get("target") is None


def test_a_token_that_is_no_agents_makes_no_target(browser, talk):
    token = Tokens().add("codex", "Codex")
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=token)
    assert stored(browser).get("target") is None


def test_a_session_target_is_stored_with_its_kind(browser, talk):
    render(browser, talk)
    assert stored(browser)["target"]["kind"] == "session"


def test_a_render_from_a_session_takes_the_target_back_from_an_agent(browser, talk):
    token = Tokens().add("ada-chatgpt", client="ChatGPT")
    render(browser, talk)
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=token)
    render(browser, talk, dict(SESSION, session="s-2"))
    assert stored(browser)["target"]["session"] == "s-2" and "session" not in stored(browser)


def test_a_render_with_no_agent_keeps_an_agent_target_and_none_clears_everything(browser, talk):
    token = Tokens().add("ada-chatgpt", client="ChatGPT")
    render(browser, talk)
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=token)
    render(browser, talk, None)
    assert stored(browser)["target"]["token"] == "ada-chatgpt"
    render(browser, talk, {"agent": "none"})
    assert stored(browser)["target"] is None and "session" not in stored(browser)


def test_a_render_while_a_tell_runs_keeps_the_session_it_was_sent_to_beside_the_new_target(browser, talk):
    release = threading.Event()
    render(browser, talk)
    browser.hub.runner.start("tell", DOC, "c1", lambda job: release.wait(10))
    try:
        render(browser, talk, {"agent": "none"})
        assert stored(browser)["target"] is None and stored(browser)["session"]["session"] == "s-1"
        assert browser.hub.target(DOC) is None and browser.hub.target(DOC, kept=True).session == "s-1"
        render(browser, talk, dict(SESSION, session="s-2"))
        assert stored(browser)["target"]["session"] == "s-2" and stored(browser)["session"]["session"] == "s-1"
        assert browser.hub.target(DOC).session == "s-2" and browser.hub.target(DOC, kept=True).session == "s-1"
    finally:
        release.set()
        browser.hub.runner.join(10)


def test_a_render_while_a_tell_runs_leaves_a_session_beside_an_agent_alone(browser, talk):
    release = threading.Event()
    token = Tokens().add("ada-chatgpt", client="ChatGPT")
    render(browser, talk)
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=token)
    browser.hub.runner.start("tell", DOC, "c1", lambda job: release.wait(10))
    try:
        render(browser, talk, {"agent": "none"})
        assert stored(browser)["target"] is None and stored(browser)["session"]["session"] == "s-1"
    finally:
        release.set()
        browser.hub.runner.join(10)


def test_a_door_write_while_a_tell_runs_leaves_the_session_kept_for_it(browser, talk):
    release = threading.Event()
    token = Tokens().add("ada-chatgpt", client="ChatGPT")
    render(browser, talk)
    browser.hub.runner.start("tell", DOC, "c1", lambda job: release.wait(10))
    try:
        render(browser, talk, dict(SESSION, session="s-2"))
        ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=token)
        assert stored(browser)["target"]["kind"] == "agent" and stored(browser)["session"]["session"] == "s-1"
    finally:
        release.set()
        browser.hub.runner.join(10)


def test_a_tell_is_live_while_its_cancel_is_under_way_and_is_asked_without_the_documents_lock(browser, talk):
    release = threading.Event()
    render(browser, talk)
    hub = browser.hub
    assert not hub.tell_live(DOC)
    hub.runner.start("stop", DOC, "c1", lambda job: release.wait(10))
    try:
        with hub.entry(DOC).live._held():        # a rebuild holds it while it reads the docs: no wait here
            assert hub.tell_live(DOC)
    finally:
        release.set()
        hub.runner.join(10)


def test_the_kept_session_stays_when_a_render_moved_the_target_off_the_session_a_tell_starts_for(browser, talk):
    release = threading.Event()
    render(browser, talk)
    told = browser.hub.target(DOC)                                  # the session the Tell was looked up for
    browser.hub.runner.start("tell", DOC, "c9", lambda job: release.wait(10))
    try:
        render(browser, talk, dict(SESSION, session="s-2"))
        assert stored(browser)["session"]["session"] == "s-1"
    finally:
        release.set()
        browser.hub.runner.join(10)
    browser.hub.drop_kept(DOC, "c1", told)                          # the Tell of c1 begins, a render came between
    assert stored(browser)["session"]["session"] == "s-1"
    browser.hub.drop_kept(DOC, "c1", browser.hub.target(DOC))       # one that goes to the target drops it
    assert "session" not in stored(browser)


def test_a_render_that_beat_the_tell_to_its_wait_still_leaves_the_session_the_tell_goes_to(browser, talk):
    render(browser, talk)
    told = browser.hub.target(DOC)                                  # the Tell looked the target up: s-1
    render(browser, talk, dict(SESSION, session="s-2"))             # no Tell was live yet, so nothing was kept
    assert "session" not in stored(browser)
    browser.hub.drop_kept(DOC, "c1", told)                          # the Tell begins its wait and goes to s-1
    assert stored(browser)["target"]["session"] == "s-2" and stored(browser)["session"]["session"] == "s-1"
    assert browser.hub.target(DOC, kept=True).session == "s-1"


def test_a_tell_sent_again_while_the_first_still_waits_leaves_the_session_kept_for_it(browser, talk):
    release = threading.Event()
    render(browser, talk)
    browser.hub.runner.start("tell", DOC, "c1", lambda job: release.wait(10))
    try:
        render(browser, talk, dict(SESSION, session="s-2"))
        browser.hub.drop_kept(DOC, "c1", browser.hub.target(DOC), True)
        assert stored(browser)["session"]["session"] == "s-1"
    finally:
        release.set()
        browser.hub.runner.join(10)


def test_a_pick_while_a_tell_runs_does_not_replace_the_session_kept_for_it(browser, talk):
    release = threading.Event()
    token = Tokens().add("ada-chatgpt", client="ChatGPT")
    render(browser, talk)
    browser.hub.runner.start("tell", DOC, "c1", lambda job: release.wait(10))
    try:
        render(browser, talk, dict(SESSION, session="s-2"))
        assert pick(browser, "session").status == 200               # the target is that session already
        assert stored(browser)["session"]["session"] == "s-1"
        assert pick(browser, "agent:ada-chatgpt").status == 200
        assert stored(browser)["session"]["session"] == "s-1" and browser.hub.target(DOC, kept=True).session == "s-1"
    finally:
        release.set()
        browser.hub.runner.join(10)


# ── the id, not the name, is the agent ───────────────────────────────────────

def test_a_revoked_token_is_no_target_and_a_new_token_of_its_name_is_not_the_old_one(browser, talk):
    token = Tokens().add("ada-chatgpt", client="ChatGPT")
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=token)
    old = row("ada-chatgpt").id
    Tokens().revoke("ada-chatgpt")
    got = browser.get(f"/_/doc?doc={DOC}").json()
    assert got["target"]["token"] == "ada-chatgpt"
    assert got["lines"]["tell"] == REVOKED.format(agent="ada-chatgpt") and got["capabilities"] == []
    assert got["target"]["revoked"] is True                       # the page takes no token of this name for it
    Tokens().add("ada-chatgpt", client="ChatGPT")
    assert row("ada-chatgpt").id != old
    got = browser.get(f"/_/doc?doc={DOC}").json()
    assert got["lines"]["tell"] == REVOKED.format(agent="ada-chatgpt")        # the new token is not the target
    assert stored(browser)["target"]["id"] == old


def test_a_stop_still_finds_the_session_a_tell_was_sent_to_when_an_agent_is_the_target_now(browser, talk):
    render(browser, talk)
    token = Tokens().add("ada-chatgpt", client="ChatGPT")
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=token)
    assert stored(browser)["target"]["kind"] == "agent"
    assert browser.hub.target(DOC) is None and browser.hub.target(DOC, kept=True).session == "s-1"
    assert browser.hub.tell.view(DOC, session=True).target.session == "s-1"
    assert browser.hub.tell.view(DOC).target is None              # the page's view is the agent's
    assert pick(browser, "none").status == 200                    # none keeps the session for a running Tell too
    assert browser.hub.tell.view(DOC).target is None and browser.hub.tell.view(DOC).lines["tell"]
    assert browser.hub.tell.view(DOC, session=True).target.session == "s-1"


def test_the_wire_form_names_the_token_and_the_server_stores_its_id(browser, talk):
    Tokens().add("ada-chatgpt", client="ChatGPT")
    r = pick(browser, "agent:ada-chatgpt")
    assert r.status == 200, r.text
    assert stored(browser)["target"] == agent("ada-chatgpt", row("ada-chatgpt").id)


# ── POST /_/target ───────────────────────────────────────────────────────────

def test_the_person_picks_an_agent_a_session_or_none(browser, talk):
    Tokens().add("ada-chatgpt", client="ChatGPT")
    render(browser, talk)
    person = browser.hub.person
    got = pick(browser, "agent:ada-chatgpt").json()
    assert got["ok"] is True
    assert got["target"] == {"kind": "agent", "token": "ada-chatgpt",
                             "display": f"ChatGPT ({person})", "label": f"ChatGPT ({person})"}
    assert got["targets"] == [{"target": "session", "label": "Cosima · Claude Code"},
                              {"target": "agent:ada-chatgpt", "label": f"ChatGPT ({person})"}]
    back = pick(browser, "session").json()
    assert back["target"]["kind"] == "session" and back["target"]["name"] == "Cosima"
    assert stored(browser)["target"]["session"] == "s-1" and "session" not in stored(browser)
    gone = pick(browser, "none").json()
    assert gone["target"] is None and stored(browser)["target"] is None
    assert [t["target"] for t in gone["targets"]] == ["session", "agent:ada-chatgpt"]     # the session can be taken back


def test_a_picked_agent_can_be_told_and_the_page_shows_no_line_under_tell(browser, talk):
    Tokens().add("ada-chatgpt", client="ChatGPT")
    pick(browser, "agent:ada-chatgpt")
    meta = page_meta(browser.get(URL).text)
    assert meta["agent"]["kind"] == "agent" and meta["can"] == ["queue"]
    assert meta["lines"]["tell"] is None
    assert browser.post("/_/tell", {"doc": DOC, "id": "c1"}).status == 200


@pytest.mark.parametrize("target", ["", "everyone", "agent:", "agent:nobody", "Session",
                                    "agent:../x", 3, None, ["session"], {"target": "none"}, "agent:plain"])
def test_the_person_cannot_pick_what_is_not_there_or_not_an_agent(browser, talk, target):
    Tokens().add("ada-chatgpt", client="ChatGPT")
    Tokens().add("plain", "Codex")
    render(browser, talk, None)
    before = stored(browser)
    r = pick(browser, target)
    assert r.status == 400 and r.json()["ok"] is False
    assert stored(browser) == before


def test_a_session_cannot_be_picked_when_none_rendered_this_page(browser, talk):
    assert pick(browser, "session").status == 400


def test_the_target_route_needs_a_sign_in_and_a_known_document(browser, talk):
    assert browser.post("/_/target", {"doc": DOC, "target": "none"}, cookie=False).status in (401, 403)
    assert pick(browser, "none", doc="work/missing.md").status == 404


def test_doc_and_the_meta_block_carry_target_and_targets(browser, talk):
    Tokens().add("ada-chatgpt", client="ChatGPT")
    person = browser.hub.person
    render(browser, talk)
    want = [{"target": "session", "label": "Cosima · Claude Code"},
            {"target": "agent:ada-chatgpt", "label": f"ChatGPT ({person})"}]
    got = browser.get(f"/_/doc?doc={DOC}").json()
    assert got["target"]["kind"] == "session" and got["targets"] == want
    meta = page_meta(browser.get(URL).text)
    assert meta["agent"]["kind"] == "session" and meta["targets"] == want


# ── proxy mode: a target per member ──────────────────────────────────────────

def test_a_members_agent_write_takes_the_members_target_and_never_the_hub_persons(browser, talk, work):
    token = Tokens().add("bea-chatgpt", client="ChatGPT")
    browser.hub.proxy = members(work, bea=["bea-chatgpt"])
    render(browser, talk)
    before = stored(browser)["target"]
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=token)
    assert stored(browser)["target"] == before
    assert stored(browser)["targets"] == {BEA: agent("bea-chatgpt", row("bea-chatgpt").id)}


def test_an_agent_no_member_names_acts_for_the_hub_person(browser, talk, work):
    token = Tokens().add("stray", client="ChatGPT")
    browser.hub.proxy = members(work)
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=token)
    assert stored(browser)["target"]["token"] == "stray" and "targets" not in stored(browser)


def test_a_member_sees_their_own_target_and_the_hub_persons_session_stays_hidden(front, browser, talk, work):
    token = Tokens().add("bea-chatgpt", client="ChatGPT")
    Tokens().add("bea-claude", client="Claude")
    front.hub.proxy = members(work, bea=["bea-chatgpt", "bea-claude"])
    render(browser, talk)
    assert front.get(f"/_/doc?doc={DOC}").json()["target"] is None
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=token)
    got = front.get(f"/_/doc?doc={DOC}").json()
    assert got["target"] == {"kind": "agent", "token": "bea-chatgpt", "display": "ChatGPT (Bea)",
                             "label": "ChatGPT (Bea)"}
    assert got["targets"] == [{"target": "agent:bea-chatgpt", "label": "ChatGPT (Bea)"},
                              {"target": "agent:bea-claude", "label": "Claude (Bea)"}]
    assert "Cosima" not in str(got) and "s-1" not in str(got)


def test_a_member_picks_one_of_their_own_agents_and_clears_it(front, browser, talk, work):
    Tokens().add("bea-chatgpt", client="ChatGPT")
    front.hub.proxy = members(work, bea=["bea-chatgpt"])
    render(browser, talk)
    before = stored(browser)["target"]
    got = pick(front, "agent:bea-chatgpt").json()
    assert got["target"]["token"] == "bea-chatgpt"
    assert stored(browser)["targets"][BEA]["id"] == row("bea-chatgpt").id and stored(browser)["target"] == before
    assert pick(front, "none").json()["target"] is None
    assert BEA not in stored(browser).get("targets", {}) and stored(browser)["target"] == before


def test_a_member_cannot_pick_another_members_agent_nor_the_hub_accounts_session(front, browser, talk, work, other):
    Tokens().add("bea-chatgpt", client="ChatGPT")
    Tokens().add("cal-chatgpt", client="ChatGPT")
    Tokens().add("loose", client="Claude")
    Tokens().add("plain", "Codex")
    front.hub.proxy = members(work, other, bea=["bea-chatgpt", "plain"], cal=["cal-chatgpt"])
    render(browser, talk)
    before = stored(browser)
    for target in ("session", "agent:cal-chatgpt", "agent:loose", "agent:plain", "agent:nobody", "everyone"):
        r = pick(front, target)
        assert r.status == 400 and r.json()["ok"] is False, target
    assert stored(browser) == before


def test_a_member_cannot_pick_for_a_document_of_another_member(front, browser, work, other):
    Tokens().add("bea-chatgpt", client="ChatGPT")
    front.hub.proxy = members(work, other, bea=["bea-chatgpt"])
    (other / "theirs.md").write_text("# Theirs\n\nText.\n", encoding="utf-8")
    browser.hub.roots.for_document(other / "theirs.md")
    r = pick(front, "agent:bea-chatgpt", doc="other/theirs.md")
    assert r.status == 404 and browser.hub.docs.get("other/theirs.md").get("targets") is None


def test_a_member_whose_agent_is_no_longer_theirs_has_no_target(front, browser, talk, work):
    token = Tokens().add("bea-chatgpt", client="ChatGPT")
    front.hub.proxy = members(work, bea=["bea-chatgpt"])
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=token)
    front.hub.proxy = members(work, bea=[])                  # the config moved the token off Bea
    got = front.get(f"/_/doc?doc={DOC}").json()
    assert got["target"] is None and got["targets"] == []


def test_a_members_revoked_agent_shows_the_line_of_a_revoked_token(front, browser, talk, work):
    token = Tokens().add("bea-chatgpt", client="ChatGPT")
    front.hub.proxy = members(work, bea=["bea-chatgpt"])
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=token)
    Tokens().revoke("bea-chatgpt")
    got = front.get(f"/_/doc?doc={DOC}").json()
    assert got["lines"]["tell"] == REVOKED.format(agent="bea-chatgpt") and got["capabilities"] == []


def test_each_member_has_their_own_target_on_the_same_document(front, browser, talk, work, other):
    a = Tokens().add("bea-chatgpt", client="ChatGPT")
    b = Tokens().add("cal-claude", client="Claude")
    front.hub.proxy = members(work, other, bea=["bea-chatgpt"], cal=["cal-claude"])
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", token=a)
    assert front.get(f"/_/doc?doc={DOC}").json()["target"]["token"] == "bea-chatgpt"
    assert stored(browser)["targets"].keys() == {BEA}
    assert call(browser, "reply", doc=DOC, id="c1", text="Done.", token=b)[0] is True     # Cal has no right to Bea's page
    assert stored(browser)["targets"].keys() == {BEA}


# ── POST /_/target takes the sheaf's name, as /_/export does (9.11) ──────────

def test_the_target_is_judged_and_stored_under_the_sheafs_name(front, browser, talk, work, monkeypatch):
    """A sheaf closed to the member between the check and the store takes no target: the check and the store are
    one step under the name's lock, as /_/export reads (9.11)."""
    import contextlib
    from sheafmd.hub import place, targets
    Tokens().add("bea-chatgpt", client="ChatGPT")
    front.hub.proxy = members(work, bea=["bea-chatgpt"])
    render(browser, talk)
    hub, held_at = browser.hub, {}
    depth = []

    @contextlib.contextmanager
    def held(h, address):
        depth.append(address)
        try:
            yield True
        finally:
            depth.pop()
    real_visible, real_pick = hub.visible, targets.pick
    monkeypatch.setattr(place, "held", held)
    monkeypatch.setattr(hub, "visible", lambda member, doc: held_at.update(visible=bool(depth)) or real_visible(member, doc))
    monkeypatch.setattr(targets, "pick", lambda *a: held_at.update(pick=bool(depth)) or real_pick(*a))
    assert pick(front, "agent:bea-chatgpt").status == 200
    assert held_at == {"visible": True, "pick": True}


def test_a_sheaf_closed_to_the_member_takes_no_target_and_is_a_404(front, browser, talk, work, monkeypatch):
    Tokens().add("bea-chatgpt", client="ChatGPT")
    front.hub.proxy = members(work, bea=["bea-chatgpt"])
    render(browser, talk)
    monkeypatch.setattr(browser.hub, "visible", lambda member, doc: False)
    assert pick(front, "agent:bea-chatgpt").status == 404
    assert BEA not in stored(browser).get("targets", {})


# ── the wire grammar is named once (ticket 12, row 23) ───────────────────────

def test_the_wire_grammar_is_read_in_one_place_and_the_page_reads_the_same_words():
    from pathlib import Path
    from sheafmd.hub import targets
    assert targets.parse("none") == ("none", None) and targets.parse("session") == ("session", None)
    assert targets.parse("agent:ada-chatgpt") == ("agent", "ada-chatgpt")
    assert targets.wire("ada-chatgpt") == "agent:ada-chatgpt"
    for bad in ("agent:", "agent", "", "Session", None, 3, {"kind": "agent"}):
        with pytest.raises(targets.Refused):
            targets.parse(bad)
    js = (Path(targets.__file__).parents[1] / "page" / "page.js").read_text()
    reads = js[js.index("function targetNow()"):js.index("function otherTargets()")]
    for word in ("'none'", "'session'", f"'{targets.AGENT_PREFIX}'"):
        assert word in reads, f"page.js targetNow no longer says {word}"


def test_targets_and_tell_import_each_other_nowhere_inside_a_function():
    import ast
    from pathlib import Path
    from sheafmd.hub import targets
    tree = ast.parse(Path(targets.__file__).read_text())
    inside = [n for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)
              for n in ast.walk(f) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert inside == []
    assert not any(isinstance(n, ast.ImportFrom) and n.module == "tell" and n.level == 1
                   for n in ast.walk(tree)), "targets must not import tell"
