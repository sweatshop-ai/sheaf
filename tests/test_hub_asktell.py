"""Ask, Tell and Cancel through the hub (SPEC 8.10, 10.5, 10.6, 11.2, 11.3).

The handler runs in the test's process, with no HTTP socket. The session is a record in the
test's config folder, its message socket a Unix socket that a thread of the test listens on,
and `claude` a shell script of the test's own that the hub starts as a child: nothing here
reaches a real session, socket or config (the conftest gives every test its own HOME)."""
import json
import os
import socket
import subprocess
import threading
import time

import pytest

import sheafmd.comments as rdc
from agent_fakes import PID, FakeClaude, Peer, write_record
from helpers import PLAN, browser_on, holds_number, page_meta, proc_state, writes_from_outside
from sheafmd import diagnostics, paths
from sheafmd.agents import prompts
from sheafmd.agents.base import State
from sheafmd.agents.claude_code import proc_start
from sheafmd.hub import live, state
from sheafmd.hub.core import Hub
from sheafmd.hub.handler import NO_AGENT
from sheafmd.source import md_hash, update_file

DOC = "work/plan.md"
URL = "/work/plan.md"
NOT_YET = ("{product} can answer threads through the MCP door. Ask and Tell need an adapter "
           "sheaf does not have yet.")
ENDED = "The Claude Code session that rendered this page has ended. Render it again from a session."
NO_SOCKET = ("Tell needs the session's message socket, which was not found. Render the page "
             "again from the session.")
GONE = "The document is no longer on the hub: its folder was forgotten, or its file is gone."


def at_the_jobs_own_look(monkeypatch, hub, act):
    """`act()` runs when the job looks the document up (the second `hub.entry`, after the route's), and
    the look then goes as usual. The addresses looked up are listed in what it returns."""
    real, asked = hub.entry, []

    def in_between(address):
        asked.append(address)
        if len(asked) == 2:
            monkeypatch.setattr(hub, "entry", real)
            act()
        return real(address)
    monkeypatch.setattr(hub, "entry", in_between)
    return asked


def forgotten_and_taken(browser, hub, new, session):
    """What happens at the job's own look in the tests of a forget in between: the root is forgotten, and
    the folder of `new` takes its name."""
    def act():
        assert hub.forget_root("work").name == "work"
        assert attach(browser, new, session.target()).json()["doc"] == DOC
    return act


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def hub(work, clock):
    h = Hub(port=27419, key=paths.ensure_key(), started_by="test", clock=clock)
    yield h
    h.runner.kill_all()
    h.runner.join(10)


@pytest.fixture
def cfg(tmp_path):
    d = tmp_path / "claude-config"
    (d / "sessions").mkdir(parents=True)
    return d


@pytest.fixture
def peer(short_tmp):
    p = Peer(os.path.join(short_tmp, "s.sock"))
    yield p
    p.close()


@pytest.fixture
def claude(tmp_path):
    return FakeClaude(tmp_path / "fake")


class Session:
    def __init__(self, cfg, peer, claude, cwd):
        self.cfg, self.peer, self.claude, self.cwd = cfg, peer, claude, cwd

    def record(self, **fields):
        fields.setdefault("messagingSocketPath", self.peer.path)
        return write_record(self.cfg, **fields)

    def target(self, **over):
        t = {"agent": "claude-code", "session": "s-1", "pid": PID, "socket": self.peer.path,
             "name": "Cosima", "cwd": str(self.cwd), "bin": str(self.claude.bin),
             "config_dir": str(self.cfg), "proc_start": proc_start(PID)}
        t.update(over)
        return t


@pytest.fixture
def session(cfg, peer, claude, work):
    s = Session(cfg, peer, claude, work)
    s.record()
    return s


def attach(browser, plan, target):
    r = browser.post("/_/render", {"path": str(plan), "settings": {}, "target": target},
                     key=True, cookie=False)
    assert r.status == 200, r.text
    return r


def comment(plan, quote="Second paragraph", body="Why pears?"):
    """A thread on the plan, written the way a person's comment is."""
    update_file(plan, lambda t: rdc.add_comment(t, *rdc.find_quote(t, quote), quote, body, "Ada",
                                                "2026-10-14T10:00")[0])
    return "c1"


def thread(plan, cid="c1"):
    return rdc.parse(plan.read_text(encoding="utf-8")).by_id(cid)


@pytest.fixture
def ready(browser, plan, session):
    """A plan with a thread c1, rendered from the Claude Code session."""
    attach(browser, plan, session.target())
    comment(plan)
    return plan


def tab(hub):
    return hub.entry(DOC).bus.subscribe()


def events(sub):
    return sub.drain()


def named(evs, name):
    return [d for n, d in evs if n == name]


def post(browser, route, **body):
    return browser.post(route, {"doc": DOC, "id": "c1", **body})


def finish(hub, within=15):
    """Every job started so far has ended. `Jobs.join` returns when its time is up, ended or not, and a
    test that went on from there would assert on a world a stop job is still changing: say which job
    is still there instead."""
    hub.runner.join(within)
    alive = [t.name for t in hub.runner._threads if t.is_alive()]
    assert not alive, f"jobs still running {within} s after the last was started: {alive}"


def ended(pid):
    """The process has ended or is a zombie. Unlike helpers.gone it reaps nothing: a child of
    this test that a job still waits for must not be reaped here, or its return code would read
    0 in place of the signal that ended it."""
    return proc_state(pid) != "alive"


