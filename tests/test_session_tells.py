"""A member's Tell to a session on their laptop (SPEC 9.8): queued on the hub, answered by the door's `tells` long-poll,
only to the token that declared the session and only for that session id; the page shows queued, waiting, seen and done."""
import threading
import time

import pytest

from sheafmd.hub.state import Tokens
from helpers import BEA, CAL, call, door, ok, refused, rpc
from test_hub_target import DOC
from test_hub_waiting import agent_token, talk  # noqa: F401  (talk is a fixture)
from test_proxy_own_agents import both, doc, post

SESSION = "6f1c2f0e-3a55-4a0e-9d52-0c1f6a1b7d11"


def declared(session):
    return {"X-Sheaf-Session": session, "X-Sheaf-Host": "laptop"}


@pytest.fixture
def laptops(front, browser, talk, work):
    """Bea has two laptops (a token each), Cal one; each token is a Claude Code token that may write."""
    front.tokens = {n: agent_token(n, "Claude Code", write=True) for n in ("bea-one", "bea-two", "cal-one")}
    front.hub.proxy = both(work, bea=["bea-one", "bea-two"], cal=["cal-one"])
    front.door = browser
    return front


def say(laptops, who, tool, header=SESSION, **args):
    res = door(laptops.door, rpc("tools/call", {"name": tool, "arguments": args}), token=laptops.tokens[who],
               headers=declared(header) if header else {}, as_name=None)
    assert res.status == 200, res.text
    out = res.json()["result"]
    return out["isError"], (out["content"][0]["text"] if out["isError"] else __import__("json").loads(out["content"][0]["text"]))


def declare(laptops, who="bea-one", session=SESSION):
    """The session declares itself the way it does: by writing, here a reply to the comment."""
    bad, got = say(laptops, who, "reply", session, doc=DOC, id="c1", text="Looking.")
    assert not bad, got


def tell(laptops, member=BEA):
    return post(laptops, member, "/_/tell")


def poll(laptops, who="bea-one", session=SESSION, wait=0):
    return say(laptops, who, "tells", session, wait=wait)


def test_a_session_that_wrote_becomes_the_members_target_and_a_tell_waits_for_it_until_it_listens(laptops):
    declare(laptops)
    target = doc(laptops, BEA)["target"]
    assert target["laptop"] is True and target["display"].endswith("· 6f1c2f0e")
    assert tell(laptops).status == 200
    assert doc(laptops, BEA)["telling"] == [{"id": "c1", "to": "Claude Code (Bea) · 6f1c2f0e", "state": "waiting", "laptop": True}]
    assert poll(laptops)[0] is False
    assert doc(laptops, BEA)["telling"][0]["state"] == "seen" and doc(laptops, BEA)["telling"][0]["laptop"] is True


def test_the_declaring_token_gets_the_tell_once_and_it_is_marked_seen(laptops):
    declare(laptops)
    tab = laptops.get(f"/_/live?doc={DOC}", member=BEA).stream
    tell(laptops)
    bad, got = poll(laptops)
    assert not bad and [t["thread"] for t in got["tells"]] == ["c1"]
    assert "Tell from sheaf" in got["tells"][0]["message"] and got["tells"][0]["doc"] == DOC
    assert [(n, d.get("state")) for n, d in tab.drain() if n.startswith("tell-")] == [("tell-queued", "waiting"), ("tell-seen", None)]
    again = poll(laptops)[1]["tells"]
    assert [t["thread"] for t in again] == ["c1"]            # seen is not taken away: until it answers, it is listed


def test_another_members_token_claiming_the_same_session_id_gets_nothing(laptops):
    declare(laptops)
    tell(laptops)
    assert poll(laptops, "cal-one")[1] == {"tells": []}
    assert doc(laptops, BEA)["telling"][0]["state"] == "waiting"     # untouched: not seen


def test_a_second_laptop_of_the_same_member_declaring_the_same_id_does_not_take_the_first_laptops_tell(laptops):
    declare(laptops)
    tell(laptops)
    assert poll(laptops, "bea-two")[1] == {"tells": []}
    assert doc(laptops, BEA)["telling"][0]["state"] == "waiting"


