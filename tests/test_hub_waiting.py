"""A Tell to an agent waits on the document until that agent next calls `documents` (SPEC 9.8, D26, 10.5, 12).

Over the HTTP door with fake agent tokens: the full loop, the token's stable `id` as the key, isolation between
tokens and between members, the transitions under one lock, and the diagnostics rows."""
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import sheafmd
from helpers import PLAN, claim_port, comment, hub_rows, ok
from sheafmd import comments as rdc
from sheafmd.source import update_file
from test_hub_tell import wait_until
from sheafmd.hub.state import Tokens
from test_hub_target import DOC, agent, members, pick, row

SECOND = "{agent} has this comment waiting already: cancel it first, or reply in the thread."


@pytest.fixture
def talk(plan):
    comment(plan)
    return plan


def agent_token(name="ada-chatgpt", client="ChatGPT", **kw):
    return Tokens().add(name, client=client, **kw)


def tell(browser, **body):
    return browser.post("/_/tell", {"doc": DOC, "id": "c1", **body})


def documents(browser, token, **args):
    return ok(browser, "documents", token=token, **args)


def target(browser, name="ada-chatgpt"):
    assert pick(browser, f"agent:{name}").status == 200


def tab(hub):
    return hub.entry(DOC).bus.subscribe()


def named(evs, name):
    return [d for n, d in evs if n == name]


# ── the full loop ────────────────────────────────────────────────────────────

def test_a_tell_to_an_agent_waits_is_listed_first_and_ends_on_its_action_reply(browser, talk):
    token = agent_token()
    target(browser)
    sub = tab(browser.hub)
    assert tell(browser).status == 200
    assert named(sub.drain(), "tell-queued") == [{"id": "c1", "agent": "ChatGPT (" + browser.hub.person + ")"}]
    first, = documents(browser, token)
    assert first["doc"] == DOC
    t, = first["tells"]
    assert t["thread"] == "c1" and "Why pears?" in t["message"] and 'role="action"' in t["message"]
    assert named(sub.drain(), "tell-seen") == [{"id": "c1"}]
    assert documents(browser, token)[0]["tells"][0]["id"] == t["id"]       # listed again, seen once
    assert named(sub.drain(), "tell-seen") == []
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", role="action", token=token)
    assert documents(browser, token)[0]["tells"] == []
    assert named(sub.drain(), "tell-done") == [{"id": "c1"}]


def test_the_changes_of_the_document_carry_the_tell_that_waits_as_telling(browser, talk):
    agent_token()
    target(browser)
    sub = tab(browser.hub)
    assert tell(browser).status == 200
    browser.hub.entry(DOC).live.refresh(force=True)
    browser.hub.entry(DOC).live.rebuild()
    got = [d for n, d in sub.drain() if n == "changed"]
    assert got and got[-1]["telling"] == [{"id": "c1", "to": "ChatGPT (" + browser.hub.person + ")", "state": "queued"}]


def test_a_token_that_only_reads_and_answers_comments_can_take_a_tell_and_end_it(browser, talk):
    token = agent_token()                                       # no --write: the right to pages, not to replies
    target(browser)
    assert tell(browser).status == 200
    assert documents(browser, token)[0]["tells"]
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", role="action", token=token)
    assert documents(browser, token)[0]["tells"] == []


def test_a_comment_sent_with_tell_writes_it_and_the_tell_waits(browser, talk):
    token = agent_token()
    target(browser)
    r = browser.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "body": "Please do.", "tell": True})
    assert r.status == 200 and "tellError" not in r.json()
    msg = documents(browser, token)[0]["tells"][0]["message"]
    assert "Please do." in msg


# ── the id, not the name, is the agent ───────────────────────────────────────

def test_a_token_made_again_under_the_same_name_never_receives_the_old_tell(browser, talk):
    old = agent_token()
    target(browser)
    assert tell(browser).status == 200
    Tokens().revoke("ada-chatgpt")
    new = agent_token()
    assert documents(browser, new)[0]["tells"] == []
    assert browser.hub.waiting_tells.waits(DOC) == []
    assert [r["token"] for r in hub_rows("tell-cancelled")] == ["ada-chatgpt"]