def wait_until(cond, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


# ── what the page is told about the agent ────────────────────────────────────

def test_a_page_rendered_from_a_claude_code_session_offers_ask_and_tell_to_it(
        browser, plan, session):
    attach(browser, plan, session.target())
    meta = page_meta(browser.get(URL).text)
    assert meta["agent"] == {"agent": "claude-code", "display": "Claude", "product": "Claude Code",
                             "name": "Cosima", "label": "Cosima"}
    assert meta["can"] == ["ask", "deliver"]
    assert meta["lines"] == {"ask": None, "tell": None}


def test_a_session_without_a_name_is_labelled_by_the_start_of_its_id(browser, plan, session):
    session.record(name="")
    attach(browser, plan, session.target(name="", session="s-1"))
    assert page_meta(browser.get(URL).text)["agent"]["label"] == "s-1"
    long_id = "3e1f9a2b-0000-4000-8000-000000000001"
    session.record(name="", sessionId=long_id)
    attach(browser, plan, session.target(name="", session=long_id))
    assert page_meta(browser.get(URL).text)["agent"]["label"] == "3e1f9a2b"


def test_a_session_renamed_after_the_render_is_shown_by_its_new_name(browser, plan, session):
    attach(browser, plan, session.target())
    session.record(name="Beatrix")
    agent = page_meta(browser.get(URL).text)["agent"]
    assert (agent["name"], agent["label"]) == ("Beatrix", "Beatrix")
    assert agent["display"] == "Claude"


def test_a_session_whose_record_is_gone_keeps_the_name_stored_at_the_render(browser, plan, session):
    attach(browser, plan, session.target())
    os.unlink(session.cfg / "sessions" / f"{PID}.json")
    assert page_meta(browser.get(URL).text)["agent"]["name"] == "Cosima"


def test_the_name_the_page_is_given_is_cleaned_by_the_rule_of_a_display_name(browser, plan, session):
    attach(browser, plan, session.target())
    session.record(name="Lin\x07nea \n  Two")
    assert page_meta(browser.get(URL).text)["agent"]["name"] == "Linnea Two"
    session.record(name="x" * 80)
    assert page_meta(browser.get(URL).text)["agent"]["name"] == "x" * 60
    session.record(name="\x07 ")
    assert page_meta(browser.get(URL).text)["agent"]["name"] == "Cosima"


@pytest.mark.parametrize("pid", [PID, 260])      # 260: a runner's pid; page.js holds "2600", which is not it
def test_the_page_never_holds_the_session_id_the_socket_or_the_command(browser, plan, session, pid):
    attach(browser, plan, session.target(session="s-secret-1"))
    session.record(sessionId="s-secret-1")
    page = browser.get(URL).text
    doc = browser.get(f"/_/doc?doc={DOC}").text
    for text in (page, doc):
        for private in ("s-secret-1", session.peer.path, str(session.claude.bin), str(session.cfg)):
            assert private not in text.replace('"pid"', ""), private
        assert not holds_number(text, pid), pid


def test_a_page_with_no_session_says_so_under_both_buttons(browser, plan):
    meta = page_meta(browser.get(URL).text)
    assert meta["agent"] is None and meta["can"] == []
    assert meta["lines"] == {"ask": NO_AGENT, "tell": NO_AGENT}


@pytest.mark.parametrize("agent, product", [("codex", "Codex CLI"), ("cursor", "Cursor agent"),
                                            ("opencode", "opencode"), ("gemini", "Gemini CLI")])
def test_an_agent_without_an_adapter_gets_disabled_buttons_with_their_line(
        browser, plan, agent, product):
    attach(browser, plan, {"agent": agent, "session": "t-1"})
    meta = page_meta(browser.get(URL).text)
    line = NOT_YET.format(product=product)
    assert meta["can"] == [] and meta["lines"] == {"ask": line, "tell": line}
    assert meta["agent"]["product"] == product
    got = browser.get(f"/_/doc?doc={DOC}").json()
    assert got["capabilities"] == [] and got["lines"] == {"ask": line, "tell": line}
    for route in ("/_/ask", "/_/tell"):
        comment(plan)
        r = post(browser, route)
        assert (r.status, r.json()["error"]) == (409, line)


def test_an_agent_the_user_named_that_sheaf_does_not_know_shows_that_name(browser, plan):
    attach(browser, plan, {"agent": "foo"})
    meta = page_meta(browser.get(URL).text)
    assert meta["agent"]["display"] == "foo"
    assert meta["lines"]["ask"] == NOT_YET.format(product="foo")


def test_a_session_that_has_ended_disables_tell_with_its_line_and_still_may_ask(
        browser, plan, session):
    attach(browser, plan, session.target())
    (session.cfg / "sessions" / f"{PID}.json").unlink()
    session.peer.close()
    os.unlink(session.peer.path)
    meta = page_meta(browser.get(URL).text)
    assert meta["can"] == ["ask"]
    assert meta["lines"] == {"ask": None, "tell": ENDED}


def test_a_session_whose_socket_was_not_found_says_that_under_tell_only(browser, plan, session):
    session.record(messagingSocketPath="")
    attach(browser, plan, session.target(socket=""))
    meta = page_meta(browser.get(URL).text)
    assert meta["can"] == ["ask"] and meta["lines"] == {"ask": None, "tell": NO_SOCKET}


def test_without_the_command_ask_is_disabled_with_a_line(browser, plan, session):
    attach(browser, plan, session.target(bin=""))
    meta = page_meta(browser.get(URL).text)
    assert meta["can"] == ["deliver"]
    assert "Ask needs" in meta["lines"]["ask"] and meta["lines"]["tell"] is None


def test_doc_gives_the_public_part_of_the_target_and_what_it_can_do(browser, plan, session):
    attach(browser, plan, session.target())
    got = browser.get(f"/_/doc?doc={DOC}").json()
    assert got["target"] == {"agent": "claude-code", "display": "Claude",
                             "product": "Claude Code", "name": "Cosima", "label": "Cosima"}
    assert got["capabilities"] == ["ask", "deliver", "state", "stop"]
    assert got["asking"] == [] and got["telling"] == [] and got["question"] == ""


# ── the target a render records ──────────────────────────────────────────────

def test_a_render_with_a_malformed_target_is_refused_in_one_sentence(browser, plan):
    for bad in ({"agent": 3}, {"agent": "x", "pid": "9"}, {"session": "s"}, {"agent": "a b"},
                {"agent": "x", "socket": ["a"]}, [], "claude"):
        r = browser.post("/_/render", {"path": str(plan), "target": bad}, key=True, cookie=False)
        assert r.status == 400 and r.json()["ok"] is False, bad
    assert browser.hub.docs.get(DOC).get("target") is None


def test_a_render_that_finds_no_agent_keeps_the_stored_target_and_none_clears_it(
        browser, plan, session):
    attach(browser, plan, session.target())
    r = browser.post("/_/render", {"path": str(plan), "target": None}, key=True, cookie=False)
    assert r.status == 200 and browser.hub.docs.get(DOC)["target"]["session"] == "s-1"
    attach(browser, plan, {"agent": "none"})
    assert browser.hub.docs.get(DOC)["target"] is None
    assert page_meta(browser.get(URL).text)["lines"]["ask"] == NO_AGENT


def test_the_page_cannot_set_the_target(browser, plan, session):
    r = browser.post("/_/render", {"path": str(plan), "target": session.target()})
    assert r.status == 403
    assert browser.hub.docs.get(DOC).get("target") is None


# ── Ask ──────────────────────────────────────────────────────────────────────

def test_ask_forks_the_session_and_writes_its_answer_as_a_reply_with_the_role_answer(
        browser, hub, ready, session, work):
    sub = tab(hub)
    sub.drain()
    asked = thread(ready)
    held = hub.entry(DOC).live.snapshot()["hash"]               # the text a tab holds when it asks
    r = post(browser, "/_/ask")
    assert r.status == 200 and r.json() == {"ok": True}
    finish(hub)
    evs = events(sub)
    assert [n for n, _ in evs] == ["ask-started", "ask-done"]
    c = thread(ready)
    assert [(x.by, x.role, x.text) for x in c.replies] == [("Claude", "answer", "The answer.")]
    done = named(evs, "ask-done")[0]
    assert done["id"] == "c1" and done["hash"] == md_hash(ready.read_text(encoding="utf-8"))
    assert done["textSame"] is True and done["base"] == held != done["hash"]
    assert done["comments"][0]["replies"][0]["role"] == "answer"
    [call] = session.claude.calls()
    prompt = prompts.ask(str(ready), asked, links=True)
    assert call["argv"] == ["-p", "--resume", "s-1", "--fork-session", "--tools", "Read,Grep,Glob",
                            "--allowedTools", "Read,Grep,Glob", "--disallowedTools",
                            "Bash,Edit,Write,NotebookEdit", "--strict-mcp-config",
                            "--output-format", "text"]
    assert call["stdin"] == prompt                      # the thread and the path never go on argv
    assert not [a for a in call["argv"] if "Why pears?" in a or str(ready) in a]
    assert call["cwd"] == os.path.realpath(work)


def test_ask_and_the_courier_run_under_the_config_folder_of_the_session(
        browser, hub, ready, session, tmp_path, monkeypatch):
    """`--resume` finds a session in the config folder it runs under: the hub's own may be
    another one than the session's."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "the-hubs-own"))
    post(browser, "/_/ask")
    finish(hub)
    FakeClaude(session.claude.dir, answer="sent")
    session.record(peerProtocol=2)
    post(browser, "/_/tell")
    finish(hub)
    asked, told = session.claude.calls()
    assert asked["config_var"] == told["config_var"] == str(session.cfg)


def test_ask_that_is_already_running_on_the_thread_is_refused(browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="x", sleep=30)
    assert post(browser, "/_/ask").status == 200
    assert wait_until(lambda: session.claude.calls() != [])
    r = post(browser, "/_/ask")
    assert r.status == 409 and r.json()["error"] == "Cosima is already answering this comment"
    assert hub.runner.active("ask") == [[DOC, "c1"]]
    assert browser.get(f"/_/doc?doc={DOC}").json()["asking"] == ["c1"]
    assert browser.get("/_/jobs", cookie=False, key=True).json()["asking"] == [[DOC, "c1"]]


def test_an_ask_that_runs_turns_the_dot_of_its_document_orange_and_cancel_turns_it_back(
        browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="x", sleep=30)

    def dot():
        [d] = [d for r in browser.get("/_/index.json").json()["roots"] for d in r["docs"]
               if d["doc"] == DOC]
        return d["dot"]
    assert dot() == "blue"
    assert post(browser, "/_/ask").status == 200
    assert wait_until(lambda: session.claude.calls() != [])
    assert dot() == "orange"
    assert post(browser, "/_/cancel", what="ask").json() == {"ok": True}
    finish(hub)
    assert dot() == "blue"


def test_a_second_thread_may_be_asked_at_the_same_time(browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="x", sleep=30)
    update_file(ready, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "First paragraph"),
                                                 "First paragraph", "Why?", "Ada", "2026-10-14T10:01")[0])
    assert post(browser, "/_/ask", id="c1").status == 200
    assert post(browser, "/_/ask", id="c2").status == 200


def test_ask_failing_says_the_last_three_lines_of_stderr_and_writes_nothing(
        browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="", err="one\ntwo\nthree\nfour", code=1)
    sub = tab(hub)
    sub.drain()
    before = ready.read_text(encoding="utf-8")
    post(browser, "/_/ask")
    finish(hub)
    [failed] = named(events(sub), "ask-failed")
    assert failed["id"] == "c1" and "two three four" in failed["error"] and "one" not in failed["error"]
    assert ready.read_text(encoding="utf-8") == before
    assert hub.runner.active("ask") == []


def test_an_empty_answer_is_a_failure_too(browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="  \n", err="")
    sub = tab(hub)
    sub.drain()
    post(browser, "/_/ask")
    finish(hub)
    [failed] = named(events(sub), "ask-failed")
    assert "no answer" in failed["error"] and thread(ready).replies == []


def test_ask_that_takes_too_long_is_killed_and_fails(browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="late", sleep=30)
    hub.asktell.ask_timeout = 0.5
    sub = tab(hub)
    sub.drain()
    post(browser, "/_/ask")
    finish(hub)
    [failed] = named(events(sub), "ask-failed")
    assert failed["error"].startswith("Cosima did not answer within")
    [call] = session.claude.calls()
    assert ended(call["pid"]) and thread(ready).replies == []


def test_ask_whose_command_is_missing_says_so(browser, hub, ready, session):
    sub = tab(hub)
    sub.drain()
    session.claude.bin.unlink()
    r = post(browser, "/_/ask")
    assert r.status == 409 and "Ask needs" in r.json()["error"]


def test_ask_answering_a_comment_that_was_deleted_meanwhile_fails_and_writes_nothing(
        browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="too late", sleep=1)
    sub = tab(hub)
    sub.drain()
    post(browser, "/_/ask")
    assert wait_until(lambda: session.claude.calls() != [])
    update_file(ready, lambda t: rdc.delete(t, "c1"))
    finish(hub)
    assert named(events(sub), "ask-failed") and "too late" not in ready.read_text(encoding="utf-8")


def test_an_answer_never_lands_in_another_thread_that_took_the_id_of_the_asked_one(
        browser, hub, ready, session):
    """Ids are the highest plus one, so deleting the last comment frees its id for the next
    one. The answer belongs to the thread the prompt was made from."""
    FakeClaude(session.claude.dir, answer="too late", sleep=1)
    sub = tab(hub)
    sub.drain()
    post(browser, "/_/ask")
    assert wait_until(lambda: session.claude.calls() != [])
    update_file(ready, lambda t: rdc.delete(t, "c1"))
    update_file(ready, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "Second paragraph"),
                                                 "Second paragraph", "Unrelated!", "Bo",
                                                 "2026-10-14T11:30")[0])
    finish(hub)
    [failed] = named(events(sub), "ask-failed")
    assert failed["id"] == "c1" and "the comment changed" in failed["error"]
    assert thread(ready).by == "Bo" and thread(ready).replies == []
    assert "too late" not in ready.read_text(encoding="utf-8")


def test_an_answer_still_lands_when_others_replied_to_the_thread_meanwhile(
        browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="The answer.", sleep=1)
    sub = tab(hub)
    sub.drain()
    post(browser, "/_/ask")
    assert wait_until(lambda: session.claude.calls() != [])
    update_file(ready, lambda t: rdc.reply(t, "c1", "Me too", "Bo", "2026-10-14T11:30", False, None))
    finish(hub)
    assert named(events(sub), "ask-done")
    assert [r.text for r in thread(ready).replies] == ["Me too", "The answer."]


def test_ask_of_a_comment_that_is_not_there_is_404(browser, ready, session):
    r = post(browser, "/_/ask", id="c9")
    assert r.status == 404 and r.json()["error"] == "no comment c9 in this document"
    assert session.claude.calls() == []


def test_ask_of_a_document_with_no_session_is_409_whatever_the_comment(browser, plan):
    assert post(browser, "/_/ask", id="c9").json() == {"ok": False, "error": NO_AGENT}


def test_a_comment_added_with_ask_starts_the_ask_and_one_without_a_session_says_why(
        browser, hub, plan, session):
    attach(browser, plan, session.target())
    text = plan.read_text(encoding="utf-8")
    blk, s, e = rdc.find_quote(text, "Second paragraph")
    r = browser.post("/_/comment", {"doc": DOC, "op": "add", "hash": md_hash(text), "block": blk,
                                    "start": s, "end": e, "quote": "Second paragraph",
                                    "body": "Why pears?", "ask": True})
    assert r.json()["ok"] is True and "askError" not in r.json()
    finish(hub)
    assert [x.text for x in thread(plan).replies] == ["The answer."]


def test_a_reply_sent_with_ask_starts_the_ask_too(browser, hub, ready, session):
    text = ready.read_text(encoding="utf-8")
    r = browser.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "hash": md_hash(text),
                                    "body": "And plums?", "ask": True})
    assert r.json()["ok"] is True and "askError" not in r.json()
    finish(hub)
    assert [(x.by, x.role) for x in thread(ready).replies] == [("Ada", None), ("Claude", "answer")]


# The page gave up on the answer and sends the reply again with its request id: the hub took the first, so the
# second writes nothing and starts no second Ask.
def test_a_reply_sent_again_with_its_request_id_starts_no_second_ask(browser, hub, ready, session):
    text = ready.read_text(encoding="utf-8")
    body = {"doc": DOC, "op": "reply", "id": "c1", "hash": md_hash(text), "body": "And plums?", "ask": True,
            "rid": "r0123456789abcdef"}
    assert browser.post("/_/comment", body).json()["ok"] is True
    finish(hub)
    again = browser.post("/_/comment", body).json()
    assert again["ok"] is True and again["again"] is True and "askError" not in again
    finish(hub)
    assert [(x.by, x.role) for x in thread(ready).replies] == [("Ada", None), ("Claude", "answer")]
    assert len(session.claude.calls()) == 1


# ── Cancel an Ask ────────────────────────────────────────────────────────────

def test_cancelling_an_ask_kills_the_fork_writes_nothing_and_says_cancelled(
        browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="partial", sleep=30)
    sub = tab(hub)
    sub.drain()
    before = ready.read_text(encoding="utf-8")
    post(browser, "/_/ask")
    assert wait_until(lambda: session.claude.calls() != [])
    pid = session.claude.calls()[0]["pid"]
    r = post(browser, "/_/cancel", what="ask")
    assert r.json() == {"ok": True}
    finish(hub)
    names = [n for n, _ in events(sub)]
    assert names == ["ask-started", "ask-cancelled"]
    assert ended(pid) and ready.read_text(encoding="utf-8") == before
    assert hub.runner.active("ask") == []


def test_cancelling_an_ask_that_is_no_longer_running_still_clears_the_page(
        browser, hub, ready):
    sub = tab(hub)
    sub.drain()
    assert post(browser, "/_/cancel", what="ask").json() == {"ok": True}
    assert events(sub) == [("ask-cancelled", {"id": "c1"})]


# ── Tell ─────────────────────────────────────────────────────────────────────

def test_tell_pushes_the_message_to_the_session_in_under_a_second_and_waits(
        browser, hub, ready, session):
    sub = tab(hub)
    sub.drain()
    t0 = time.monotonic()
    r = post(browser, "/_/tell")
    got = session.peer.wait_for(1)[0]
    assert time.monotonic() - t0 < 1.0
    assert r.status == 200 and r.json() == {"ok": True}
    msg = json.loads(got)
    assert msg["msgV"] == 1 and msg["type"] == "user" and msg["priority"] == "next"
    content = msg["message"]["content"]
    sender = f"uds:{paths.runtime_dir()}/hub-27419.sock"
    assert msg["from"] == sender
    assert content.startswith(f'<cross-session-message from="{sender}" from-name="sheaf" '
                              'from-mode="prompting">\n')
    body = content.split(">\n", 1)[1].rsplit("\n</cross-session-message>", 1)[0]
    assert body == prompts.tell(DOC, str(ready), "Ada", thread(ready), links=True)
    finish(hub)
    assert [n for n, _ in events(sub)] == ["tell-sent"]
    assert browser.get(f"/_/doc?doc={DOC}").json()["telling"] == ["c1"]
    assert browser.get("/_/jobs", cookie=False, key=True).json()["telling"] == [[DOC, "c1"]]


def test_the_thread_waits_until_a_reply_with_the_role_action_lands(browser, hub, ready, session):
    sub = tab(hub)
    sub.drain()
    post(browser, "/_/tell")
    finish(hub)
    events(sub)
    at = "2026-10-14T10:05"
    update_file(ready, lambda t: rdc.reply(t, "c1", "Just chatting.", "Claude", at, role="answer"))
    hub.tick()
    assert browser.get(f"/_/doc?doc={DOC}").json()["telling"] == ["c1"]
    update_file(ready, lambda t: rdc.reply(t, "c1", "Done.", "Claude", at, role="action"))
    hub.tick()
    changed = named(events(sub), "changed")[-1]
    assert changed["telling"] == []
    assert browser.get(f"/_/doc?doc={DOC}").json()["telling"] == []
    assert hub.entry(DOC).live.waiting() == []


def test_a_tell_nobody_answers_fails_after_ten_minutes_naming_the_product(
        browser, hub, ready, session, clock):
    sub = tab(hub)
    sub.drain()
    post(browser, "/_/tell")
    finish(hub)
    events(sub)
    clock.t += 600
    hub.tick()
    assert named(events(sub), "tell-failed") == []
    clock.t += 1
    hub.tick()
    [failed] = named(events(sub), "tell-failed")
    assert failed == {"id": "c1", "error": "no reply from the Claude Code session after 10 min. "
                      "It may be busy, closed, or it answered in its own chat. Tell again, or "
                      "reply here."}
    assert hub.entry(DOC).live.waiting() == []


def test_a_session_waiting_on_its_person_shows_the_question_and_pauses_the_clock(
        browser, hub, ready, session, clock):
    sub = tab(hub)
    sub.drain()
    post(browser, "/_/tell")
    finish(hub)
    events(sub)
    session.record(status="waiting", waitingFor="Which tagline?")
    hub.tick()
    assert named(events(sub), "tell-waiting") == [{"ids": ["c1"], "question": "Which tagline?"}]
    assert browser.get(f"/_/doc?doc={DOC}").json()["question"] == "Which tagline?"
    clock.t += 3600
    hub.tick()
    assert named(events(sub), "tell-failed") == [] and hub.entry(DOC).live.waiting() == ["c1"]
    session.record(status="busy")
    hub.tick()
    assert named(events(sub), "tell-working") == [{"ids": ["c1"]}]
    clock.t += 600
    hub.tick()
    assert hub.entry(DOC).live.waiting() == ["c1"]             # the clock restarted
    clock.t += 1
    hub.tick()
    assert named(events(sub), "tell-failed")


def test_a_wait_is_not_left_when_the_state_cannot_be_read(browser, hub, ready, session, clock):
    post(browser, "/_/tell")
    finish(hub)
    (session.cfg / "sessions" / f"{PID}.json").write_text("{broken")
    hub.tick()                                                  # a gone session is not an error
    assert hub.entry(DOC).live.waiting() == ["c1"]


def test_a_failing_delivery_ends_the_wait_and_says_why(browser, hub, ready, session, short_tmp):
    deaf = socket.socket(socket.AF_UNIX)
    deaf.bind(os.path.join(short_tmp, "deaf.sock"))            # a file nobody listens behind
    try:
        session.record(messagingSocketPath=os.path.join(short_tmp, "deaf.sock"))
        sub = tab(hub)
        sub.drain()
        assert post(browser, "/_/tell").status == 200
        finish(hub)
        [failed] = named(events(sub), "tell-failed")
        assert failed["id"] == "c1" and "Claude Code" in failed["error"]
        assert hub.entry(DOC).live.waiting() == []
    finally:
        deaf.close()


def test_a_peer_protocol_other_than_1_delivers_through_the_courier(browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="sent")
    session.record(peerProtocol=2)
    sub = tab(hub)
    sub.drain()
    post(browser, "/_/tell")
    finish(hub)
    assert session.peer.data == b""
    [call] = session.claude.calls()
    assert call["argv"] == ["-p", "--model", "haiku", "--allowedTools", "SendMessage",
                            "--output-format", "text"]
    assert 'to = "uds:' in call["stdin"] and "Why pears?" not in " ".join(call["argv"])
    assert call["session_var"] == ""                             # set to empty, not inherited
    assert [n for n, _ in events(sub)] == ["tell-sent"]
    assert [r for r in diagnostics.read() if r["kind"] == "tell-courier"][0]["peerProtocol"] == "2"


def test_a_courier_that_does_not_say_sent_fails_the_tell(browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="no luck", err="denied")
    session.record(peerProtocol=2)
    sub = tab(hub)
    sub.drain()
    post(browser, "/_/tell")
    finish(hub)
    [failed] = named(events(sub), "tell-failed")
    assert "delivery failed" in failed["error"] and hub.entry(DOC).live.waiting() == []


def test_a_tell_without_a_socket_is_refused_with_its_line_and_waits_for_nothing(
        browser, hub, ready, session):
    attach(browser, ready, session.target(socket=""))
    session.record(messagingSocketPath="")
    r = post(browser, "/_/tell")
    assert r.status == 409 and r.json()["error"] == NO_SOCKET
    assert hub.entry(DOC).live.waiting() == []


def test_tell_of_a_comment_that_is_not_there_is_404_and_pushes_nothing(browser, ready, session):
    r = post(browser, "/_/tell", id="c9")
    assert r.status == 404 and session.peer.data == b""


def test_a_comment_added_with_tell_is_written_delivered_and_waits(browser, hub, plan, session):
    attach(browser, plan, session.target())
    text = plan.read_text(encoding="utf-8")
    blk, s, e = rdc.find_quote(text, "Second paragraph")
    r = browser.post("/_/comment", {"doc": DOC, "op": "add", "hash": md_hash(text), "block": blk,
                                    "start": s, "end": e, "quote": "Second paragraph",
                                    "body": "Fix this.", "tell": True})
    got = r.json()
    assert got["ok"] is True and got["telling"] == ["c1"] and "tellError" not in got
    finish(hub)
    content = json.loads(session.peer.wait_for(1)[0])["message"]["content"]
    assert "pressed Tell on comment c1" in content and "Fix this." in content


def test_a_comment_added_with_tell_but_no_way_to_deliver_is_still_written(browser, hub, plan):
    text = plan.read_text(encoding="utf-8")
    blk, s, e = rdc.find_quote(text, "Second paragraph")
    r = browser.post("/_/comment", {"doc": DOC, "op": "add", "hash": md_hash(text), "block": blk,
                                    "start": s, "end": e, "quote": "Second paragraph",
                                    "body": "Fix this.", "tell": True})
    got = r.json()
    assert got["ok"] is True and got["tellError"] == NO_AGENT and got["telling"] == []
    assert thread(plan).body == "Fix this." and hub.entry(DOC).live.waiting() == []


def test_a_reply_sent_with_tell_delivers_and_waits(browser, hub, ready, session):
    text = ready.read_text(encoding="utf-8")
    r = browser.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "hash": md_hash(text),
                                    "body": "Do it now.", "tell": True})
    assert r.json()["telling"] == ["c1"]
    finish(hub)
    assert "Do it now." in json.loads(session.peer.wait_for(1)[0])["message"]["content"]


def test_a_tell_on_a_thread_that_is_being_told_is_refused_and_delivers_nothing_twice(
        browser, hub, ready, session):
    """A double click must not deliver the message twice."""
    FakeClaude(session.claude.dir, answer="sent", sleep=30)
    session.record(peerProtocol=2)
    assert post(browser, "/_/tell").status == 200
    assert wait_until(lambda: session.claude.calls() != [])
    r = post(browser, "/_/tell")
    assert r.status == 409 and r.json()["error"] == "Cosima is already being told about this comment"
    assert len(session.claude.calls()) == 1
    assert hub.entry(DOC).live.waiting() == ["c1"]            # the wait the first one began stays


def test_a_reply_sent_with_tell_on_a_thread_that_is_being_told_is_written_and_leaves_the_wait(
        browser, hub, ready, session):
    """The reply is kept (the page's form is gone once it is sent), the second Tell is refused as
    /_/tell refuses it, and the wait the first one began stays as it is (SPEC 11.3)."""
    FakeClaude(session.claude.dir, answer="sent", sleep=30)
    session.record(peerProtocol=2)
    assert post(browser, "/_/tell").status == 200
    assert wait_until(lambda: session.claude.calls() != [])
    text = ready.read_text(encoding="utf-8")
    r = browser.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "hash": md_hash(text),
                                    "body": "And this too.", "tell": True})
    got = r.json()
    assert got["ok"] is True and got["tellError"] == "Cosima is already being told about this comment"
    assert got["telling"] == ["c1"]
    assert [r.text for r in thread(ready).replies][-1] == "And this too."
    assert len(session.claude.calls()) == 1
    assert hub.entry(DOC).live.waiting() == ["c1"]            # the wait the first one began stays


def test_a_second_tell_goes_out_once_the_first_is_over(browser, hub, ready, session):
    assert post(browser, "/_/tell").status == 200
    finish(hub)
    assert post(browser, "/_/tell").status == 200
    finish(hub)
    assert len(session.peer.wait_for(2)) == 2


# ── Ask and Tell name their thread by id, in the text the page holds (SPEC 7.3) ──

@pytest.mark.parametrize("route", ["/_/ask", "/_/tell"])
def test_an_ask_or_a_tell_from_a_page_whose_version_the_document_does_not_know_is_refused(
        browser, hub, ready, session, route):
    """In a text the document never handed out (another folder's file took the address, or the
    version aged out) the id may name another thread: its answer would go there, or the session
    would be told of it. Nothing starts and nothing waits."""
    kept = ready.read_text(encoding="utf-8")
    r = post(browser, route, hash=md_hash("A text this document never handed out.\n"))
    assert r.status == 409, r.json()
    assert r.json()["error"] == ("the .md changed on disk and this page's version is no longer known to "
                                 "the hub, so this comment may not be the one on the page. Reload the page")
    finish(hub)
    assert session.claude.calls() == [] and session.peer.messages == []
    assert hub.runner.active("ask") == [] and hub.entry(DOC).live.waiting() == []
    assert ready.read_text(encoding="utf-8") == kept


@pytest.mark.parametrize("which", ["current", "older", "none"])
@pytest.mark.parametrize("route", ["/_/ask", "/_/tell"])
def test_an_ask_or_a_tell_from_the_current_version_an_older_known_one_or_none_starts(
        browser, hub, ready, session, route, which):
    """An older version the document knows still names its threads: the page and an agent both
    writing in one document stays allowed. A request with no hash is not checked."""
    held = hub.entry(DOC).live.snapshot()["hash"]
    if which == "older":
        update_file(ready, lambda t: t + "\nA paragraph from outside.\n")
        assert md_hash(ready.read_text(encoding="utf-8")) != held
    r = post(browser, route, **({} if which == "none" else {"hash": held}))
    assert r.status == 200, r.json()
    finish(hub)
    if route == "/_/ask":
        assert len(session.claude.calls()) == 1
    else:
        assert len(session.peer.wait_for(1)) == 1


# More writes than the hub keeps versions of, in memory and on disk (SPEC 7.4).
MANY = max(live.VERSIONS, state.VERSIONS_KEPT) + 1


@pytest.mark.parametrize("pinned", [True, False], ids=["pinned", "not-pinned"])
@pytest.mark.parametrize("route", ["/_/ask", "/_/tell"])
def test_an_ask_or_a_tell_from_a_page_that_pinned_its_version_starts_after_more_writes_than_the_hub_keeps(
        browser, hub, ready, session, route, pinned):
    """The page keeps its version while a form holds the reload a change needs, and pins it (SPEC 7.4): an
    Ask or a Tell sent with it starts however much was written meanwhile. Unpinned, that version goes with
    the oldest, and the request is refused as before."""
    e = hub.entry(DOC)
    e.live.refresh()
    held, pin = e.live.snapshot()["hash"], None
    writes_from_outside(ready, e.live, 1)
    if pinned:
        pin = browser.post("/_/pin", {"doc": DOC, "hash": held})
    writes_from_outside(ready, e.live, MANY)
    r = post(browser, route, hash=held)
    finish(hub)
    if not pinned:
        assert r.status == 409 and session.claude.calls() == [] and session.peer.messages == []
        return
    assert r.status == 200, r.json()
    if route == "/_/ask":
        assert len(session.claude.calls()) == 1
    else:
        assert len(session.peer.wait_for(1)) == 1
    assert pin.status == 200


@pytest.mark.parametrize("pinned", [True, False], ids=["pinned", "not-pinned"])
@pytest.mark.parametrize("what", ["reply", "ask", "tell"])
def test_a_reply_an_ask_or_a_tell_from_a_page_that_pinned_its_version_is_taken_after_a_restart_and_more_writes(
        browser, hub, ready, session, clock, what, pinned):
    """The pins are on disk too (SPEC 7.4): a page that held its reload through a restart of the hub (10.7)
    still replies, asks and tells with its version. Unpinned, the hub that comes back knows only the newest
    on disk, and the request is refused as before."""
    e = hub.entry(DOC)
    e.live.refresh()
    held, pin = e.live.snapshot()["hash"], None
    writes_from_outside(ready, e.live, 1)
    if pinned:
        pin = browser.post("/_/pin", {"doc": DOC, "hash": held})
    writes_from_outside(ready, e.live, MANY)
    fresh = Hub(port=27419, key=paths.ensure_key(), started_by="test", clock=clock)     # the hub restarts
    again = browser_on(fresh)
    try:
        if what == "reply":
            r = again.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "hash": held, "body": "Because."})
        else:
            r = post(again, f"/_/{what}", hash=held)
        finish(fresh)
        assert r.status == (200 if pinned else 409), r.json()
        if what == "reply":
            assert [x.text for x in thread(ready).replies] == (["Because."] if pinned else [])
        elif what == "ask":
            assert len(session.claude.calls()) == (1 if pinned else 0)
        elif pinned:
            assert len(session.peer.wait_for(1)) == 1
        else:
            assert session.peer.messages == []
        assert pin is None or pin.status == 200
    finally:
        fresh.runner.kill_all()
        fresh.runner.join(10)


@pytest.mark.parametrize("route", ["/_/ask", "/_/tell"])
def test_a_page_of_a_forgotten_root_cannot_ask_or_tell_a_thread_of_the_folder_that_takes_the_name(
        browser, hub, ready, session, tmp_path, route):
    """The folder that takes the name has a c1 of its own, rendered from the same session. The old
    page's Ask would write its answer there, its Tell would hand that thread to the session."""
    old_hash = md_hash(ready.read_text(encoding="utf-8"))
    assert hub.forget_root("work").name == "work"
    new = tmp_path / "y" / "work" / "plan.md"
    new.parent.mkdir(parents=True)
    new.write_text(PLAN + "\nThe new document.\n", encoding="utf-8")
    assert attach(browser, new, session.target()).json()["doc"] == DOC
    comment(new, body="The new question.")
    kept = new.read_text(encoding="utf-8")
    assert post(browser, route, hash=old_hash).status == 409
    finish(hub)
    assert session.claude.calls() == [] and session.peer.messages == []
    assert new.read_text(encoding="utf-8") == kept
    assert post(browser, route, hash=md_hash(kept)).status == 200      # the new document's own page
    finish(hub)


@pytest.mark.parametrize("route", ["/_/ask", "/_/tell"])
def test_an_ask_or_a_tell_is_checked_on_the_document_it_starts_on(
        browser, hub, ready, session, tmp_path, monkeypatch, route):
    """The route finds the document, and the job looks it up again when it starts. A forget in
    between, and another folder that takes the name: the version is checked on the document the job
    then runs on, never on the one it was found as."""
    old_hash = md_hash(ready.read_text(encoding="utf-8"))
    new = tmp_path / "y" / "work" / "plan.md"
    new.parent.mkdir(parents=True)
    new.write_text(PLAN + "\nThe new document.\n", encoding="utf-8")
    comment(new, body="The new question.")
    kept = new.read_text(encoding="utf-8")
    asked = at_the_jobs_own_look(monkeypatch, hub, forgotten_and_taken(browser, hub, new, session))
    assert post(browser, route, hash=old_hash).status == 409
    finish(hub)
    assert len(asked) == 2
    assert session.claude.calls() == [] and session.peer.messages == []
    assert new.read_text(encoding="utf-8") == kept


@pytest.mark.parametrize("op", ["add", "reply"])
@pytest.mark.parametrize("button", ["ask", "tell"])
def test_a_comment_sent_with_ask_or_tell_starts_its_job_only_on_the_text_it_was_written_in(
        browser, hub, ready, session, tmp_path, monkeypatch, button, op):
    """The comment route writes the comment, and the job looks the document up again when it starts. A
    forget in between, and another folder that takes the name: the job would run on that folder's
    thread of the same id (c1 for the reply, c2 for the new comment), which the comment was never
    written in. The comment stays written; the job is refused as an Ask or a Tell from a version the
    document does not know is."""
    new = tmp_path / "y" / "work" / "plan.md"
    new.parent.mkdir(parents=True)
    new.write_text(PLAN + "\nThe new document.\n", encoding="utf-8")
    comment(new, body="The new question.")
    comment(new, quote="First paragraph", body="Another new question.")
    kept = new.read_text(encoding="utf-8")
    asked = at_the_jobs_own_look(monkeypatch, hub, forgotten_and_taken(browser, hub, new, session))
    text = ready.read_text(encoding="utf-8")
    if op == "reply":
        fields = {"id": "c1"}
    else:
        blk, start, end = rdc.find_quote(text, "First paragraph")
        fields = {"block": blk, "start": start, "end": end, "quote": "First paragraph"}
    r = browser.post("/_/comment", {"doc": DOC, "op": op, "hash": md_hash(text), "body": "And plums?",
                                    button: True, **fields})
    got = r.json()
    assert r.status == 200 and got["id"] == ("c1" if op == "reply" else "c2") and len(asked) == 2, got
    assert got[f"{button}Error"] == ("the .md changed on disk and this page's version is no longer known to "
                                     "the hub, so this comment may not be the one on the page. Reload the page")
    finish(hub)
    assert session.claude.calls() == [] and session.peer.messages == []
    assert new.read_text(encoding="utf-8") == kept
    written = thread(ready, got["id"])
    assert (written.replies[-1].text if op == "reply" else written.body) == "And plums?"
    assert got.get("telling", []) == [] and hub.entry(DOC).live.waiting() == []


@pytest.mark.parametrize("button", ["ask", "tell"])
def test_a_comment_sent_with_ask_or_tell_still_starts_when_the_file_moved_before_the_job_did(
        browser, hub, ready, session, monkeypatch, button):
    """The control: a write from outside between the comment and the job's start leaves the text the
    comment was written in a version the document knows, so the job starts."""
    asked = at_the_jobs_own_look(monkeypatch, hub,
                                 lambda: update_file(ready, lambda t: t + "\nA paragraph from outside.\n"))
    text = ready.read_text(encoding="utf-8")
    got = browser.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "hash": md_hash(text),
                                      "body": "And plums?", button: True}).json()
    assert got["ok"] is True and f"{button}Error" not in got and len(asked) == 2, got
    assert md_hash(ready.read_text(encoding="utf-8")) != got["hash"]
    finish(hub)
    if button == "ask":
        assert len(session.claude.calls()) == 1
    else:
        assert len(session.peer.wait_for(1)) == 1