def test_a_replayed_session_id_from_another_token_gets_nothing_and_another_id_of_the_right_token_gets_nothing(laptops):
    declare(laptops)
    tell(laptops)
    assert poll(laptops, "cal-one", SESSION)[1] == {"tells": []}
    assert poll(laptops, "bea-one", "another-session")[1] == {"tells": []}
    assert doc(laptops, BEA)["telling"][0]["state"] == "waiting"


def test_a_resumed_session_of_the_same_member_and_laptop_picks_the_tell_up_whenever_it_comes_back(laptops):
    declare(laptops)
    tell(laptops)
    laptops.hub.session_tells._now = lambda t=time.monotonic: t() + 7 * 86400     # a week: no expiry
    assert doc(laptops, BEA)["telling"][0]["state"] == "waiting"
    assert [t["thread"] for t in poll(laptops)[1]["tells"]] == ["c1"]


def test_an_action_reply_from_the_session_ends_the_tell_as_done_and_another_sessions_reply_does_not(laptops):
    declare(laptops)
    tell(laptops)
    poll(laptops)
    tab = laptops.get(f"/_/live?doc={DOC}", member=BEA).stream
    say(laptops, "bea-one", "reply", "other-session", doc=DOC, id="c1", text="No.", role="action")
    assert doc(laptops, BEA)["telling"][0]["state"] == "seen"
    say(laptops, "bea-one", "reply", SESSION, doc=DOC, id="c1", text="Done.", role="action")
    assert doc(laptops, BEA)["telling"] == []
    assert [n for n, _ in tab.drain() if n.startswith("tell-")] == ["tell-done"]


def test_cancel_ends_only_the_readers_own_tell_and_the_session_is_left_nothing(laptops):
    declare(laptops)
    tell(laptops)
    assert post(laptops, CAL, "/_/cancel").status == 200
    assert len(doc(laptops, BEA)["telling"]) == 1
    assert post(laptops, BEA, "/_/cancel").status == 200
    assert doc(laptops, BEA)["telling"] == [] and poll(laptops)[1] == {"tells": []}


def test_retarget_sends_the_waiting_tell_to_the_members_own_agent_instead(laptops, browser):
    agent = laptops.tokens["bea-agent"] = agent_token("bea-agent", "ChatGPT")
    laptops.hub.proxy = both(laptops.hub.proxy.members[BEA].roots[0], bea=["bea-one", "bea-two", "bea-agent"], cal=["cal-one"])
    declare(laptops)
    tell(laptops)
    assert post(laptops, CAL, "/_/retarget", target="agent:bea-agent").status in (400, 409)     # not his Tell
    assert post(laptops, BEA, "/_/retarget", target="agent:cal-one").status == 400              # not her agent
    assert post(laptops, BEA, "/_/retarget", target="agent:bea-agent").status == 200
    assert doc(laptops, BEA)["telling"] == [{"id": "c1", "to": "ChatGPT (Bea)", "state": "queued"}]
    assert poll(laptops)[1] == {"tells": []}
    assert ok(browser, "documents", token=agent)[0]["tells"]


def test_a_poll_with_nothing_waiting_returns_empty_within_its_wait_and_wakes_at_once_for_a_tell(laptops):
    declare(laptops)
    began = time.monotonic()
    assert poll(laptops, wait=1)[1] == {"tells": []}
    assert 0.8 < time.monotonic() - began < 3
    got = []
    t = threading.Thread(target=lambda: got.append(poll(laptops, wait=20)))
    t.start()
    time.sleep(0.3)
    tell(laptops)
    t.join(10)
    assert not t.is_alive() and [x["thread"] for x in got[0][1]["tells"]] == ["c1"]


def test_a_token_holds_at_most_two_polls_and_the_third_is_refused_with_a_wait(laptops):
    declare(laptops)
    holds = [threading.Thread(target=poll, args=(laptops,), kwargs={"wait": 2}) for _ in range(2)]
    for h in holds:
        h.start()
    time.sleep(0.5)
    bad, said = poll(laptops)
    assert bad and "already holds 2" in said and "5 seconds" in said
    for h in holds:
        h.join(10)
    assert poll(laptops)[0] is False                                         # the holds are given back
    assert poll(laptops, "bea-two")[0] is False                              # another token has its own count


def test_the_poll_needs_a_members_agent_token_and_one_session_id(laptops, browser):
    assert refused(browser, "tells", token=laptops.tokens["bea-one"]).startswith("Name the session")
    bad, said = say(laptops, "bea-one", "tells", None, session="x\ny", wait=0)
    assert bad
    assert call(browser, "tells", as_name="Claude")[0] is True               # the key is no member's laptop
    bad, said = say(laptops, "bea-one", "tells", SESSION, session="another", wait=0)
    assert bad and "different sessions" in said