def test_revoking_a_token_ends_its_tells_as_cancelled_and_the_page_hears_of_it(browser, talk):
    agent_token()
    target(browser)
    sub = tab(browser.hub)
    assert tell(browser).status == 200
    Tokens().revoke("ada-chatgpt")
    browser.get(f"/_/doc?doc={DOC}")
    assert named(sub.drain(), "tell-cancelled")[0]["id"] == "c1"
    assert browser.get(f"/_/doc?doc={DOC}").json()["telling"] == []


def test_a_revoke_by_the_cli_ends_the_tell_at_the_watchers_next_pass_with_no_page_asking(browser, talk):
    agent_token()
    target(browser)
    sub = tab(browser.hub)
    assert tell(browser).status == 200
    sub.drain()
    Tokens().revoke("ada-chatgpt")                      # the CLI, in its own process: the hub is not called
    browser.hub.tick()
    assert named(sub.drain(), "tell-cancelled") == [{"id": "c1", "seen": False, "reason": "revoked"}]
    assert browser.hub.waiting_tells.waits(DOC, sweep=False) == []


@pytest.mark.parametrize("how", ["resolved", "deleted"])
def test_a_thread_closed_from_outside_ends_the_tell_at_the_watchers_next_pass(browser, talk, how):
    agent_token()
    target(browser)
    sub = tab(browser.hub)
    assert tell(browser).status == 200
    sub.drain()
    update_file(talk, (lambda t: rdc.set_status(t, "c1", "resolved")) if how == "resolved" else (lambda t: rdc.delete(t, "c1")))
    browser.hub.tick()
    assert named(sub.drain(), "tell-cancelled")[0]["id"] == "c1"
    assert browser.hub.waiting_tells.waits(DOC, sweep=False) == []


# ── one Tell waits per thread and agent ──────────────────────────────────────

def test_a_second_tell_to_the_same_agent_on_the_thread_is_refused_and_a_reply_sent_with_it_is_written(browser, talk):
    token = agent_token()
    target(browser)
    assert tell(browser).status == 200
    r = tell(browser)
    assert r.status == 409 and r.json()["error"] == SECOND.format(agent="ChatGPT (" + browser.hub.person + ")")
    r = browser.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "body": "Again.", "tell": True})
    assert r.status == 200 and r.json()["tellError"] == SECOND.format(agent="ChatGPT (" + browser.hub.person + ")")
    assert len(documents(browser, token)[0]["tells"]) == 1
    assert "Again." in str(ok(browser, "threads", doc=DOC, token=token))


# ── ends ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("how", ["resolve-door", "resolve-page", "delete-page"])
def test_resolving_or_deleting_the_thread_ends_the_tell(browser, talk, how):
    token = agent_token()
    target(browser)
    assert tell(browser).status == 200
    if how == "resolve-door":
        ok(browser, "resolve", doc=DOC, id="c1", token=token)
    elif how == "resolve-page":
        assert browser.post("/_/comment", {"doc": DOC, "op": "status", "id": "c1", "status": "resolved"}).status == 200
    else:
        assert browser.post("/_/comment", {"doc": DOC, "op": "delete", "id": "c1"}).status == 200
    assert browser.hub.waiting_tells.waits(DOC) == []
    assert documents(browser, token, open_only=False)[0]["tells"] == []


def test_a_cancel_from_the_page_ends_it_and_says_whether_the_agent_had_seen_it(browser, talk):
    token = agent_token()
    target(browser)
    sub = tab(browser.hub)
    assert tell(browser).status == 200
    assert browser.post("/_/cancel", {"doc": DOC, "id": "c1"}).status == 200
    assert named(sub.drain(), "tell-cancelled") == [{"id": "c1", "seen": False}]
    assert documents(browser, token)[0]["tells"] == []
    assert tell(browser).status == 200
    documents(browser, token)
    sub.drain()
    browser.post("/_/cancel", {"doc": DOC, "id": "c1"})
    assert named(sub.drain(), "tell-cancelled") == [{"id": "c1", "seen": True}]


# ── isolation ────────────────────────────────────────────────────────────────

def test_a_token_never_sees_the_tell_of_another_and_another_agents_reply_does_not_end_it(browser, talk):
    ada, bob = agent_token(), agent_token("bob-claude", "Claude")
    target(browser)
    assert tell(browser).status == 200
    assert documents(browser, bob)[0]["tells"] == []
    ok(browser, "reply", doc=DOC, id="c1", text="Mine.", role="action", token=bob)
    assert documents(browser, ada)[0]["tells"]