@pytest.mark.parametrize("op", ["add", "reply"])
@pytest.mark.parametrize("button", ["ask", "tell"])
def test_a_comment_sent_with_ask_or_tell_whose_root_is_forgotten_before_the_job_starts_is_answered(
        browser, hub, ready, session, monkeypatch, button, op):
    """The comment route writes the comment, and the job looks the document up again when it starts. A
    forget in between, and no folder that takes the name: the job finds no document. The comment was
    written, so the route answers 200 with the refusal in askError or tellError, as it does for a text
    the document does not know, and the wait the Tell began is ended."""
    def forget():
        assert hub.forget_root("work").name == "work"
    asked = at_the_jobs_own_look(monkeypatch, hub, forget)
    text = ready.read_text(encoding="utf-8")
    if op == "reply":
        fields = {"id": "c1"}
    else:
        blk, start, end = rdc.find_quote(text, "First paragraph")
        fields = {"block": blk, "start": start, "end": end, "quote": "First paragraph"}
    r = browser.post("/_/comment", {"doc": DOC, "op": op, "hash": md_hash(text), "body": "And plums?",
                                    button: True, **fields})
    got = r.json()
    assert r.status == 200 and got["id"] == ("c1" if op == "reply" else "c2") and len(asked) == 2, got
    assert got[f"{button}Error"] == GONE
    assert hub.roots.get("work") is None
    finish(hub)
    assert session.claude.calls() == [] and session.peer.messages == []
    written = thread(ready, got["id"])
    assert (written.replies[-1].text if op == "reply" else written.body) == "And plums?"
    assert got.get("telling", []) == []


