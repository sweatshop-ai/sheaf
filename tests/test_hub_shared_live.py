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