def bea_tells(front, browser, work, other, body="Please do."):
    """Bea has told her agent about c1 from her page; Cal and a token no member names are agents too."""
    bea, cal, loose = agent_token("bea-chatgpt"), agent_token("cal-chatgpt"), agent_token("loose", "Claude")
    front.hub.proxy = members(work, other, bea=["bea-chatgpt"], cal=["cal-chatgpt"])
    assert pick(front, "agent:bea-chatgpt").status == 200
    r = front.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "body": body, "tell": True})
    assert r.status == 200 and "tellError" not in r.json(), r.text
    return bea, cal, loose


def test_a_members_tell_waits_for_their_own_agent_only(front, browser, talk, work, other):
    bea, cal, loose = bea_tells(front, browser, work, other)
    t, = documents(browser, bea)[0]["tells"]
    assert t["by"] == "Bea" and "Please do." in t["message"]
    assert all(d["tells"] == [] for d in documents(browser, cal))
    assert all(d["tells"] == [] for d in documents(browser, loose))
    assert front.get(f"/_/doc?doc={DOC}").json()["telling"] == [{"id": "c1", "to": "ChatGPT (Bea)", "state": "seen"}]


def test_each_page_is_told_of_its_own_tells_only(front, browser, talk, work, other):
    """The hub person's page never hears of a member's Tell nor of the agent it waits for, and a member's page hears of
    their own, whole: queued, seen, cancelled (SPEC 9.9)."""
    bea, loose = agent_token("bea-chatgpt"), agent_token("ada-chatgpt")
    front.hub.proxy = members(work, other, bea=["bea-chatgpt"], cal=[])
    assert pick(front, "agent:bea-chatgpt").status == 200
    target(browser)
    mine, own = front.get(f"/_/live?doc={DOC}").stream, browser.get(f"/_/live?doc={DOC}").stream

    def heard(sub):
        return [(n, d) for n, d in sub.drain() if n.startswith("tell-")]
    r = front.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "body": "Please do.", "tell": True})
    assert r.status == 200 and "tellError" not in r.json(), r.text
    assert heard(mine) == [("tell-queued", {"id": "c1", "agent": "ChatGPT (Bea)"})] and heard(own) == []
    documents(browser, bea)
    assert heard(mine) == [("tell-seen", {"id": "c1"})] and heard(own) == []
    assert tell(browser).status == 200                                 # the hub person's, on the same thread
    assert heard(own) == [("tell-queued", {"id": "c1", "agent": "ChatGPT (" + browser.hub.person + ")"})] and heard(mine) == []
    assert front.post("/_/cancel", {"doc": DOC, "id": "c1"}).status == 200
    assert heard(mine) == [("tell-cancelled", {"id": "c1", "seen": True})] and heard(own) == []


def test_the_box_or_a_relay_comes_before_a_members_agent(front, browser, talk, work, other, monkeypatch):
    from sheafmd.hub.handler import Handler
    agent_token("bea-chatgpt")
    front.hub.proxy = members(work, other, bea=["bea-chatgpt"], cal=[])
    assert pick(front, "agent:bea-chatgpt").status == 200
    monkeypatch.setattr(Handler, "_work_route", lambda self, *a, **k: "box")
    assert front.post("/_/tell", {"doc": DOC, "id": "c1"}).status == 400
    front.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "body": "Please do.", "tell": True})
    assert front.hub.waiting_tells.pending(row("bea-chatgpt")) == set()


def test_a_member_with_no_agent_of_theirs_is_refused_the_tell_route_with_the_line_of_10_6(front, browser, talk, work, other):
    agent_token("bea-chatgpt")
    front.hub.proxy = members(work, other, bea=["bea-chatgpt"], cal=[])
    r = front.post("/_/tell", {"doc": DOC, "id": "c1"})
    assert r.status == 400 and r.json()["error"] == "Let one of your agents work on this page to Tell it."


def test_a_members_cancel_ends_only_their_own_tell_and_the_hub_persons_cancel_leaves_it(front, browser, talk, work, other):
    bea, cal, loose = bea_tells(front, browser, work, other)
    target(browser, "loose")                                         # the hub person has a Tell on the same thread
    assert tell(browser).status == 200
    assert browser.post("/_/cancel", {"doc": DOC, "id": "c1"}).status == 200
    assert documents(browser, bea)[0]["tells"] and documents(browser, loose)[0]["tells"] == []
    assert tell(browser).status == 200
    assert front.post("/_/cancel", {"doc": DOC, "id": "c1"}).status == 200
    assert documents(browser, bea)[0]["tells"] == [] and documents(browser, loose)[0]["tells"]