@pytest.mark.parametrize("gone", ["forgotten", "deleted"])
@pytest.mark.parametrize("route", ["/_/ask", "/_/tell"])
def test_an_ask_or_a_tell_whose_document_goes_before_the_job_starts_is_refused_as_one_not_there(
        browser, hub, ready, session, monkeypatch, route, gone):
    """The route finds the document, and the job looks it up again when it starts. Its root forgotten in
    between with no folder that takes the name, or its file deleted: the job finds no document, and the
    request is refused with 404, as one for a document that is not there, not as a failure of the hub."""
    held = md_hash(ready.read_text(encoding="utf-8"))

    def go():
        if gone == "forgotten":
            assert hub.forget_root("work").name == "work"
        else:
            ready.unlink()
    asked = at_the_jobs_own_look(monkeypatch, hub, go)
    r = post(browser, route, hash=held)
    assert (r.status, r.json()) == (404, {"ok": False, "error": GONE}) and len(asked) == 2
    finish(hub)
    assert session.claude.calls() == [] and session.peer.messages == []


@pytest.mark.parametrize("route", ["/_/ask", "/_/tell"])
def test_an_ask_or_a_tell_admitted_after_a_forget_that_came_between_its_look_and_its_start_is_refused(
        browser, hub, ready, session, monkeypatch, route):
    """The job holds its entry and is about to be admitted; the root is forgotten right there, and the forget's
    cancel finds no job yet. The job must not start after it: it would run on a document that is gone,
    after Cancel answered ok."""
    held = md_hash(ready.read_text(encoding="utf-8"))
    sub = tab(hub)
    sub.drain()
    real, forgotten = hub.asktell._thread, []

    def forgotten_after(e, cid):          # the last look before the job is admitted
        found = real(e, cid)
        forgotten.append(hub.forget_root("work").name)
        return found
    monkeypatch.setattr(hub.asktell, "_thread", forgotten_after)
    r = post(browser, route, hash=held)
    assert forgotten == ["work"]
    assert (r.status, r.json()) == (404, {"ok": False, "error": GONE})
    finish(hub)
    assert wait_until(lambda: not hub.runner.running("ask", DOC, "c1")
                      and not hub.runner.running("tell", DOC, "c1"))
    assert hub.runner.active("ask") == [] and hub.runner.active("tell") == []
    assert session.claude.calls() == [] and session.peer.messages == []
    heard = events(sub)
    assert [n for n, _ in heard if n != "gone"] == [], heard


