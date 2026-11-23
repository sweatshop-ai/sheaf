"""One stream for every tab of a browser (ticket 160): `GET /_/live?shared=ID`, with each tab's
stream added by `POST /_/live/join` and dropped by `POST /_/live/leave`. A browser opens six
connections to a host at most, so seven tabs that each held a stream left the seventh waiting for
ever. Each tab's stream stays a Subscription on its own document's Bus: the hub counts it as a tab."""
import pytest

SID = "s" * 24


@pytest.fixture
def docs(world, work):
    names = [f"d{n}.md" for n in range(7)]
    for name in names:
        (work / name).write_text(f"# {name}\n\nText.\n", encoding="utf-8")
        world.hub.render(work / name, {}, None)
    return [f"work/{name}" for name in names]


def shared(world, sid=SID):
    r = world.get(f"/_/live?shared={sid}")
    assert r.status == 200 and r.stream is not None
    return r.stream


def join(world, key, doc, sid=SID):
    return world.post("/_/live/join", {"stream": sid, "key": key, "doc": doc})


def by_key(stream):
    out = {}
    for name, d in stream.drain():
        assert name == "m"
        out.setdefault(d["k"], []).append((d["e"], d["d"]))
    return out


def test_seven_tabs_share_one_stream_and_each_counts_as_a_tab(world, docs):
    stream = shared(world)
    for n, doc in enumerate(docs):
        assert join(world, f"t{n}", doc).status == 200
    got = by_key(stream)
    for n, doc in enumerate(docs):
        assert [e for e, _ in got[f"t{n}"]] == ["open", "hello"]
        assert got[f"t{n}"][1][1]["tabs"] == 1
        assert world.hub.tabs(doc) == 1


def test_an_event_reaches_only_the_tabs_of_its_document(world, docs):
    stream = shared(world)
    join(world, "a", docs[0])
    join(world, "b", docs[1])
    stream.drain()
    world.hub.entries[docs[1]].bus.publish("changed", {"x": 1})
    assert by_key(stream) == {"b": [("changed", {"x": 1})]}


def test_leave_and_a_closed_connection_drop_the_tabs(world, docs):
    stream = shared(world)
    join(world, "a", docs[0])
    join(world, "b", docs[1])
    assert world.post("/_/live/leave", {"stream": SID, "key": "a"}).status == 200
    assert (world.hub.tabs(docs[0]), world.hub.tabs(docs[1])) == (0, 1)
    stream.close()
    assert world.hub.tabs(docs[1]) == 0
    assert join(world, "c", docs[2]).status == 404          # the stream is gone with its connection


def test_a_document_the_hub_does_not_have_is_refused_on_its_key_alone(world, docs):
    stream = shared(world)
    join(world, "a", docs[0])
    assert join(world, "x", "work/nothing-here.md").status == 200
    got = by_key(stream)
    assert got["x"] == [("refused", {"status": 404})]
    assert [e for e, _ in got["a"]] == ["open", "hello"]


def test_the_last_event_of_a_tab_drops_that_tab_and_keeps_the_connection(world, docs):
    stream = shared(world)
    join(world, "a", docs[0])
    join(world, "b", docs[1])
    stream.drain()
    world.hub.entries[docs[0]].bus.publish("gone", {"doc": docs[0]})
    assert by_key(stream) == {"a": [("gone", {"doc": docs[0]})]}
    assert (world.hub.tabs(docs[0]), world.hub.tabs(docs[1])) == (0, 1)
    assert not stream.closed


def test_the_index_joins_with_no_document(world, docs):
    stream = shared(world)
    join(world, "i", "")
    got = by_key(stream)
    assert [e for e, _ in got["i"]] == ["open", "hello"]
    assert world.hub.index_bus.count() == 1


def test_a_key_joined_again_replaces_its_stream(world, docs):
    stream = shared(world)
    join(world, "a", docs[0])
    join(world, "a", docs[0])
    assert world.hub.tabs(docs[0]) == 1
    stream.close()


def test_a_stream_needs_a_proper_id_and_a_signed_in_browser(world, docs):
    assert world.get("/_/live?shared=short").status == 400
    assert world.get(f"/_/live?shared={SID}", cookie=False).status == 401
    assert join(world, "a", docs[0], sid="n" * 24).status == 404
    shared(world)
    assert world.post("/_/live/join", {"stream": SID, "key": "a", "doc": docs[0]}, cookie=False).status == 401


def test_the_same_id_opened_again_closes_the_old_connection(world, docs):
    first = shared(world)
    join(world, "a", docs[0])
    second = shared(world)
    assert first.closed and world.hub.tabs(docs[0]) == 0
    join(world, "a", docs[0])
    assert world.hub.tabs(docs[0]) == 1
    second.close()


def test_an_id_another_member_holds_is_refused_and_their_tabs_stay(front, work):
    """An id read from a front's log closes no one's tabs: only its owner opens it again (proxy mode, 9.9)."""
    from helpers import CAL
    (work / "a.md").write_text("# A\n\nText.\n", encoding="utf-8")
    front.hub.render(work / "a.md", {}, None)
    bea = front.get(f"/_/live?shared={SID}").stream
    assert front.post("/_/live/join", {"stream": SID, "key": "a", "doc": "work/a.md"}).status == 200
    assert front.get(f"/_/live?shared={SID}", member=CAL).status == 409
    assert front.post("/_/live/leave", {"stream": SID, "key": "a"}, member=CAL).status == 404
    assert not bea.closed and front.hub.tabs("work/a.md") == 1
    bea.close()