def test_a_member_tells_through_the_tell_route_only_their_own_agent_and_cannot_cancel_a_document_that_is_not_theirs(front, browser, talk, work, other):
    bea_tells(front, browser, work, other)
    assert front.post("/_/tell", {"doc": DOC, "id": "c1"}).status == 409        # her agent has the Tell on the thread already
    assert front.post("/_/cancel", {"doc": DOC, "id": "c1"}).status == 200
    assert front.post("/_/tell", {"doc": DOC, "id": "c1"}).status == 200        # the button, after a cancel
    assert [t["state"] for t in front.get(f"/_/doc?doc={DOC}").json()["telling"]] == ["queued"]
    (other / "theirs.md").write_text("# Theirs\n\nText.\n", encoding="utf-8")
    browser.hub.roots.for_document(other / "theirs.md")
    assert front.post("/_/cancel", {"doc": "other/theirs.md", "id": "c1"}).status == 404


# ── the transitions are made under one lock ──────────────────────────────────

def test_a_cancel_that_comes_while_the_first_listing_is_out_ends_it_once_and_seen_never_returns(browser, talk):
    token = agent_token()
    target(browser)
    assert tell(browser).status == 200
    waiting, order, done = browser.hub.waiting_tells, [], []
    real = waiting._emit

    def emit(address, name, data, member=None):
        if name == "tell-seen" and not order:
            c = threading.Thread(target=lambda: (browser.post("/_/cancel", {"doc": DOC, "id": "c1"}), done.append(1)))
            c.start()
            order.append(c)                                          # the cancel waits for the listing's lock
        real(address, name, data, member)
    waiting._emit = emit
    first = documents(browser, token)[0]
    order[0].join(5)
    assert first["tells"] and done == [1]
    assert documents(browser, token)[0]["tells"] == []
    assert waiting.waits(DOC) == []
    assert [r["thread"] for r in hub_rows("tell-seen")] == ["c1"] and len(hub_rows("tell-cancelled")) == 1


def test_a_cancel_first_leaves_nothing_to_list_and_nothing_seen(browser, talk):
    token = agent_token()
    target(browser)
    assert tell(browser).status == 200
    browser.post("/_/cancel", {"doc": DOC, "id": "c1"})
    assert documents(browser, token)[0]["tells"] == []
    assert hub_rows("tell-seen") == []


# ── diagnostics ──────────────────────────────────────────────────────────────

def test_each_step_writes_a_row_with_the_tokens_name_and_id_and_never_the_text(browser, talk):
    token = agent_token()
    tid = row("ada-chatgpt").id
    target(browser)
    tell(browser)
    documents(browser, token)
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", role="action", token=token)
    for kind in ("tell-queued", "tell-seen", "tell-done"):
        r, = hub_rows(kind)
        assert r["token"] == "ada-chatgpt" and r["tid"] == tid and r["thread"] == "c1"
        assert "pears" not in str(r)


# ── a real restart ───────────────────────────────────────────────────────────