@pytest.mark.parametrize("route", ["/_/ask", "/_/tell"])
def test_a_job_registered_when_a_forget_comes_is_refused_and_its_work_never_runs(
        browser, hub, ready, session, monkeypatch, route):
    """The forget comes after the job is registered and before the entry is looked at: its cancel finds
    the job, the look finds the entry gone, and the job is held back from its work either way."""
    held = md_hash(ready.read_text(encoding="utf-8"))
    sub = tab(hub)
    sub.drain()
    real, forgotten = hub.asktell._is_current, []

    def forgotten_first(e):
        forgotten.append(hub.forget_root("work").name)
        return real(e)
    monkeypatch.setattr(hub.asktell, "_is_current", forgotten_first)
    r = post(browser, route, hash=held)
    assert forgotten == ["work"]
    assert (r.status, r.json()) == (404, {"ok": False, "error": GONE})
    finish(hub)
    assert wait_until(lambda: not hub.runner.running("ask", DOC, "c1")
                      and not hub.runner.running("tell", DOC, "c1"))
    heard = events(sub)
    assert [n for n, _ in heard if n != "gone"] == [], heard
    assert session.claude.calls() == [] and session.peer.messages == []
    assert hub.jobs()["telling"] == []


@pytest.mark.parametrize("route", ["/_/ask", "/_/tell"])
def test_a_job_whose_start_fails_after_it_was_registered_never_runs_and_is_not_left_waiting(
        browser, hub, ready, session, monkeypatch, route):
    """The job is registered, held back from its work until the entry is looked at. When the look
    raises, the job is cancelled and let go: its thread ends, and nothing runs."""
    held = md_hash(ready.read_text(encoding="utf-8"))

    def broken(e):
        raise RuntimeError("the look failed")
    monkeypatch.setattr(hub.asktell, "_is_current", broken)
    post(browser, route, hash=held)
    finish(hub)
    assert wait_until(lambda: not hub.runner.running("ask", DOC, "c1")
                      and not hub.runner.running("tell", DOC, "c1"))
    assert hub.runner.active("ask") == [] and hub.runner.active("tell") == []
    assert session.claude.calls() == [] and session.peer.messages == []
    assert hub.jobs()["telling"] == []


@pytest.mark.parametrize("what", ["ask", "tell"])
def test_a_forget_of_a_root_the_registry_no_longer_holds_still_cancels_the_jobs_of_its_entries(
        hub, ready, what):
    """Another process forgot the root and this hub reloaded roots.json: the entries are still here, the
    root is not, and the forget pops the entries all the same, so it cancels their jobs too."""
    hub.entry(DOC)
    assert hub.roots.forget("work") is not None          # the registry alone: the entries stay
    stopped = threading.Event()

    def work(job):
        while not job.cancelled:
            time.sleep(0.01)
        stopped.set()
    assert hub.runner.start(what, DOC, "c1", work) is not None
    assert hub.forget_root("work") is None
    assert stopped.wait(5)


# ── Cancel a Tell ────────────────────────────────────────────────────────────

def test_cancelling_a_tell_already_sent_ends_the_wait_and_tells_the_session_to_stop(
        browser, hub, ready, session):
    sub = tab(hub)
    sub.drain()
    post(browser, "/_/tell")
    finish(hub)
    events(sub)
    r = post(browser, "/_/cancel", what="tell")
    assert r.json() == {"ok": True}
    finish(hub)
    assert events(sub) == [("tell-cancelled", {"id": "c1", "sent": True})]
    assert hub.entry(DOC).live.waiting() == []
    msgs = _arrived(hub, session.peer, 2)
    assert json.loads(msgs[1])["message"]["content"].split(">\n", 1)[1].startswith(
        prompts.cancel(DOC, "Ada", "c1"))


def test_finish_names_a_job_that_outlives_it_instead_of_returning(hub):
    release = threading.Event()
    hub.runner.start("stop", DOC, "c1", lambda job: release.wait(10))
    try:
        with pytest.raises(AssertionError, match=r"jobs still running 0\.05 s.*Thread"):
            finish(hub, within=0.05)
    finally:
        release.set()
    finish(hub)


def _arrived(hub, peer, n):
    """`peer.wait_for(n)`, and when too few arrive, a failure that says where the stop went: the
    hub's diagnostics (a skipped or failed stop records itself there), the jobs still on the thread
    (`finish` returns when its wait is over, ended or not), the connections the peer accepted and
    the messages it holds."""
    try:
        return peer.wait_for(n)
    except AssertionError as ex:
        rows = [(r["kind"], {k: v for k, v in r.items() if k not in ("at", "source", "kind", "pid", "session")})
                for r in diagnostics.read()]
        raise AssertionError(f"{ex}; connections accepted {peer.accepted}; "
                             f"messages {[m[:120] for m in peer.messages]}; "
                             f"jobs still there {[(k, len(hub.runner.worker_threads(k, DOC, 'c1'))) for k in ('tell', 'stop')]}; "
                             f"diagnostics {rows}") from None


def test_cancelling_a_delivery_still_running_kills_it_and_sends_the_stop_message(
        browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="sent", sleep=30)
    session.record(peerProtocol=2)
    sub = tab(hub)
    sub.drain()
    post(browser, "/_/tell")
    assert wait_until(lambda: session.claude.calls() != [])
    first = session.claude.calls()[0]["pid"]
    r = post(browser, "/_/cancel", what="tell")
    assert r.json() == {"ok": True}
    assert wait_until(lambda: ended(first))
    names = [n for n, _ in events(sub)]
    assert names == ["tell-cancelled"]                         # not "sent", not "failed"
    assert hub.entry(DOC).live.waiting() == []
    assert wait_until(lambda: len(session.claude.calls()) == 2
                      and session.claude.calls()[1]["stdin"])     # the stop went by the courier too
    assert "pressed Cancel on comment c1" in session.claude.calls()[1]["stdin"]


class SlowDelivery:
    """An adapter whose delivery takes as long as the test says and cannot be cancelled by the
    runner (a push on a socket is no child), and which writes down what it was asked to do."""
    agent, display, product, implemented = "claude-code", "Claude", "Claude Code", True

    def __init__(self):
        self.log, self.release = [], threading.Event()

    def capabilities(self, t):
        return frozenset({"deliver", "stop", "state"})

    def child_env(self, t):
        return None

    def state(self, t):
        return State("idle")

    def deliver(self, t, text, run):
        self.log.append("deliver-start")
        self.release.wait(10)
        self.log.append("deliver-end")

    def stop(self, t, text, run):
        self.log.append("stop")