def test_a_key_that_joins_a_new_connection_leaves_the_old_one(world, docs):
    """A leader hand-over: the old connection is still open here until a write to it fails, and the tab joins the new
    one under the same key. The hub counts it once."""
    old = shared(world)
    join(world, "t1:1", docs[0])
    new = shared(world, sid="n" * 24)
    assert join(world, "t1:1", docs[0], sid="n" * 24).status == 200
    assert world.hub.tabs(docs[0]) == 1 and old.keys() == [] and not old.closed
    old.close()
    new.close()


def test_a_late_join_on_the_old_connection_leaves_the_new_one_its_stream(world, docs):
    """Ticket 181 D: the old leader's join of a key reaches the hub after the tab joined the new connection. It must
    not take the key from the newer connection; the old one, which is going away, does not get it either."""
    old = shared(world)
    new = shared(world, sid="n" * 24)
    assert join(world, "t1:1", docs[0], sid="n" * 24).status == 200
    assert join(world, "t1:1", docs[0]).status == 200          # the late one, on the older connection
    assert new.keys() == ["t1:1"] and old.keys() == [] and world.hub.tabs(docs[0]) == 1
    old.close()
    assert new.keys() == ["t1:1"] and world.hub.tabs(docs[0]) == 1
    new.close()


def test_a_connection_opened_again_under_its_id_is_the_newest(world, docs):
    """The same browser comes back under the same id: the stream that replaced the old one takes its keys."""
    other = shared(world, sid="n" * 24)
    first = shared(world)
    first.close()
    again = shared(world)
    assert join(world, "t1:1", docs[0]).status == 200
    assert join(world, "t1:1", docs[0], sid="n" * 24).status == 200   # late, on the older of the two still open
    assert again.keys() == ["t1:1"] and other.keys() == []
    again.close()
    other.close()


@pytest.mark.parametrize("key", [None, 7, ["a"], ""])
def test_a_leave_with_no_stream_of_ours_is_refused_whatever_its_key(world, key):
    assert world.post("/_/live/leave", {"stream": "nope", "key": key}).status == 404


# ── what wakes the connection's writer (ticket 171) ──────────────────────────

def test_an_idle_connection_wakes_its_writer_no_more_than_it_is_asked_to(world, docs, monkeypatch):
    """The writer used to look at every tab's queue 20 times a second. It now waits to be told."""
    from sheafmd.hub import events
    stream = shared(world)
    join(world, "a", docs[0])
    stream.drain()
    looked = []
    real = events.Shared._poll
    monkeypatch.setattr(events.Shared, "_poll", lambda self: looked.append(1) or real(self))
    assert stream.get(timeout=0.5) is None
    assert len(looked) <= 2


def test_an_event_goes_out_when_it_is_published_not_at_the_next_look(world, docs, monkeypatch):
    import threading
    import time
    from sheafmd.hub import events
    monkeypatch.setattr(events.Shared, "POLL_S", 10, raising=False)
    stream = shared(world)
    join(world, "a", docs[0])
    stream.drain()
    got = []

    def wait():
        event = stream.get(timeout=5)
        got.append((time.monotonic(), event))
    t = threading.Thread(target=wait)
    t.start()
    time.sleep(0.2)
    sent = time.monotonic()
    world.hub.entries[docs[0]].bus.publish("changed", {"x": 1})
    t.join(timeout=6)
    at, event = got[0]
    assert event == ("m", {"k": "a", "e": "changed", "d": {"x": 1}})
    assert at - sent < 1


def test_a_join_and_a_refusal_wake_the_writer_too(world, docs):
    import threading
    import time
    stream = shared(world)
    got = []
    t = threading.Thread(target=lambda: got.append(stream.get(timeout=5)))
    t.start()
    time.sleep(0.2)
    start = time.monotonic()
    join(world, "a", docs[0])
    t.join(timeout=6)
    assert got[0] == ("m", {"k": "a", "e": "open", "d": {}})
    assert time.monotonic() - start < 1


def test_a_tab_that_receives_a_burst_does_not_hold_back_the_tabs_that_joined_after_it(world, docs):
    stream = shared(world)
    for key, doc in (("a", docs[0]), ("b", docs[1]), ("c", docs[2])):
        join(world, key, doc)
    stream.drain()
    for n in range(5):
        world.hub.entries[docs[0]].bus.publish("changed", {"n": n})
    world.hub.entries[docs[1]].bus.publish("changed", {"n": 0})
    world.hub.entries[docs[2]].bus.publish("changed", {"n": 0})
    first_three = [d["k"] for _, d in stream.drain()[:3]]
    assert sorted(first_three) == ["a", "b", "c"]


def test_a_closed_connection_still_waits_out_the_timeout_it_is_asked_for(world, docs):
    """The server's writer loop paces itself with `get(timeout=0.25)`: a stream closed from another thread, before
    the loop sees it, must not turn that into a busy loop."""
    import time
    stream = shared(world)
    stream.close()
    start = time.monotonic()
    assert stream.get(timeout=0.3) is None
    assert time.monotonic() - start >= 0.25


def test_a_tab_that_left_no_longer_wakes_the_writer(world, docs):
    stream = shared(world)
    join(world, "a", docs[0])
    sub = world.hub.entries[docs[0]].bus._subs.copy().pop()
    world.post("/_/live/leave", {"stream": SID, "key": "a"})
    assert sub.on_put is None