class Process:
    """A hub in a process of its own, on its own SHEAF_HOME (the test's) and a free SHEAF_PORT."""

    def __init__(self, port):
        self.port = port
        self.proc = None

    def start(self):
        env = {**os.environ, "SHEAF_PORT": str(self.port)}
        self.proc = subprocess.Popen([sys.executable, "-m", "sheafmd", "hub", "--started-by", "cli"], env=env,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
        wait_until(lambda: self.reachable() or self.proc.poll() is not None, 20)
        assert self.proc.poll() is None, "the hub did not start"

    def reachable(self) -> bool:
        try:
            socket.create_connection(("127.0.0.1", self.port), 0.5).close()
            return True
        except OSError:
            return False

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()

    def send(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        h = {"Host": f"127.0.0.1:{self.port}", "Origin": f"http://127.0.0.1:{self.port}", **(headers or {})}
        data = json.dumps(body).encode() if body is not None else b""
        if data:
            h["Content-Type"] = "application/json"
        c.request(method, path, data, h)
        r = c.getresponse()
        out = r.read()
        c.close()
        return r.status, json.loads(out) if out else None


def test_a_tell_survives_a_real_restart_of_the_hub_process(work):
    from sheafmd import paths
    from sheafmd.hub.core import Hub
    assert Path(sheafmd.__file__).is_relative_to(Path(__file__).resolve().parents[1])
    port, release = claim_port()
    release()
    doc = work / "plan.md"
    doc.write_text(PLAN, encoding="utf-8")
    comment(doc)
    token = agent_token()
    key = paths.ensure_key()
    cookie = Hub(port=port, key=key, started_by="test").auth     # the cookie the page of this hub would hold
    signed_in = {"Cookie": f"{cookie.cookie_name}={cookie.cookie_value()}"}
    door = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    ask = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "documents", "arguments": {}}}
    hub = Process(port)
    try:
        hub.start()
        first = hub.proc.pid
        assert hub.send("POST", "/_/render", {"path": str(doc), "settings": {}, "target": None},
                        {"X-Sheaf-Key": key})[0] == 200
        assert hub.send("POST", "/_/target", {"doc": DOC, "target": "agent:ada-chatgpt"}, signed_in)[0] == 200
        assert hub.send("POST", "/_/tell", {"doc": DOC, "id": "c1"}, signed_in)[0] == 200
        hub.stop()
        assert hub.proc.poll() is not None
        hub.start()
        assert hub.proc.pid != first
        status, got = hub.send("POST", "/_/mcp", ask, door)
        rows = json.loads(got["result"]["content"][0]["text"])
        assert status == 200 and rows[0]["doc"] == DOC and rows[0]["tells"][0]["thread"] == "c1"
        status, page = hub.send("GET", f"/_/doc?doc={DOC}", None, signed_in)
        assert [(w["id"], w["state"]) for w in page["telling"]] == [("c1", "seen")]
    finally:
        hub.stop()


# ── a waiting Tell runs nothing ──────────────────────────────────────────────

def test_a_waiting_tell_gives_no_orange_dot_and_does_not_hold_an_upgrade_back(browser, talk):
    token = agent_token()
    target(browser)
    assert tell(browser).status == 200
    hub = browser.hub
    assert not hub.busy() and not hub.waiting(DOC) and browser.get("/_/jobs", key=True, cookie=False).json()["telling"] == []
    row, = documents(browser, token)
    assert row["dot"] == "blue"


def test_the_instructions_tell_the_agent_to_call_documents_first(browser):
    from helpers import door, rpc
    got = door(browser, rpc("initialize", {"protocolVersion": "2025-06-18"})).json()["result"]["instructions"]
    assert "Call `documents` first" in got and "`tells`" in got


# ── a Tell the target cannot take ────────────────────────────────────────────

def test_a_tell_to_a_revoked_agent_is_refused_with_the_revoked_line(browser, talk):
    agent_token()
    target(browser)
    Tokens().revoke("ada-chatgpt")
    r = tell(browser)
    assert r.status == 409 and "token was revoked" in r.json()["error"]
    assert browser.hub.waiting_tells.waits(DOC) == []


# ── one open: the file is judged and read through the same descriptor (SPEC 9.11) ─────────────────────────────

def test_a_file_swapped_after_documents_judged_it_builds_no_tell_from_the_swapped_in_text(browser, talk, work, monkeypatch):
    from sheafmd import beneath
    token = agent_token()
    target(browser)
    assert tell(browser).status == 200
    other = work / "plan.swap"
    other.write_text(PLAN, encoding="utf-8")
    comment(other, body="SWAPPED IN")
    real, swapped = beneath.open_beneath, []

    def swapping(top, rel):
        op = real(top, rel)
        if not swapped and str(rel).endswith("plan.md"):
            swapped.append(1)
            os.replace(other, talk)                       # the name now holds another file; `op` holds the judged one
        return op
    monkeypatch.setattr(beneath, "open_beneath", swapping)
    first, = documents(browser, token)
    assert swapped
    t, = first["tells"]
    assert "Why pears?" in t["message"] and "SWAPPED IN" not in t["message"]


def test_the_watcher_reads_a_document_through_the_judged_open_and_ends_nothing_from_a_file_that_is_refused(browser, talk):
    agent_token()
    target(browser)
    assert tell(browser).status == 200
    update_file(talk, lambda t: rdc.set_status(t, "c1", "resolved"))
    e = browser.hub.entry(DOC)

    def refuse(op):
        raise PermissionError(13, "in a private root of another member")
    e.judge = refuse
    browser.hub.tick()
    assert [w["id"] for w in browser.hub.waiting_tells.waits(DOC, sweep=False)] == ["c1"]   # not decided from it