def test_the_stop_message_goes_out_only_after_the_delivery_it_cancels_has_ended(
        browser, hub, ready, session, monkeypatch):
    slow = SlowDelivery()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    post(browser, "/_/tell")
    assert wait_until(lambda: slow.log == ["deliver-start"])
    assert post(browser, "/_/cancel", what="tell").json() == {"ok": True}
    time.sleep(0.3)
    assert slow.log == ["deliver-start"]                      # the stop waits for the Tell
    slow.release.set()
    finish(hub)
    assert slow.log == ["deliver-start", "deliver-end", "stop"]


def test_a_tell_cancelled_before_its_delivery_starts_delivers_nothing(
        browser, hub, ready, session, monkeypatch):
    slow = SlowDelivery()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    start = hub.runner.start

    def cancelled_first(kind, address, cid, work, on_error=None):
        if kind != "tell":
            return start(kind, address, cid, work, on_error)

        def first_cancel(job):
            job.cancel()
            work(job)
        return start(kind, address, cid, first_cancel, on_error)
    monkeypatch.setattr(hub.runner, "start", cancelled_first)
    sub = tab(hub)
    sub.drain()
    post(browser, "/_/tell")
    slow.release.set()
    finish(hub)
    assert "deliver-start" not in slow.log
    assert "tell-sent" not in [n for n, _ in events(sub)]


def test_cancelling_a_tell_that_is_over_is_a_quiet_ok(browser, hub, ready, session):
    sub = tab(hub)
    sub.drain()
    assert post(browser, "/_/cancel", what="tell").json() == {"ok": True}
    assert events(sub) == [] and session.peer.data == b""


@pytest.mark.parametrize("what", ["ask", "tell"])
def test_a_cancel_after_the_root_was_forgotten_is_a_quiet_ok(browser, hub, ready, what):
    assert hub.forget_root("work").name == "work"
    assert post(browser, "/_/cancel", what=what).json() == {"ok": True}


@pytest.mark.parametrize("what", ["ask", "tell"])
def test_a_cancel_that_a_forget_overtakes_answers_ok_and_not_500(
        browser, hub, ready, monkeypatch, what):
    """The root is forgotten after the request was read and before the cancel looks at the
    document: the cancel finds nothing to clear."""
    real, forgotten = hub.asktell.cancel, []

    def forgotten_first(address, cid, kind):
        forgotten.append(hub.forget_root("work").name)
        return real(address, cid, kind)
    monkeypatch.setattr(hub.asktell, "cancel", forgotten_first)
    assert post(browser, "/_/cancel", what=what).json() == {"ok": True}
    assert forgotten == ["work"]


@pytest.mark.parametrize("what", ["ask", "tell"])
def test_a_cancel_stops_a_job_that_started_on_an_entry_a_forget_had_taken(
        browser, hub, ready, what):
    """A job that was admitted just before a forget runs on after it, on the entry it held."""
    assert hub.forget_root("work").name == "work"
    stopped = threading.Event()

    def work(job):
        while not job.cancelled:
            time.sleep(0.01)
        stopped.set()
    assert hub.runner.start(what, DOC, "c1", work) is not None
    assert post(browser, "/_/cancel", what=what).json() == {"ok": True}
    assert stopped.wait(5)


def test_a_cancel_of_an_ask_on_a_file_that_has_gone_still_stops_it(browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="partial", sleep=30)
    post(browser, "/_/ask")
    assert wait_until(lambda: session.claude.calls() != [])
    pid = session.claude.calls()[0]["pid"]
    ready.unlink()
    assert post(browser, "/_/cancel", what="ask").json() == {"ok": True}
    finish(hub)
    assert ended(pid) and hub.runner.active("ask") == []


def test_a_cancel_of_a_delivery_on_a_file_that_has_gone_still_stops_it(
        browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="sent", sleep=30)
    session.record(peerProtocol=2)
    post(browser, "/_/tell")
    assert wait_until(lambda: session.claude.calls() != [])
    pid = session.claude.calls()[0]["pid"]
    ready.unlink()
    assert post(browser, "/_/cancel", what="tell").json() == {"ok": True}
    assert wait_until(lambda: ended(pid))
    # The Tell's job has ended; the stop job is left running on purpose: its courier is the 30 s
    # FakeClaude, and the stop message is the next test's business, not this one's.
    assert wait_until(lambda: not hub.runner.worker_threads("tell", DOC, "c1"))
    assert hub.runner.active("tell") == []


# ── a Tell goes only where the document's render put it ──────────────────────

def test_a_request_cannot_name_another_target_or_socket(browser, hub, ready, session, short_tmp):
    evil = Peer(os.path.join(short_tmp, "evil.sock"))
    try:
        r = post(browser, "/_/tell", socket=evil.path, target={"agent": "claude-code",
                                                                "socket": evil.path},
                 session="s-evil", bin="/bin/true")
        assert r.status == 200
        finish(hub)
        assert len(session.peer.wait_for(1)) == 1 and evil.data == b""
    finally:
        evil.close()


@pytest.fixture
def sleeper():
    """A second live process, standing for a second session."""
    p = subprocess.Popen(["sleep", "60"])
    yield p
    p.kill()
    p.wait()


def test_two_documents_push_each_to_its_own_session(browser, hub, ready, session, work, cfg,
                                                    short_tmp, sleeper):
    other = work / "other.md"
    other.write_text(PLAN, encoding="utf-8")
    hub.roots.for_document(other)
    second = Peer(os.path.join(short_tmp, "second.sock"))
    try:
        write_record(cfg, sleeper.pid, sessionId="s-2", name="Oriel", messagingSocketPath=second.path)
        attach(browser, other, session.target(session="s-2", pid=sleeper.pid, socket=second.path,
                                              name="Oriel", proc_start=proc_start(sleeper.pid)))
        update_file(other, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "Second paragraph"),
                                                     "Second paragraph", "Why?", "Ada",
                                                     "2026-10-14T10:00")[0])
        assert browser.post("/_/tell", {"doc": "work/other.md", "id": "c1"}).status == 200
        finish(hub)
        assert len(second.wait_for(1)) == 1 and session.peer.data == b""
        assert post(browser, "/_/tell").status == 200
        finish(hub)
        assert len(session.peer.wait_for(1)) == 1 and len(second.messages) == 1
    finally:
        second.close()


def test_a_pid_another_session_took_never_receives_the_tell(browser, hub, ready, session):
    """The session the page was rendered from has ended and its pid went to another session,
    whose record holds another id, another start and its own socket."""
    other = Peer(session.peer.path + ".other")
    try:
        write_record(session.cfg, PID, sessionId="s-someone-else", procStart=proc_start(PID),
                     messagingSocketPath=other.path)
        attach(browser, ready, session.target(proc_start="999999", socket=""))
        r = post(browser, "/_/tell")
        assert r.status == 409
        assert other.data == b"" and session.peer.data == b""
    finally:
        other.close()


# ── stopping ─────────────────────────────────────────────────────────────────

def test_stopping_the_hub_kills_the_asks_in_flight(browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="x", sleep=30)
    post(browser, "/_/ask")
    assert wait_until(lambda: session.claude.calls() != [])
    pid = session.claude.calls()[0]["pid"]
    hub.stop_jobs()
    assert wait_until(lambda: ended(pid))


# ── an upgrade stop waits for the jobs, and no job starts under one (SPEC 8.4) ──

def upgrade(browser, **body):
    return browser.post("/_/stop", {"reason": "upgrade", **body}, cookie=False, key=True)


def test_an_upgrade_stop_is_refused_while_an_ask_runs_and_the_ask_goes_on(browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="x", sleep=30)
    post(browser, "/_/ask")
    assert wait_until(lambda: session.claude.calls() != [])
    r = upgrade(browser)
    assert r.status == 409 and r.json()["ok"] is False and "Ask or Tell" in r.json()["error"]
    assert hub.stop_requested is None
    assert hub.runner.active("ask") == [[DOC, "c1"]] and not ended(session.claude.calls()[0]["pid"])
    post(browser, "/_/cancel", what="ask")
    finish(hub)
    assert upgrade(browser).status == 200 and hub.stop_requested == "upgrade"


def test_an_upgrade_stop_is_refused_while_a_tell_waits_for_its_reply(browser, hub, ready, session):
    assert hub.entry(DOC).live.await_reply("c1")
    r = upgrade(browser)
    assert r.status == 409 and hub.stop_requested is None
    assert upgrade(browser, force=True).status == 200


def test_an_upgrade_stop_with_nothing_running_is_taken(browser, hub, ready):
    r = upgrade(browser)
    assert r.status == 200 and hub.stop_requested == "upgrade"


def test_sheaf_restart_may_force_an_upgrade_stop_and_a_plain_stop_never_waits(
        browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="x", sleep=30)
    post(browser, "/_/ask")
    assert wait_until(lambda: session.claude.calls() != [])
    assert upgrade(browser, force=True).status == 200 and hub.stop_requested == "upgrade"
    hub.stop_requested = None
    assert browser.post("/_/stop", {"reason": "stop"}, cookie=False, key=True).status == 200
    assert hub.stop_requested == "stop"


def test_force_must_be_true_or_false(browser, hub, ready):
    assert upgrade(browser, force="yes").status == 400 and hub.stop_requested is None


def test_no_ask_or_tell_starts_once_an_upgrade_stop_is_taken(browser, hub, ready, session):
    assert upgrade(browser).status == 200
    ask, tell = post(browser, "/_/ask"), post(browser, "/_/tell")
    assert ask.status == 409 and tell.status == 409
    assert "restarting for an upgrade" in ask.json()["error"]
    assert hub.entry(DOC).live.waiting() == [] and hub.runner.active("ask") == []
    finish(hub)
    assert session.claude.calls() == []
    r = browser.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "body": "Because.",
                                    "base": md_hash(ready.read_text(encoding="utf-8")), "tell": True})
    assert hub.entry(DOC).live.waiting() == []               # a Tell wait it began is cleared again
    assert r.json().get("tellError") and "restarting for an upgrade" in r.json()["tellError"]


def test_an_ask_that_starts_while_an_upgrade_stop_is_being_admitted_is_refused_not_killed(
        browser, hub, ready, session):
    FakeClaude(session.claude.dir, answer="x", sleep=30)
    real = hub.jobs
    looked, go = threading.Event(), threading.Event()

    def jobs():                          # the idle check has its answer, and holds it until `go`
        out = real()
        looked.set()
        assert go.wait(10)
        return out
    hub.jobs = jobs
    got = {}
    stopper = threading.Thread(target=lambda: got.update(stop=upgrade(browser)))
    stopper.start()
    assert looked.wait(10)
    asker = threading.Thread(target=lambda: got.update(ask=post(browser, "/_/ask")))
    asker.start()
    go.set()
    stopper.join(10)
    asker.join(10)
    assert got["stop"].status == 200 and got["ask"].status == 409
    finish(hub)
    assert session.claude.calls() == [] and hub.runner.active("ask") == []