def test_a_revoked_token_leaves_its_waiting_tell_waiting_for_the_member_to_cancel_or_retarget(laptops):
    agent = laptops.tokens["bea-agent"] = agent_token("bea-agent", "ChatGPT")
    laptops.hub.proxy = both(laptops.hub.proxy.members[BEA].roots[0], bea=["bea-one", "bea-two", "bea-agent"], cal=["cal-one"])
    declare(laptops)
    tell(laptops)
    Tokens().revoke("bea-one")
    mine = doc(laptops, BEA)["telling"]
    assert mine == [{"id": "c1", "to": "Claude Code (Bea) · 6f1c2f0e", "state": "waiting", "laptop": True}]   # a Tell never expires
    assert poll(laptops, "bea-two")[1] == {"tells": []}                   # the other laptop does not inherit it
    assert post(laptops, BEA, "/_/retarget", target="agent:bea-agent").status == 200
    assert doc(laptops, BEA)["telling"] == [{"id": "c1", "to": "ChatGPT (Bea)", "state": "queued"}]
    declare(laptops, "bea-two", "second")
    tell(laptops)
    Tokens().revoke("bea-two")
    assert len(doc(laptops, BEA)["telling"]) == 2
    assert post(laptops, BEA, "/_/cancel").status == 200
    assert doc(laptops, BEA)["telling"] == []


def test_the_events_and_the_rows_name_a_laptop_tell_alike_so_the_page_finds_its_line(laptops):
    declare(laptops)
    tab = laptops.get(f"/_/live?doc={DOC}", member=BEA).stream
    tell(laptops)
    name = doc(laptops, BEA)["telling"][0]["to"]
    poll(laptops)
    assert post(laptops, BEA, "/_/cancel").status == 200
    heard = [d["agent"] for n, d in tab.drain() if n.startswith("tell-")]
    assert heard and set(heard) == {name}


def test_a_retarget_the_hub_refuses_leaves_the_target_and_the_waiting_tell_as_they_were(laptops):
    laptops.tokens["bea-agent"] = agent_token("bea-agent", "ChatGPT")
    laptops.hub.proxy = both(laptops.hub.proxy.members[BEA].roots[0], bea=["bea-one", "bea-two", "bea-agent"], cal=["cal-one"])
    declare(laptops)
    tell(laptops)
    assert post(laptops, BEA, "/_/retarget", target="agent:bea-agent").status == 200
    declare(laptops)                                                # the laptop is the target again, with a new Tell
    tell(laptops)
    before = doc(laptops, BEA)["target"]
    assert before["laptop"] is True
    assert post(laptops, BEA, "/_/retarget", target="agent:bea-agent").status == 409      # that agent has this comment waiting already
    assert doc(laptops, BEA)["target"] == before
    assert [t["state"] for t in doc(laptops, BEA)["telling"] if t.get("laptop")] == ["waiting"]


def test_a_token_that_no_longer_acts_for_the_tells_member_is_listed_nothing(laptops):
    declare(laptops)
    tell(laptops)
    laptops.hub.proxy = both(laptops.hub.proxy.members[BEA].roots[0], bea=["bea-two"], cal=["cal-one", "bea-one"])
    assert poll(laptops)[1] == {"tells": []}
    assert doc(laptops, BEA)["telling"][0]["state"] != "seen"


@pytest.mark.parametrize("how", ["resolve", "reply-and-resolve"])
def test_a_resolve_from_the_page_ends_the_laptop_tell_as_the_door_does(laptops, how):
    declare(laptops)
    tell(laptops)
    assert [t["laptop"] for t in doc(laptops, BEA)["telling"]] == [True]
    body = {"op": "status", "status": "resolved"} if how == "resolve" else {"op": "reply", "body": "Thanks.", "resolve": True}
    assert post(laptops, BEA, "/_/comment", **body).status == 200
    assert [t for t in doc(laptops, BEA)["telling"] if t.get("laptop")] == []
    assert poll(laptops)[1] == {"tells": []}


