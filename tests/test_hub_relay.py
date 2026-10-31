"""The relay of a forked session (SPEC 9.14, sheaf#117): the fork's report gets a relay token, and `sheaf relay` on
the member's machine takes the Tells of that one sheaf for that one session through `/_/relay`. The verifier hands
the hub the token's sha256 as `X-Sheaf-Relay` and no member header. Through the handler in proxy mode, on the
fixtures of test_hub_work.py."""
import hashlib
import json
import os
import stat
import threading

from helpers import hub_rows
from test_hub_work import (  # noqa: F401
    ADDRESS,
    BEA,
    DOC,
    FORK,
    HANS,
    LIVE,
    SHEAF,
    THIERRY,
    box,
    comment,
    drops,
    fork,
    put,
    sessions_of,
    team,
)

from sheafmd.hub import relay as relay_mod
from sheafmd.hub import work as work_mod
from sheafmd.hub.handler import RELAY_MOVED

OTHER_DOC = "thinkingtoo/tiroir/2026-10-29-other.md"
OTHER = f"work/{OTHER_DOC}"
FORK2 = "8f9a0b1c-2d3e-4f5a-9b6c-7d8e9f0a1b2c"
NO_GOOD = "This relay token is no good: fork the session again."


def hashed(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def forked(team, doc=ADDRESS, id=FORK, as_=HANS):
    got = team.post("/_/sessions", {"doc": doc, "id": id, "machine": "hans-mac"}, member=as_)
    assert got.status == 200, got.text
    return got.json()["relay"]


def with_relay(team, method, path, token, body=None, **kw):
    """A request as Caddy sends it after the verifier took a relay token: `X-Sheaf-Relay` and no member header."""
    h = {"X-Sheaf-Relay": hashed(token) if token.startswith(relay_mod.PREFIX) else token, **kw.pop("headers", {})}
    if method == "GET":
        return team.get(path, member=None, headers=h, **kw)
    return team.post(path, body if body is not None else {}, member=None, headers=h, **kw)


def listen(team, token, doc=ADDRESS):
    return with_relay(team, "GET", f"/_/relay?doc={doc}", token)


def ack(team, token, id, outcome="delivered", doc=ADDRESS, **extra):
    return with_relay(team, "POST", "/_/relay", token, {"doc": doc, "id": id, "outcome": outcome, **extra})


def tells(sub):
    return [d for name, d in sub.drain() if name == "tell"]


# ── the token ────────────────────────────────────────────────────────────────

def test_a_fork_report_answers_a_relay_token_kept_only_as_its_hash(team, box, work):
    token = forked(team)
    assert token.startswith("sheaf_relay_") and len(token) == len("sheaf_relay_") + 43
    f = relay_mod.Relays.path()
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    raw = f.read_text(encoding="utf-8")
    assert token not in raw and hashed(token) in raw
    row, = json.loads(raw)
    assert (row["member"], row["doc"], row["session"]) == (HANS, ADDRESS, FORK)


def test_the_token_is_in_no_row_and_not_on_the_page(team, box, work):
    token = forked(team)
    sub = listen(team, token).stream
    page = team.get(f"/_/doc?doc={ADDRESS}", member=HANS).text + team.get("/" + DOC, member=HANS).text
    sub.close()
    text = json.dumps(hub_rows()) + page
    assert token not in text and hashed(token) not in text


def test_a_fork_reported_with_a_sign_in_code_gets_a_relay_token_too(team, box, work):
    from test_hub_code import code_of, fetch, report
    code = code_of(team)
    assert fetch(team, code).status == 200
    got = report(team, code)
    assert got.status == 200, got.text
    token = got.json()["relay"]
    row, = json.loads(relay_mod.Relays.path().read_text(encoding="utf-8"))
    assert row["sha256"] == hashed(token) and (row["member"], row["session"]) == (HANS, FORK)
    assert listen(team, token).status == 200


def test_a_token_opens_its_stream_with_hello_and_writes_relay_connected(team, box, work):
    token = forked(team)
    got = listen(team, token)
    assert got.status == 200 and got.headers["Content-Type"] == "text/event-stream"
    assert got.stream.drain()[0] == ("hello", {"doc": ADDRESS, "session": FORK})
    row, = hub_rows("relay-connected")
    assert (row["doc"], row["transcript"], row["member"]) == (ADDRESS, FORK, HANS) and "relay" in row
    got.stream.close()
    assert len(hub_rows("relay-closed")) == 1


def test_a_token_for_sheaf_a_is_refused_on_sheaf_b(team, box, work):
    put(team, work, OTHER_DOC, SHEAF)
    token = forked(team)
    got = listen(team, token, doc=OTHER)
    assert got.status == 404
    assert hub_rows("relay-refused")[-1]["reason"] == "doc"
    assert ack(team, token, "0" * 8, doc=OTHER).status == 404


def test_a_token_reaches_the_relay_routes_only(team, box, work):
    token = forked(team)
    for method, path in (("GET", f"/_/doc?doc={ADDRESS}"), ("GET", f"/_/session?doc={ADDRESS}"),
                         ("POST", "/_/sessions"), ("POST", "/_/comment"), ("GET", "/" + DOC)):
        got = with_relay(team, method, path, token, {"doc": ADDRESS} if method == "POST" else None)
        assert got.status == 404, (path, got.text)
    assert hub_rows("relay-refused")[-1]["reason"] == "route"


def test_a_made_up_token_is_refused_with_one_sentence(team, box, work):
    got = listen(team, relay_mod.PREFIX + "x" * 43)
    assert got.status == 401 and got.json()["error"] == NO_GOOD


def test_a_token_and_a_member_header_together_are_refused(team, box, work):
    token = forked(team)
    got = team.get(f"/_/relay?doc={ADDRESS}", member=HANS, headers={"X-Sheaf-Relay": hashed(token)})
    assert got.status == 401
    assert hub_rows("relay-refused")[-1]["reason"] == "two-credentials"


def test_a_token_is_refused_once_its_member_leaves_proxy_members(team, box, work):
    token = forked(team)
    members = dict(team.hub.proxy.members)
    del members[HANS]
    object.__setattr__(team.hub.proxy, "members", members)
    got = listen(team, token)
    assert got.status == 401 and got.json()["error"] == NO_GOOD
    assert hub_rows("relay-refused")[-1]["reason"] == "member"


def test_a_token_is_refused_after_sheaf_relay_revoke(team, box, work):
    token = forked(team)
    sub = listen(team, token).stream
    sub.drain()
    assert team.hub.relays.revoke(ADDRESS) == 1
    assert sub.drain()[-1][0] == "gone"
    assert listen(team, token).status == 401


def test_a_revoke_from_another_process_takes_relay_tell_off_at_once(team, box, work):
    token = forked(team)
    sub = listen(team, token).stream
    assert relay_mod.Relays().revoke(ADDRESS) == 1      # `sheaf relay revoke`: its own Relays, not the hub's
    assert team.get(f"/_/doc?doc={ADDRESS}", member=HANS).json()["capabilities"] == []
    assert comment(team, work, "tell").status == 400
    assert team.hub.relays.open(ADDRESS, FORK) == []
    sub.close()


def test_a_newer_fork_ends_the_older_token(team, box, work):
    old = forked(team)
    sub = listen(team, old).stream
    sub.drain()
    forked(team, id="22222222-3333-4444-8555-666666666666")
    assert sub.drain()[-1][0] == "gone"
    assert listen(team, old).status == 401


def test_a_token_whose_session_is_no_longer_live_is_refused(team, box, work):
    token = forked(team)
    text = (work / DOC).read_text(encoding="utf-8")
    (work / DOC).write_text(text.replace(f"{{id: {FORK}, host: hans-mac", f"{{id: {FORK}, host: tiroir-tt"), "utf-8")
    got = listen(team, token)
    assert got.status == 401
    assert hub_rows("relay-refused")[-1]["reason"] == "moved"


def test_the_loopback_port_has_no_relay_route(team, box, browser):
    assert browser.get(f"/_/relay?doc={ADDRESS}").status == 404


# ── the comment route, can and the queue ─────────────────────────────────────

def test_without_a_connected_relay_tell_on_a_fork_is_refused(team, box, work):
    forked(team)
    got = comment(team, work, "tell")
    assert got.status == 400
    assert team.hub.relays.open(ADDRESS, FORK) == []


def test_can_offers_relay_tell_while_the_relay_of_that_session_is_connected(team, box, work, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(relay_mod, "_clock", lambda: now[0])
    token = forked(team)
    assert team.get(f"/_/doc?doc={ADDRESS}", member=HANS).json()["capabilities"] == []
    sub = listen(team, token).stream
    j = team.get(f"/_/doc?doc={ADDRESS}", member=HANS).json()
    assert j["capabilities"] == ["relay-tell"]
    assert j["work"]["relay"] is True
    sub.close()
    now[0] += relay_mod.GRACE           # a relay that has not reconnected within the grace (#135)
    j = team.get(f"/_/doc?doc={ADDRESS}", member=HANS).json()
    assert j["capabilities"] == [] and j["work"]["relay"] is False


def test_a_tell_on_a_fork_goes_to_its_relay_with_the_full_message(team, box, work):
    token = forked(team)
    sub = listen(team, token).stream
    sub.drain()
    got = comment(team, work, "tell", as_=THIERRY)
    assert got.status == 200, got.text
    assert drops(box) == []
    t, = tells(sub)
    assert work_mod.UUID_RE.fullmatch(t["id"])
    assert t["message"].startswith(f"Tell from sheaf, on the page of {ADDRESS} (")
    assert f"Thierry pressed Tell on comment {got.json()['id']}" in t["message"]
    assert "Can you send the draft to Joey?" in t["message"]
    row, = hub_rows("tell-relayed")
    assert (row["tell"], row["thread"], row["by"]) == (t["id"], got.json()["id"], "thierry")


def test_ask_on_a_fork_stays_refused_with_a_relay_connected(team, box, work):
    token = forked(team)
    listen(team, token)
    assert comment(team, work, "ask").status == 400


def test_a_tell_is_sent_again_on_reconnect_with_the_same_id_until_acked(team, box, work):
    token = forked(team)
    first = listen(team, token).stream
    comment(team, work, "tell")
    t, = tells(first)
    first.close()
    again = listen(team, token).stream
    assert tells(again) == [t]
    assert ack(team, token, t["id"]).status == 200
    row, = hub_rows("tell-delivered")
    assert row["tell"] == t["id"]
    again.close()
    assert tells(listen(team, token).stream) == []


def test_a_failed_ack_writes_its_row_and_tells_the_page(team, box, work):
    token = forked(team)
    sub = listen(team, token).stream
    tab = team.get(f"/_/live?doc={ADDRESS}", member=HANS).stream
    comment(team, work, "tell")
    t, = tells(sub)
    tab.drain()
    assert ack(team, token, t["id"], "failed", error="the session was cleared: fork again").status == 200
    row, = hub_rows("tell-relay-failed")
    assert row["tell"] == t["id"] and row["error"] == "the session was cleared: fork again"
    data = next(d for n, d in tab.drain() if n == "tell-relay-failed")
    assert data["error"] == "the session was cleared: fork again"


def test_an_ack_of_another_shape_or_an_unknown_id_is_refused(team, box, work):
    token = forked(team)
    listen(team, token)
    assert ack(team, token, "nope", outcome="maybe").status == 400
    assert ack(team, token, "11111111-2222-4333-8444-555555555555").status == 404


def test_at_most_twenty_tells_are_open_on_a_sheaf(team, box, work):
    token = forked(team)
    listen(team, token)
    for _ in range(relay_mod.QUEUE_MAX):
        assert "tellError" not in comment(team, work, "tell").json()
    got = comment(team, work, "tell")
    assert got.status == 200 and got.json()["tellError"] == relay_mod.FULL
    assert len(team.hub.relays.open(ADDRESS, FORK)) == 20


def test_a_queued_tell_expires_after_an_hour(team, box, work, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(relay_mod, "_clock", lambda: now[0])
    token = forked(team)
    listen(team, token)
    tab = team.get(f"/_/live?doc={ADDRESS}", member=HANS).stream
    got = comment(team, work, "tell")
    tab.drain()
    now[0] += relay_mod.TTL - 1
    team.handler._expire_relayed()
    assert hub_rows("tell-expired") == []
    now[0] += 1
    team.handler._expire_relayed()
    row, = hub_rows("tell-expired")
    assert row["thread"] == got.json()["id"]
    assert team.hub.relays.open(ADDRESS, FORK) == []
    data = next(d for n, d in tab.drain() if n == "tell-relay-failed")
    assert data == {"id": got.json()["id"], "error": relay_mod.EXPIRED}


def test_a_tell_whose_fork_moved_under_the_lock_is_refused_and_queues_nothing(team, box, work, monkeypatch):
    token = forked(team)
    listen(team, token)
    real = team.hub.relays.connected
    calls = []

    def moved_meanwhile(doc, session):
        calls.append(1)
        if len(calls) > 1:          # the gate saw the relay; the recheck under the lock sees a newer fork
            text = (work / DOC).read_text(encoding="utf-8")
            (work / DOC).write_text(text.replace(f"{{id: {FORK}, host: hans-mac", f"{{id: {FORK}, host: tiroir-tt"),
                                    "utf-8")
            return False
        return real(doc, session)
    monkeypatch.setattr(team.hub.relays, "connected", moved_meanwhile)
    assert comment(team, work, "tell").status == 400
    assert team.hub.relays.open(ADDRESS, FORK) == []


def test_two_forks_reported_at_once_leave_the_later_one_with_a_good_token(team, box, work, monkeypatch):
    """#134: fork A is written first, so B is live; A's token must not be issued after B's and push it out."""
    real, other = team.hub.relays.issue, {}

    def issue(member, doc, session):
        if session == FORK and not other:
            def report_b():
                other["got"] = team.post("/_/sessions", {"doc": ADDRESS, "id": FORK2, "machine": "hans-mac"},
                                         member=HANS)
            other["thread"] = threading.Thread(target=report_b)
            other["thread"].start()
            other["thread"].join(1.0)       # B's report runs to its end here unless A's lock holds it back
        return real(member, doc, session)
    monkeypatch.setattr(team.hub.relays, "issue", issue)
    forked(team)
    other["thread"].join(10)
    got = other["got"]
    assert got.status == 200, got.text
    assert sessions_of(work)[0].startswith(f"{{id: {FORK2}, ")
    sub = listen(team, got.json()["relay"])
    assert sub.status == 200, sub.text
    assert [n for n, _ in sub.stream.drain()] == ["hello"]


def test_a_tell_judged_on_one_fork_is_not_queued_for_a_newer_one(team, box, work, monkeypatch):
    """#134: a fork that lands between the comment's write and the queue does not receive the Tell."""
    listen(team, forked(team))
    real = team.handler._relay_tell

    def fork_lands_first(*a, **kw):
        forked(team, id=FORK2)
        return real(*a, **kw)
    monkeypatch.setattr(team.handler, "_relay_tell", fork_lands_first)
    got = comment(team, work, "tell")
    assert got.status == 200 and got.json()["tellError"] == RELAY_MOVED
    assert team.hub.relays.open(ADDRESS, FORK2) == []


def test_a_live_session_changed_by_hand_drops_the_queued_tells_with_a_row(team, box, work):
    """#134: the live session changed in the file, not by a fork report: the Tells queued for the old one are
    dropped as for a fork, with their row and the page's event, when the next Tell is queued for the new one."""
    listen(team, forked(team))
    tab = team.get(f"/_/live?doc={ADDRESS}", member=HANS).stream
    first = comment(team, work, "tell").json()["id"]
    put(team, work, DOC, (work / DOC).read_text(encoding="utf-8").replace(f"{{id: {FORK},", f"{{id: {FORK2},"))
    team.hub.entry(ADDRESS).live.refresh()
    token2, _ = team.hub.relays.issue(HANS, ADDRESS, FORK2)
    listen(team, token2)
    tab.drain()
    got = comment(team, work, "tell")
    assert got.status == 200 and "tellError" not in got.json(), got.text
    row, = hub_rows("tell-relay-failed")
    assert row["thread"] == first and row["error"] == RELAY_MOVED
    assert {"id": first, "error": RELAY_MOVED} in [d for n, d in tab.drain() if n == "tell-relay-failed"]
    assert [t.thread for t in team.hub.relays.open(ADDRESS, FORK2)] == [got.json()["id"]]


# ── #135: the reconnect gap, the page told, expiry by the clock, visibility ──

def test_a_tell_pressed_in_the_reconnect_gap_is_queued_and_sent_on_reconnect(team, box, work, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(relay_mod, "_clock", lambda: now[0])
    token = forked(team)
    listen(team, token).stream.close()          # the front ended the stream; the relay is reconnecting
    now[0] += relay_mod.GRACE - 1
    got = comment(team, work, "tell")
    assert got.status == 200 and "tellError" not in got.json(), got.text
    row, = hub_rows("tell-relayed")
    assert row["thread"] == got.json()["id"]
    assert [t["id"] for t in tells(listen(team, token).stream)] == [row["tell"]]


def test_past_the_grace_a_closed_relay_is_no_longer_connected(team, box, work, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(relay_mod, "_clock", lambda: now[0])
    listen(team, forked(team)).stream.close()
    now[0] += relay_mod.GRACE
    assert comment(team, work, "tell").status == 400
    assert team.get(f"/_/doc?doc={ADDRESS}", member=HANS).json()["capabilities"] == []


def test_the_page_is_told_when_a_relay_connects_and_when_it_is_gone(team, box, work, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(relay_mod, "_clock", lambda: now[0])
    token = forked(team)
    tab = team.get(f"/_/live?doc={ADDRESS}", member=HANS).stream
    tab.drain()
    sub = listen(team, token).stream
    assert [n for n, _ in tab.drain()].count("relay") == 1
    sub.close()
    listen(team, token).stream.close()          # a reconnect within the grace: the page hears nothing
    team.hub.tick()
    assert "relay" not in [n for n, _ in tab.drain()]
    now[0] += relay_mod.GRACE
    team.hub.tick()
    assert [n for n, _ in tab.drain()].count("relay") == 1


def test_a_queued_tell_expires_by_the_clock_with_nothing_calling_in(team, box, work, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(relay_mod, "_clock", lambda: now[0])
    listen(team, forked(team))
    got = comment(team, work, "tell")
    now[0] += relay_mod.TTL
    team.hub.tick()
    row, = hub_rows("tell-expired")
    assert row["thread"] == got.json()["id"]


def test_a_member_whose_access_is_taken_away_gets_gone_instead_of_the_tell(team, box, work):
    sub = listen(team, forked(team)).stream
    sub.drain()
    (work / "projects.toml").write_text('[projects."thinkingtoo/tiroir"]\nmembers = ["thierry"]\n'
                                        'status = "live"\n', encoding="utf-8")
    relayed = team.hub.relays.put(ADDRESS, FORK, relay_mod.Tell(
        "11111111-2222-4333-8444-555555555555", "c9", "the thread's words", "thierry"))
    assert relayed == []
    assert [n for n, _ in sub.drain()] == ["gone"]


# ── the box's drop carries the Tell's id and its message (9.12) ──────────────

def test_a_tell_dropped_for_james_carries_its_id_message_and_path(team, box, work):
    got = comment(team, work, "tell")
    d = json.loads(drops(box)[0].read_bytes())
    assert work_mod.UUID_RE.fullmatch(d["id"])
    assert d["message"].startswith(f"Tell from sheaf, on the page of {ADDRESS} (")
    assert d["address"] == ADDRESS and d["abs_path"] == str(work / DOC)
    assert d["thread"] == got.json()["id"] and d["kind"] == "tell"