def test_a_second_tell_that_loses_the_race_to_start_is_refused_and_leaves_the_wait_of_the_first(
        browser, hub, ready, session):
    """Both checks of `start_tell` (the thread is being told; an upgrade stop was taken) meet
    here: two Tells pass the first check together, the runner takes one and answers None to the
    other. That one is a 409 and does not clear the wait, which the first one began and owns;
    only a refusal by the upgrade stop clears the wait its own Tell began."""
    session.record(peerProtocol=2)
    assert hub.entry(DOC).live.await_reply("c1")              # the first Tell's wait
    hub.runner.start = lambda *a, **k: None                   # the first Tell's job is the runner's
    r = post(browser, "/_/tell")
    assert r.status == 409 and r.json()["error"] == "Cosima is already being told about this comment"
    assert hub.entry(DOC).live.waiting() == ["c1"]


# ── what an upgrade stop counts as running: every delivery and every stop message ──

def end_the_wait(hub, ready, clock, how):
    """End the Tell's wait while its delivery still runs: by the clock, or by a reply with the
    role `action` that lands first."""
    if how == "expired":
        clock.t += hub.tell_wait + 1
    else:
        update_file(ready, lambda t: rdc.reply(t, "c1", "Done.", "Claude", "2026-10-14T10:05",
                                               role="action"))
    hub.tick()
    assert hub.entry(DOC).live.waiting() == []


@pytest.mark.parametrize("how", ["expired", "answered"])
def test_an_upgrade_stop_is_refused_while_a_delivery_runs_whose_wait_has_ended(
        browser, hub, ready, session, clock, monkeypatch, how):
    slow = SlowDelivery()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    post(browser, "/_/tell")
    assert wait_until(lambda: slow.log == ["deliver-start"])
    end_the_wait(hub, ready, clock, how)
    r = upgrade(browser)
    assert r.status == 409 and "Ask or Tell" in r.json()["error"]
    assert hub.stop_requested is None and not hub.upgrading
    slow.release.set()
    finish(hub)
    assert slow.log == ["deliver-start", "deliver-end"]
    assert upgrade(browser).status == 200 and hub.stop_requested == "upgrade"


@pytest.mark.parametrize("how", ["expired", "answered"])
def test_sheaf_restart_still_forces_an_upgrade_stop_over_a_delivery_whose_wait_has_ended(
        browser, hub, ready, session, clock, monkeypatch, how):
    slow = SlowDelivery()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    post(browser, "/_/tell")
    assert wait_until(lambda: slow.log == ["deliver-start"])
    end_the_wait(hub, ready, clock, how)
    assert upgrade(browser, force=True).status == 200 and hub.stop_requested == "upgrade"
    slow.release.set()


def test_an_upgrade_stop_is_refused_while_a_stop_message_waits_for_its_delivery(
        browser, hub, ready, session, monkeypatch):
    slow = SlowDelivery()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    post(browser, "/_/tell")
    assert wait_until(lambda: slow.log == ["deliver-start"])
    assert post(browser, "/_/cancel", what="tell").json() == {"ok": True}
    assert hub.jobs() == {"asking": [], "telling": []}        # what GET /_/jobs lists is as it was
    assert hub.runner.active("stop") == [[DOC, "c1"]]
    r = upgrade(browser)
    assert r.status == 409 and hub.stop_requested is None and not hub.upgrading
    slow.release.set()
    finish(hub)
    assert slow.log == ["deliver-start", "deliver-end", "stop"]   # the stop message went out
    assert upgrade(browser).status == 200 and hub.stop_requested == "upgrade"


def test_a_plain_stop_never_waits_for_a_stop_message(browser, hub, ready, session, monkeypatch):
    slow = SlowDelivery()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    post(browser, "/_/tell")
    assert wait_until(lambda: slow.log == ["deliver-start"])
    post(browser, "/_/cancel", what="tell")
    assert browser.post("/_/stop", {"reason": "stop"}, cookie=False, key=True).status == 200
    assert hub.stop_requested == "stop"
    slow.release.set()


def test_an_upgrade_stop_that_comes_while_a_tell_is_being_cancelled_waits_for_its_stop_message(
        browser, hub, ready, session, monkeypatch):
    """Cancel ends the delivery's job and its wait, then starts the stop message: an upgrade stop
    that looks in between must not find the hub idle."""
    slow = SlowDelivery()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    start = hub.runner.start
    reached, go = threading.Event(), threading.Event()

    def held_stop(kind, address, cid, work, on_error=None):
        if kind == "stop":
            reached.set()
            assert go.wait(10)
        return start(kind, address, cid, work, on_error)
    monkeypatch.setattr(hub.runner, "start", held_stop)
    post(browser, "/_/tell")
    assert wait_until(lambda: slow.log == ["deliver-start"])
    got = {}
    canceller = threading.Thread(target=lambda: got.update(cancel=post(browser, "/_/cancel",
                                                                       what="tell")))
    canceller.start()
    assert reached.wait(10)
    stopper = threading.Thread(target=lambda: got.update(stop=upgrade(browser)))
    stopper.start()
    stopper.join(0.5)
    go.set()
    canceller.join(10)
    stopper.join(10)
    assert got["cancel"].json() == {"ok": True}
    assert got["stop"].status == 409 and hub.stop_requested is None
    slow.release.set()
    finish(hub)
    assert slow.log == ["deliver-start", "deliver-end", "stop"]


def test_cancelling_a_tell_looks_the_session_up_without_the_admission_lock(
        browser, hub, ready, session, monkeypatch):
    """The look at the session reads files and asks the adapter, which can be slow; every Ask and
    Tell start, every upgrade stop and the signal handler wait on the admission lock."""
    slow = SlowDelivery()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    real, free = hub.asktell.view, []

    def can_admit():
        got = []

        def probe():
            got.append(hub.admit.acquire(timeout=1))
            if got[0]:
                hub.admit.release()
        other = threading.Thread(target=probe)
        other.start()
        other.join()
        return got[0]

    def view(address):
        free.append(can_admit())
        return real(address)
    post(browser, "/_/tell")
    assert wait_until(lambda: slow.log == ["deliver-start"])
    monkeypatch.setattr(hub.asktell, "view", view)
    assert post(browser, "/_/cancel", what="tell").json() == {"ok": True}
    assert free and all(free)
    slow.release.set()
    finish(hub)


# ── a cancel never makes the admission lock wait for a render ─────────────────

def stall_the_rebuild(hub, plan, monkeypatch):
    """The file changes and the watcher starts its rebuild; the render (pandoc, mmdc: up to 300 s)
    does not end until the returned event is set, and holds the document's lock meanwhile."""
    rendering, release = threading.Event(), threading.Event()

    def build(e, text):
        rendering.set()
        release.wait(30)
        return e.html
    monkeypatch.setattr(hub, "_build", build)
    update_file(plan, lambda t: t + "\nMore.\n")
    threading.Thread(target=hub.tick, daemon=True).start()
    assert rendering.wait(5)
    return release


@pytest.mark.parametrize("render", ["stalled", "idle"])
def test_cancelling_a_tell_leaves_the_admission_lock_free_while_a_render_holds_the_document(
        browser, hub, ready, session, monkeypatch, render):
    """Ending a Tell's wait takes the document's lock, which a rebuild holds across its render. Every
    Ask and Tell start, every upgrade stop and the signal handler wait on the admission lock, so a
    cancel must not sit on it meanwhile: `sheaf restart` stops the hub at once."""
    slow = SlowDelivery()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    post(browser, "/_/tell")
    assert wait_until(lambda: slow.log == ["deliver-start"])
    release = stall_the_rebuild(hub, ready, monkeypatch) if render == "stalled" else threading.Event()
    got = {}
    canceller = threading.Thread(target=lambda: got.update(cancel=post(browser, "/_/cancel",
                                                                       what="tell")), daemon=True)
    stopper = threading.Thread(target=lambda: got.update(stop=upgrade(browser, force=True)),
                               daemon=True)
    try:
        canceller.start()
        assert wait_until(lambda: hub.runner.active("tell") == [])     # the delivery is cancelled
        stopper.start()
        stopper.join(3)
        assert "stop" in got                             # taken though the render has not ended
        canceller.join(1)
        assert canceller.is_alive() == (render == "stalled")     # the wait ends with the render
    finally:
        release.set()
        canceller.join(10)
        stopper.join(10)
    assert got["stop"].status == 200 and hub.stop_requested == "upgrade"
    assert got["cancel"].json() == {"ok": True} and hub.entry(DOC).live.waiting() == []
    slow.release.set()
    finish(hub)
    assert slow.log == ["deliver-start", "deliver-end", "stop"]       # the stop message went out


@pytest.mark.parametrize("state", ["ended", "waiting"])
def test_cancelling_a_tell_looks_the_session_up_only_when_a_stop_message_is_to_go(
        browser, hub, ready, session, monkeypatch, state):
    """The look at the session reads files and asks the adapter. A Tell that has ended has nothing
    to stop, so cancelling it again is a quiet ok and asks nothing."""
    post(browser, "/_/tell")
    finish(hub)
    if state == "ended":
        post(browser, "/_/cancel", what="tell")          # its wait ends and its stop message goes out
        finish(hub)
    looked, real = [], hub.asktell.view
    monkeypatch.setattr(hub.asktell, "view", lambda address: looked.append(address) or real(address))
    assert post(browser, "/_/cancel", what="tell").json() == {"ok": True}
    finish(hub)
    assert looked == ([] if state == "ended" else [DOC])


def test_a_cancel_that_fails_leaves_no_stop_message_listed_as_on_its_way(
        browser, hub, ready, session, monkeypatch):
    """What the list of running jobs holds for the stop message must end with the cancel, or no
    upgrade stop could be taken again."""
    post(browser, "/_/tell")
    finish(hub)
    live, calls = hub.entry(DOC).live, []
    real = live.stop_waiting

    def broken_once(cid):
        calls.append(cid)
        if len(calls) == 1:
            raise RuntimeError("the document's lock failed")
        return real(cid)
    monkeypatch.setattr(live, "stop_waiting", broken_once)
    r = post(browser, "/_/cancel", what="tell")
    assert r.status == 500 and hub.runner.active("stop") == []
    assert upgrade(browser).status == 409                  # the Tell's wait is still there, nothing else
    assert post(browser, "/_/cancel", what="tell").json() == {"ok": True}
    finish(hub)
    assert upgrade(browser).status == 200


# ── a Tell is refused while the cancel of its thread is not over ───────────────

CANCELLING = "The Tell of this comment is still being cancelled. Try again when that is done."
WAIT_ENDED = ("This Tell ended before it went out: it was cancelled, answered or failed. "
              "Tell again if you still want it.")