def test_the_words_of_a_tell_are_read_under_the_pages_name_and_outside_the_session_lock(laptops, monkeypatch):
    from sheafmd import mcp
    from sheafmd.hub import place
    declare(laptops)
    tell(laptops)
    seen = []
    real = mcp.Door._open_in

    def spy(self, address, whole=False):
        seen.append((place.owns(laptops.hub, address), laptops.hub.session_tells._lock._is_owned()))
        return real(self, address, whole)
    monkeypatch.setattr(mcp.Door, "_open_in", spy)
    assert [t["thread"] for t in poll(laptops)[1]["tells"]] == ["c1"]
    assert seen and all(held and not locked for held, locked in seen)


def test_a_session_id_over_the_limit_never_becomes_a_target_so_no_poll_of_it_is_refused_for_ever(laptops):
    from sheafmd.hub import session_tells
    long = "s" * (session_tells.MAX_SESSION + 1)
    declare(laptops, session=long)
    assert doc(laptops, BEA)["target"].get("laptop") is not True
    declare(laptops, session="s" * session_tells.MAX_SESSION)
    assert doc(laptops, BEA)["target"]["laptop"] is True


def test_a_session_that_stopped_polling_is_forgotten_after_it_stopped_counting_as_listening(laptops):
    from sheafmd.hub import session_tells
    tells = laptops.hub.session_tells
    tells._heard[("bea-one", "old-id", "gone")] = tells._now() - session_tells.LISTENING - 1
    declare(laptops)
    poll(laptops)
    assert ("bea-one", "old-id", "gone") not in tells._heard
    assert any(k[2] == SESSION for k in tells._heard)


def test_a_poll_whose_caller_has_gone_returns_at_once_and_frees_its_slot_for_a_fast_reconnect(laptops):
    from sheafmd.hub import waiting
    tells = laptops.hub.session_tells
    row = laptops.hub.tokens.list()[0]
    gone = threading.Event()
    done = []

    def held():
        done.append(tells.take(row, SESSION, 25, lambda t: False, gone=gone.is_set))
    pollers = [threading.Thread(target=held) for _ in range(2)]
    for p in pollers:
        p.start()
    time.sleep(0.3)
    with pytest.raises(waiting.Refused):                     # two are held: a third is refused
        tells.take(row, SESSION, 0, lambda t: False)
    began = time.monotonic()
    gone.set()
    for p in pollers:
        p.join(5)
    assert time.monotonic() - began < 3 and done == [[], []]
    assert tells.take(row, SESSION, 0, lambda t: False) == []           # the reconnect is not refused


def test_the_server_tells_a_poll_that_its_caller_closed_the_connection():
    import socket
    from sheafmd.hub import server
    a, b = socket.socketpair()
    me = type("H", (), {"connection": a})()
    try:
        assert server._Http._gone(me) is False
        b.close()
        assert server._Http._gone(me) is True
    finally:
        a.close()


def test_a_write_answers_with_the_session_id_the_door_recorded_for_it(laptops):
    """The mod arms only when this id is the session's own (SPEC 9.14): after a /clear the helper may still send the old id."""
    bad, got = say(laptops, "bea-one", "reply", SESSION, doc=DOC, id="c1", text="Looking.")
    assert not bad and got["session"] == SESSION
    bad, got = say(laptops, "bea-one", "resolve", "old-id-2", doc=DOC, id="c1")
    assert not bad and got["session"] == "old-id-2"
    bad, got = say(laptops, "bea-one", "reply", None, doc=DOC, id="c1", text="No header.")
    assert not bad and "session" not in got


def test_a_poll_is_written_to_the_diagnostics_once_a_minute_per_session_with_no_token(laptops):
    from helpers import hub_rows
    from sheafmd.hub import session_tells
    tells = laptops.hub.session_tells
    now = [1000.0]
    tells._now = lambda: now[0]
    declare(laptops)
    poll(laptops)
    poll(laptops)                                                    # a second poll a moment later: no second row
    rows = hub_rows("tells-poll")
    assert len(rows) == 1 and rows[0]["laptop_session"] == SESSION and rows[0]["token"] == "bea-one"
    assert laptops.tokens["bea-one"] not in str(rows)                # the name of the token, never its secret
    poll(laptops, session="another-session-id")                       # another session: its own row
    assert len(hub_rows("tells-poll")) == 2
    now[0] += session_tells.LISTENING + 1
    poll(laptops)                                                    # a minute on: the session is heard again
    assert len(hub_rows("tells-poll")) == 3