class SlowDeliveryAsk(SlowDelivery):
    """The same, and it answers an Ask with a command that stands still until the test ends it."""

    def capabilities(self, t):
        return super().capabilities(t) | {"ask"}

    def ask_command(self, t):
        return ["sleep", "30"]


class SlowStop(SlowDelivery):
    """The same, and the stop message takes as long as the test says."""

    def __init__(self):
        super().__init__()
        self.stop_release = threading.Event()

    def stop(self, t, text, run):
        self.log.append("stop-start")
        self.stop_release.wait(10)
        self.log.append("stop-end")


def tell_by(browser, route):
    """A Tell of thread c1 by the Tell button (`"tell"`) or as a reply sent with Tell (`"comment"`)."""
    if route == "tell":
        return post(browser, "/_/tell")
    return browser.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "body": "Again.",
                                       "tell": True})


def refusal(r, route):
    """The line a Tell was refused with, as its route says it, or None."""
    return r.json().get("error" if route == "tell" else "tellError")


def told_and_over(browser, hub, slow):
    """A Tell whose delivery has ended and whose wait is still listed."""
    assert post(browser, "/_/tell").status == 200
    assert wait_until(lambda: slow.log == ["deliver-start"])
    slow.release.set()
    finish(hub)
    assert slow.log == ["deliver-start", "deliver-end"] and hub.entry(DOC).live.waiting() == ["c1"]


def hold_back_stop_waiting(live, monkeypatch):
    """The first `stop_waiting` (a cancel's) stops where it is, before it takes the document's lock,
    until the second event is set; later calls are not held back. Returns (it is there, let it go)."""
    reached, released = threading.Event(), threading.Event()
    real = live.stop_waiting

    def paused(cid):
        if not reached.is_set():
            reached.set()
            assert released.wait(10)
        return real(cid)
    monkeypatch.setattr(live, "stop_waiting", paused)
    return reached, released


def cancel_under_way(browser, hub, plan, slow, monkeypatch, held_by):
    """The cancel of that Tell, past its step under the admission lock (the delivery's job is over, the
    stop message is listed as on its way) and not yet at the end of the wait: held back by a rebuild's
    render, which holds the document's lock (`"render"`), or stopped on the way there (`"pause"`).
    Returns the function that lets it go, the cancel's thread and a dict that the requests fill with
    their answers."""
    told_and_over(browser, hub, slow)
    if held_by == "render":
        go = stall_the_rebuild(hub, plan, monkeypatch).set
    else:
        _, released = hold_back_stop_waiting(hub.entry(DOC).live, monkeypatch)
        go = released.set
    got = {}
    canceller = threading.Thread(target=lambda: got.update(cancel=post(browser, "/_/cancel",
                                                                       what="tell")), daemon=True)
    canceller.start()
    assert wait_until(lambda: hub.runner.active("stop") == [[DOC, "c1"]])
    return go, canceller, got


@pytest.mark.parametrize("held_by", ["render", "pause"])
@pytest.mark.parametrize("route", ["tell", "comment"])
def test_a_tell_is_refused_while_the_cancel_of_its_thread_is_under_way(
        browser, hub, ready, session, monkeypatch, route, held_by):
    """The cancel ends the Tell's wait after its step under the admission lock. A Tell of the same
    thread that began in between would have its wait removed by the older cancel, and the session
    would be sent a stop message for a delivery nobody cancelled."""
    slow = SlowDelivery()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    go, canceller, got = cancel_under_way(browser, hub, ready, slow, monkeypatch, held_by)
    again = threading.Thread(target=lambda: got.update(again=tell_by(browser, route)), daemon=True)
    try:
        again.start()
        again.join(3)
        if route == "tell" or held_by == "pause":   # a write waits for the render; a refusal does not
            assert "again" in got
        if route == "tell":
            assert got["again"].status == 409 and refusal(got["again"], route) == CANCELLING
    finally:
        go()
        canceller.join(10)
        again.join(10)
    if route == "comment":                          # the reply is kept, the Tell is not made
        assert refusal(got["again"], route) == CANCELLING
        assert [r.text for r in thread(ready).replies][-1] == "Again."
    assert got["cancel"].json() == {"ok": True}
    finish(hub)
    assert hub.entry(DOC).live.waiting() == []
    assert slow.log == ["deliver-start", "deliver-end", "stop"]        # nothing was delivered again


@pytest.mark.parametrize("route", ["tell", "comment"])
def test_a_tell_is_refused_until_the_stop_message_of_its_cancel_has_been_sent(
        browser, hub, ready, session, monkeypatch, route):
    """The stop message goes out as a job of its own once the cancel is done. A Tell delivered before
    it is out would be stopped by it, and the person started that Tell after cancelling."""
    slow = SlowStop()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    told_and_over(browser, hub, slow)
    assert post(browser, "/_/cancel", what="tell").json() == {"ok": True}
    assert wait_until(lambda: slow.log[-1:] == ["stop-start"])      # the cancel is over, the message is not out
    assert refusal(tell_by(browser, route), route) == CANCELLING
    slow.stop_release.set()
    finish(hub)
    assert refusal(tell_by(browser, route), route) is None
    finish(hub)
    assert slow.log == ["deliver-start", "deliver-end", "stop-start", "stop-end",
                        "deliver-start", "deliver-end"]


@pytest.mark.parametrize("route", ["tell", "comment"])
def test_a_tell_is_accepted_again_once_the_cancel_of_its_thread_is_over(
        browser, hub, ready, session, monkeypatch, route):
    slow = SlowDelivery()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    told_and_over(browser, hub, slow)
    assert post(browser, "/_/cancel", what="tell").json() == {"ok": True}
    finish(hub)
    assert slow.log == ["deliver-start", "deliver-end", "stop"] and hub.runner.active("stop") == []
    r = tell_by(browser, route)
    assert r.status == 200 and refusal(r, route) is None
    finish(hub)
    assert slow.log.count("deliver-start") == 2 and hub.entry(DOC).live.waiting() == ["c1"]


def test_an_ask_is_not_refused_while_the_cancel_of_a_tell_on_its_thread_is_under_way(
        browser, hub, ready, session, monkeypatch):
    """Only a Tell is kept out by the cancel of a Tell: an Ask does not touch the wait."""
    slow = SlowDeliveryAsk()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    go, canceller, got = cancel_under_way(browser, hub, ready, slow, monkeypatch, "render")
    try:
        assert post(browser, "/_/ask").status == 200
        assert hub.runner.active("ask") == [[DOC, "c1"]]
    finally:
        post(browser, "/_/cancel", what="ask")
        go()
        canceller.join(10)
    finish(hub)
    assert got["cancel"].json() == {"ok": True}


@pytest.mark.parametrize("cancel", ["under way", "over"])
@pytest.mark.parametrize("route", ["tell", "comment"])
def test_a_tell_that_a_cancel_overtakes_between_its_wait_and_its_delivery_delivers_nothing(
        browser, hub, ready, session, monkeypatch, route, cancel):
    """A Tell takes the admission lock twice: for its wait, then for its job. A cancel whose step comes in
    between finds no job to end and ends the wait. If it has not yet ended the wait when the job is to
    start, or has ended it and is over, the delivery would be the one the person cancelled, and the stop
    message may have come first. The refused Tell leaves the wait to the cancel: the Tell delivered before
    it still gets its stop message."""
    slow = SlowDelivery()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    told_and_over(browser, hub, slow)
    got, real_thread = {}, hub.asktell._thread
    canceller = threading.Thread(target=lambda: got.update(cancel=post(browser, "/_/cancel",
                                                                       what="tell")), daemon=True)
    if cancel == "under way":
        reached, released = hold_back_stop_waiting(hub.entry(DOC).live, monkeypatch)

    def between_the_two_admissions(e, cid):
        if cancel == "under way":
            canceller.start()
            assert reached.wait(5)               # past its step, at the end of the wait
        else:
            canceller.run()                      # the whole cancel, here and not in a thread of its own
            finish(hub)
        return real_thread(e, cid)
    monkeypatch.setattr(hub.asktell, "_thread", between_the_two_admissions)
    try:
        r = tell_by(browser, route)
    finally:
        if cancel == "under way":
            released.set()
            canceller.join(10)
    assert refusal(r, route) == (CANCELLING if cancel == "under way" else WAIT_ENDED)
    assert r.status == (409 if route == "tell" else 200) and got["cancel"].json() == {"ok": True}
    finish(hub)
    assert hub.entry(DOC).live.waiting() == []
    assert slow.log == ["deliver-start", "deliver-end", "stop"]     # the cancel found the wait; no second Tell


def test_a_wait_that_a_reply_begins_during_a_cancel_is_ended_with_it(
        browser, hub, ready, session, monkeypatch):
    """A reply sent with Tell begins its wait under the document's lock, which the runner knows nothing of.
    One that begins after the cancel has ended the wait, and is refused because the stop message is not
    out yet, would be left to nobody: the thread would show "working" with no Tell for ten minutes, on the
    hub and in the page that sent the reply."""
    slow = SlowStop()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    sub = tab(hub)
    told_and_over(browser, hub, slow)
    got, real_line = {}, hub.asktell.telling_line

    def line_then_a_whole_cancel(address, cid):
        line = real_line(address, cid)           # no cancel yet
        got["cancel"] = post(browser, "/_/cancel", what="tell")      # the wait ends, the stop message waits
        return line
    monkeypatch.setattr(hub.asktell, "telling_line", line_then_a_whole_cancel)
    r = tell_by(browser, "comment")
    assert refusal(r, "comment") == CANCELLING and got["cancel"].json() == {"ok": True}
    slow.stop_release.set()
    finish(hub)
    assert hub.entry(DOC).live.waiting() == []
    assert slow.log == ["deliver-start", "deliver-end", "stop-start", "stop-end"]
    # the page that sent the reply holds the wait it was told of ("working"): the end of it is said
    assert named(events(sub), "tell-cancelled") == [{"id": "c1", "sent": True}, {"id": "c1"}]
    monkeypatch.setattr(hub.asktell, "telling_line", real_line)
    assert refusal(tell_by(browser, "comment"), "comment") is None        # and the thread takes a Tell again


def test_is_waiting_answers_while_a_render_holds_the_document(browser, hub, ready, session, monkeypatch):
    """It is asked under the admission lock: a read that waited for the document's lock would hold
    every Ask and Tell start and every upgrade stop up behind a render."""
    slow = SlowDelivery()
    monkeypatch.setattr(hub, "adapter", lambda agent: slow)
    told_and_over(browser, hub, slow)
    release, got = stall_the_rebuild(hub, ready, monkeypatch), []
    asker = threading.Thread(target=lambda: got.append(hub.entry(DOC).live.is_waiting("c1")), daemon=True)
    try:
        asker.start()
        asker.join(2)
        assert got == [True]
    finally:
        release.set()
        asker.join(10)
