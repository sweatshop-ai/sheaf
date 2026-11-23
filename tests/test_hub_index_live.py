"""The index stream: `GET /_/live` with no document (SPEC 8.6, 8.8). The index moves a dot
without any tab being open on the document: the watcher looks at every listed file every 5 s
while an index stream is open, and a Tell or a save moves it at once. Time is the test's own
clock; one test at the end runs the real server on a real socket."""
import http.client
import os
import threading
import time

import pytest

import sheafmd.comments as rdc
from helpers import NOW, PLAN, browser_on, make_repo, read_events, thread, with_threads
from sheafmd import diagnostics, paths
from sheafmd.agents.base import State
from sheafmd.blocks import split_md_blocks
from sheafmd.hub import events
from sheafmd.hub import index as index_mod
from sheafmd.hub import roots as roots_mod
from sheafmd.hub import server
from sheafmd.hub import state
from sheafmd.hub.core import Hub
from sheafmd.source import md_hash


class Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def clock(world):
    c = Clock()
    world.hub.clock = c
    return c


def open_index(browser):
    r = browser.get("/_/live")
    assert r.status == 200 and r.stream is not None
    return r.stream


def statuses(sub):
    return [d for name, d in sub.drain() if name == "status"]


def edit(f, text, age=0):
    """Write a document so that its (mtime, size) differ from what they were."""
    f.write_text(text, encoding="utf-8")
    os.utime(f, (NOW + 100 - age, NOW + 100 - age))


def look_or_sweep(first: str, world, clock, address: str):
    """What compares the document's row with the board: a look at it, or the next sweep."""
    if first == "a look":
        world.hub.index.touch(address)
    else:
        clock.advance(5)
        world.hub.tick()


# ── the stream ───────────────────────────────────────────────────────────────

def test_the_index_stream_says_hello_and_then_only_what_happens(world):
    r = world.get("/_/live")
    assert r.status == 200 and r.headers["Content-Type"] == "text/event-stream"
    assert r.stream.drain() == [("hello", {"boot": world.hub.boot, "version": world.hub.version,
                                           "service": False})]
    assert r.stream.drain() == []


def test_the_index_stream_is_for_a_browser_that_is_signed_in(world):
    assert world.get("/_/live", cookie=False).status == 401
    assert world.get("/_/live", cookie=False, key=True).status == 403


def test_two_streams_opening_together_start_the_board_once(world):
    """The second would take a board that already holds a change the first was never told of."""
    hub, calls, answers, later = world.hub, [], [], []
    real_arm = hub.index.arm

    def arm():
        calls.append(1)
        if len(calls) == 1:                        # the second stream arrives while this one arms
            later.append(threading.Thread(target=lambda: answers.append(world.get("/_/live"))))
            later[0].start()
            later[0].join(0.5)
        real_arm()

    hub.index.arm = arm
    first = world.get("/_/live")
    later[0].join(5)
    assert not later[0].is_alive(), "the second stream did not finish"
    assert first.status == 200 and [a.status for a in answers] == [200]
    assert len(calls) == 1
    assert hub.index_bus.count() == 2


def test_the_index_stream_is_not_a_document_stream(world, put):
    put("a.md")
    doc = world.get("/_/live?doc=work/a.md").stream
    sub = open_index(world)
    sub.drain()
    world.hub.entry("work/a.md").bus.publish("changed", {"hash": "x"})
    assert doc.drain()[-1][0] == "changed" and sub.drain() == []
    assert world.hub.tabs("work/a.md") == 1          # the index is no tab on any document


def test_a_stop_reaches_the_index_stream(world):
    sub = open_index(world)
    sub.drain()
    world.hub.announce_stop("upgrade")
    assert sub.drain() == [("hub-stopping", {"reason": "upgrade"})]


# ── the watcher (8.6): every listed file, every 5 s, no tab needed ───────────

def test_a_document_nobody_has_open_moves_its_dot_within_five_seconds(world, put, clock):
    sub = open_index(world)
    sub.drain()
    f = put("a.md", with_threads(thread("c1", "Bob")))          # an agent writes a new document
    world.hub.tick()
    clock.advance(4.9)
    world.hub.tick()
    assert statuses(sub) == []                                  # not looked at before 5 s
    clock.advance(0.2)
    world.hub.tick()
    assert statuses(sub) == [{"doc": "work/a.md", "root": "work", "dot": "red", "open": 1,
                              "changed": pytest.approx(f.stat().st_mtime)}]
    edit(f, with_threads(thread("c1", "Bob", "Ada")))           # a reply from the CLI
    clock.advance(5)
    world.hub.tick()
    (got,) = statuses(sub)
    assert (got["doc"], got["dot"], got["open"]) == ("work/a.md", "blue", 1)
    assert world.hub.entries == {}                              # and nothing was opened for it


def test_a_sweep_that_finds_nothing_new_says_nothing(world, put, clock):
    put("a.md", with_threads(thread("c1", "Ada")))
    sub = open_index(world)
    sub.drain()
    for _ in range(4):
        clock.advance(5)
        world.hub.tick()
    assert sub.drain() == []


def test_a_document_that_goes_away_says_so(world, put, clock):
    f = put("a.md")
    sub = open_index(world)
    sub.drain()
    f.unlink()
    clock.advance(5)
    world.hub.tick()
    assert statuses(sub) == [{"doc": "work/a.md", "root": "work", "dot": None, "open": 0,
                              "changed": None}]
    clock.advance(5)
    world.hub.tick()
    assert statuses(sub) == []


def test_a_forgotten_root_takes_its_documents_off_the_index(world, clock):
    sub = open_index(world)
    sub.drain()
    world.hub.forget_root("work")
    clock.advance(5)
    world.hub.tick()
    assert [(d["doc"], d["dot"]) for d in statuses(sub)] == [("work/start.md", None)]


def test_a_new_root_is_announced_by_its_documents(world, tmp_path, clock):
    sub = open_index(world)
    sub.drain()
    new = tmp_path / "fresh"
    new.mkdir()
    (new / "x.md").write_text("# X\n")
    world.hub.roots.for_document(new / "x.md")
    clock.advance(5)
    world.hub.tick()
    assert [(d["doc"], d["root"], d["dot"]) for d in statuses(sub)] == [("fresh/x.md", "fresh", "green")]


# ── nobody looking, nobody looked at ─────────────────────────────────────────

def test_with_no_index_open_the_watcher_does_not_list_anything(world, put, clock, monkeypatch):
    calls = []
    real = roots_mod.list_documents
    monkeypatch.setattr(roots_mod, "list_documents", lambda r: calls.append(r.name) or real(r))
    for _ in range(4):
        clock.advance(5)
        world.hub.tick()
    assert calls == []
    sub = open_index(world)
    assert calls == ["work"]                                    # once, to know where it stands
    sub.close()
    clock.advance(5)
    world.hub.tick()
    assert calls == ["work"]


def test_a_stream_opened_later_is_not_told_what_happened_before(world, put, clock):
    f = put("a.md", with_threads(thread("c1", "Bob")))
    world.hub.tick()
    edit(f, with_threads(thread("c1", "Bob"), thread("c2", "Bob")))
    sub = open_index(world)
    assert [n for n, _ in sub.drain()] == ["hello"]
    clock.advance(5)
    world.hub.tick()
    assert sub.drain() == []


def test_a_second_stream_gets_the_same_events_and_the_last_to_close_ends_the_looking(
        world, put, clock, monkeypatch):
    first, second = open_index(world), open_index(world)
    first.drain(), second.drain()
    put("a.md", with_threads(thread("c1", "Bob")))
    clock.advance(5)
    world.hub.tick()
    assert [d["doc"] for d in statuses(first)] == ["work/a.md"] == [d["doc"] for d in statuses(second)]
    first.close()
    edit(world.hub.roots.resolve("work/a.md"), with_threads(thread("c1", "Ada")))
    clock.advance(5)
    world.hub.tick()
    assert [d["dot"] for d in statuses(second)] == ["blue"]
    second.close()
    calls = []
    monkeypatch.setattr(roots_mod, "list_documents", lambda r: calls.append(1) or roots_mod.Listing([], 0))
    clock.advance(5)
    world.hub.tick()
    assert calls == []


def test_a_sweep_that_fails_is_written_down_and_the_watcher_goes_on(world, put, clock, monkeypatch):
    sub = open_index(world)
    sub.drain()

    def boom(*a):
        raise OSError("disk went away")
    monkeypatch.setattr(roots_mod, "list_documents", boom)
    clock.advance(5)
    world.hub.tick()
    rows = [r for r in diagnostics.read() if r["kind"] == "status-failed"]
    assert rows and "disk went away" in rows[-1]["traceback"]


def test_a_sweep_whose_thread_cannot_start_is_written_down_and_the_next_one_runs(world, put, clock,
                                                                                  monkeypatch):
    sub = open_index(world)
    sub.drain()
    tries = []

    def no_thread_once(run):
        tries.append(1)
        if len(tries) == 1:
            raise RuntimeError("can't start new thread")
        run()
    monkeypatch.setattr(world.hub.index, "_start_sweep", no_thread_once)
    clock.advance(5)
    world.hub.tick()
    rows = [r for r in diagnostics.read() if r["kind"] == "status-failed"]
    assert rows and "can't start new thread" in rows[-1]["traceback"]
    put("a.md", with_threads(thread("c1", "Bob")))
    clock.advance(5)
    world.hub.tick()
    assert len(tries) == 2 and [d["doc"] for d in statuses(sub)] == ["work/a.md"]


# ── what moves a dot at once, without waiting for a sweep ────────────────────

def test_opening_a_thread_on_the_page_turns_the_dot_at_once(world, put):
    put("a.md", with_threads(thread("c1", "Bob")))
    sub = open_index(world)
    sub.drain()
    world.post("/_/seen", {"doc": "work/a.md", "id": "c1", "count": 1})
    (got,) = statuses(sub)
    assert (got["doc"], got["dot"], got["open"]) == ("work/a.md", "blue", 1)


def test_a_comment_written_on_the_page_moves_the_dot_at_once(world, put):
    f = put("a.md")
    sub = open_index(world)
    sub.drain()
    text = f.read_text(encoding="utf-8")
    blk, s, e = rdc.find_quote(text, "Second paragraph")
    r = world.post("/_/comment", {"doc": "work/a.md", "op": "add", "hash": md_hash(text),
                                  "block": blk, "start": s, "end": e, "quote": "Second paragraph",
                                  "body": "Why pears?"})
    assert r.status == 200
    assert [(d["dot"], d["open"]) for d in statuses(sub)] == [("blue", 1)]


def test_resolving_a_thread_on_the_page_moves_the_dot_at_once(world, put):
    f = put("a.md", with_threads(thread("c1", "Ada")))
    sub = open_index(world)
    sub.drain()
    r = world.post("/_/comment", {"doc": "work/a.md", "op": "status", "id": "c1",
                                  "hash": md_hash(f.read_text(encoding="utf-8")),
                                  "status": "resolved"})
    assert r.status == 200
    assert [(d["dot"], d["open"]) for d in statuses(sub)] == [("green", 0)]


def test_a_save_on_the_page_moves_the_last_change_at_once(world, put):
    f = put("a.md", age=500)
    sub = open_index(world)
    sub.drain()
    text = f.read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("Second"))
    r = world.post("/_/save", {"doc": "work/a.md", "hash": md_hash(text),
                               "edits": [{"i": i, "html": "<p>Second, edited.</p>"}]})
    assert r.status == 200
    (got,) = statuses(sub)
    assert got["dot"] == "green" and got["changed"] == pytest.approx(f.stat().st_mtime)
    assert got["changed"] > NOW - 100


def test_a_render_of_a_new_document_announces_it_at_once(world, tmp_path):
    sub = open_index(world)
    sub.drain()
    new = tmp_path / "fresh" / "x.md"
    new.parent.mkdir()
    new.write_text("# X\n")
    world.hub.render(new, {}, None)
    assert [(d["doc"], d["root"], d["dot"]) for d in statuses(sub)] == [("fresh/x.md", "fresh", "green")]


def test_a_page_opened_by_its_address_but_not_listed_is_not_announced_and_not_taken_back(
        world, tmp_path, clock):
    repo = make_repo(tmp_path / "proj")
    (repo / ".gitignore").write_text("drafts/\n")
    (repo / "a.md").write_text("# A\n")
    (repo / "drafts").mkdir()
    (repo / "drafts" / "x.md").write_text("# X\n")
    world.hub.roots.for_document(repo / "a.md")
    sub = open_index(world)
    sub.drain()
    assert world.get("/proj/drafts/x.md").status == 200
    for _ in range(12):
        clock.advance(1)
        world.hub.tick()
    assert statuses(sub) == []


def test_a_tell_that_starts_moves_the_dot_at_the_next_second(world, put, clock, monkeypatch):
    put("a.md", with_threads(thread("c1", "Ada")))
    e = world.hub.entry("work/a.md")
    # The watcher reads the session's state from the adapter every second; this test sets the
    # state itself, so the adapter is not asked (a document with no target reads as none).
    monkeypatch.setattr(world.hub.tell, "observe", lambda entry: None)
    sub = open_index(world)
    sub.drain()
    e.live.await_reply("c1")
    clock.advance(1)
    world.hub.tick()
    assert [d["dot"] for d in statuses(sub)] == ["orange"]
    e.live.observe(State("waiting", "Which one?"))
    clock.advance(1)
    world.hub.tick()
    assert [d["dot"] for d in statuses(sub)] == ["red"]
    e.live.stop_waiting("c1")
    e.live.observe(State("idle"))
    clock.advance(1)
    world.hub.tick()
    assert [d["dot"] for d in statuses(sub)] == ["blue"]


def test_a_document_with_a_tab_open_moves_with_its_tab(world, put, clock):
    f = put("a.md", with_threads(thread("c1", "Ada")))
    tab = world.get("/_/live?doc=work/a.md").stream
    sub = open_index(world)
    tab.drain(), sub.drain()
    edit(f, with_threads(thread("c1", "Ada", "Bob")))
    clock.advance(1)
    world.hub.tick()                                            # no sweep yet: only the tab's second
    assert [n for n, _ in tab.drain()] == ["changed"]
    assert [d["dot"] for d in statuses(sub)] == ["red"]


def test_a_sweep_never_tells_what_a_look_made_while_it_listed_has_overtaken(world, put, clock, tmp_path,
                                                                            monkeypatch):
    """A sweep reads the documents root by root, then says what moved. A thread opened on the page
    while it lists a later root turns the dot at once; the sweep's row, read before, must not turn it
    back."""
    put("a.md", with_threads(thread("c1", "Bob")))
    later = tmp_path / "later"
    later.mkdir()
    (later / "x.md").write_text("# X\n")
    world.hub.roots.for_document(later / "x.md")
    sub = open_index(world)
    sub.drain()
    real = roots_mod.list_documents

    def opened_meanwhile(root):
        if root.name == "later":
            world.post("/_/seen", {"doc": "work/a.md", "id": "c1", "count": 1})
        return real(root)
    monkeypatch.setattr(roots_mod, "list_documents", opened_meanwhile)
    clock.advance(5)
    world.hub.tick()
    assert [(d["doc"], d["dot"]) for d in statuses(sub)] == [("work/a.md", "blue")]


def test_a_sweep_says_nothing_of_a_root_forgotten_while_it_listed(world, put, clock, tmp_path, monkeypatch):
    """A root forgotten while the sweep lists a later one, and its name taken by another folder: the
    rows the sweep read are the old folder's, and would be told under the name the other folder
    holds now. The next sweep tells what that folder holds, and that the old one's other file is gone."""
    f = put("a.md", with_threads(thread("c1", "Ada")))
    later = tmp_path / "later"
    later.mkdir()
    (later / "x.md").write_text("# X\n")
    world.hub.roots.for_document(later / "x.md")
    other = tmp_path / "y" / "work"
    other.mkdir(parents=True)
    (other / "a.md").write_text("# Another document\n")
    sub = open_index(world)
    sub.drain()
    edit(f, with_threads(thread("c1", "Ada"), thread("c2", "Ada")))    # the old folder's row is news
    real = roots_mod.list_documents

    def forgotten_meanwhile(root):
        if root.name == "later":
            assert world.hub.forget_root("work").name == "work"
            assert world.hub.roots.address(other / "a.md") == "work/a.md"
        return real(root)
    monkeypatch.setattr(roots_mod, "list_documents", forgotten_meanwhile)
    clock.advance(5)
    world.hub.tick()
    assert [d for d in statuses(sub) if d["doc"].startswith("work/")] == []
    monkeypatch.setattr(roots_mod, "list_documents", real)
    clock.advance(5)
    world.hub.tick()
    assert sorted((d["doc"], d["dot"]) for d in statuses(sub)) == [("work/a.md", "green"),
                                                                    ("work/start.md", None)]


def test_a_look_says_nothing_of_a_root_forgotten_while_it_read_the_row(world, put, clock, tmp_path,
                                                                     monkeypatch):
    """A look (a save, a thread opened, a render) reads its document's row and then tells the indexes.
    A forget in between, and the name taken by another folder: the row is the old folder's, and would
    be told under the name the other folder holds now. The next sweep tells what that folder holds."""
    f = put("a.md", with_threads(thread("c1", "Ada")))
    other = tmp_path / "y" / "work"
    other.mkdir(parents=True)
    (other / "a.md").write_text("# Another document\n")
    sub = open_index(world)
    sub.drain()
    edit(f, with_threads(thread("c1", "Ada"), thread("c2", "Ada")))    # the old folder's row is news
    index, real = world.hub.index, world.hub.index._row

    def forgotten_meanwhile(*a, **k):
        row = real(*a, **k)
        monkeypatch.setattr(index, "_row", real)
        assert world.hub.forget_root("work").name == "work"
        assert world.hub.roots.address(other / "a.md") == "work/a.md"
        return row
    monkeypatch.setattr(index, "_row", forgotten_meanwhile)
    index.touch("work/a.md")
    assert statuses(sub) == []
    clock.advance(5)
    world.hub.tick()
    assert sorted((d["doc"], d["dot"]) for d in statuses(sub)) == [("work/a.md", "green"),
                                                                    ("work/start.md", None)]


@pytest.mark.parametrize("first", ["a look", "a sweep"])
def test_events_reach_the_stream_in_the_order_the_board_took_them(first, world, put, clock, monkeypatch):
    """A look or a sweep compares its rows with the board under the index's lock and sends the events
    after it, outside the lock. A thread opened on the page while the first is between the two
    compares later: its event must not reach the stream first, or the page keeps the older dot that
    the board no longer holds, until the next change."""
    f = put("a.md", with_threads(thread("c1", "Bob")))
    sub = open_index(world)
    sub.drain()
    edit(f, with_threads(thread("c1", "Bob")) + "\nA line more.\n")     # the first one's news: red, moved
    bus, real = world.hub.index_bus, world.hub.index_bus.publish

    def opened_meanwhile(name, data):
        monkeypatch.setattr(bus, "publish", real)
        later = threading.Thread(target=world.post,
                                 args=("/_/seen", {"doc": "work/a.md", "id": "c1", "count": 1}))
        later.start()
        later.join(5)
        assert not later.is_alive()
        real(name, data)
    monkeypatch.setattr(bus, "publish", opened_meanwhile)
    look_or_sweep(first, world, clock, "work/a.md")
    assert [(d["doc"], d["dot"]) for d in statuses(sub)] == [("work/a.md", "red"), ("work/a.md", "blue")]
    assert world.hub.index._board["work/a.md"][0] == "blue"


@pytest.mark.parametrize("first", ["a look", "a sweep"])
def test_a_root_forgotten_after_the_comparison_and_before_the_send_is_not_told(first, world, put, clock,
                                                                                tmp_path, monkeypatch):
    """The board took the old folder's row, and the root is forgotten and its name taken by another
    folder before the event goes out: it is not sent, and the next sweep tells what that folder
    holds, and that the old one's other file is gone."""
    f = put("a.md", with_threads(thread("c1", "Ada")))
    other = tmp_path / "y" / "work"
    other.mkdir(parents=True)
    (other / "a.md").write_text("# Another document\n")
    sub = open_index(world)
    sub.drain()
    edit(f, with_threads(thread("c1", "Ada"), thread("c2", "Ada")))    # the old folder's row is news
    index, real = world.hub.index, world.hub.index._publish

    def forgotten_meanwhile(*a, **k):
        monkeypatch.setattr(index, "_publish", real)
        assert world.hub.forget_root("work").name == "work"
        assert world.hub.roots.address(other / "a.md") == "work/a.md"
        return real(*a, **k)
    monkeypatch.setattr(index, "_publish", forgotten_meanwhile)
    look_or_sweep(first, world, clock, "work/a.md")
    assert [d for d in statuses(sub) if d["doc"].startswith("work/")] == []
    clock.advance(5)
    world.hub.tick()
    assert sorted((d["doc"], d["dot"]) for d in statuses(sub)) == [("work/a.md", "green"),
                                                                    ("work/start.md", None)]


@pytest.mark.parametrize("first", ["a look", "a sweep"])
def test_a_forgotten_roots_document_whose_event_was_held_back_is_told_gone_at_the_next_sweep(
        first, world, clock, tmp_path, monkeypatch):
    """The event not sent leaves the open indexes with the old row: the board must not forget that
    they hold it. When no folder takes the name, the next sweep says the document is gone."""
    solo = tmp_path / "solo"
    solo.mkdir()
    f = solo / "x.md"
    f.write_text(with_threads(thread("c1", "Ada")), encoding="utf-8")
    world.hub.roots.for_document(f)
    sub = open_index(world)
    sub.drain()
    edit(f, with_threads(thread("c1", "Ada"), thread("c2", "Ada")))    # the old row is news
    index, real = world.hub.index, world.hub.index._publish

    def forgotten_meanwhile(*a, **k):
        monkeypatch.setattr(index, "_publish", real)
        assert world.hub.forget_root("solo").name == "solo"
        return real(*a, **k)
    monkeypatch.setattr(index, "_publish", forgotten_meanwhile)
    look_or_sweep(first, world, clock, "solo/x.md")
    assert statuses(sub) == []
    clock.advance(5)
    world.hub.tick()
    assert [(d["doc"], d["dot"]) for d in statuses(sub)] == [("solo/x.md", None)]


def test_a_look_that_is_sending_leaves_the_sweeps_events_to_the_sweeps_thread(world, put, monkeypatch):
    """The watcher's pass never waits for a sweep (8.6), and a request is not held by one: a look
    whose event is going out when a sweep queues its own does not send the sweep's (each one goes
    through every member's stream). The sweep's thread sends them, after the look's."""
    f, g = put("a.md", with_threads(thread("c1", "Bob"))), put("b.md")
    sub = open_index(world)
    sub.drain()
    edit(f, with_threads(thread("c1", "Bob")) + "\nA line more.\n")     # the look's news
    edit(g, "# B, moved\n")                                             # the sweep's news
    index, bus, real = world.hub.index, world.hub.index_bus, world.hub.index_bus.publish
    before, senders = index._board["work/b.md"], []
    sweep = threading.Thread(target=index.sweep, name="the sweep")

    def sending(name, data):
        senders.append((data["doc"], threading.current_thread().name))
        if len(senders) == 1:
            sweep.start()
            deadline = time.time() + 5
            while index._board["work/b.md"] == before and time.time() < deadline:    # the sweep compared
                time.sleep(0.01)
        real(name, data)
    monkeypatch.setattr(bus, "publish", sending)
    index.touch("work/a.md")
    sweep.join(5)
    assert not sweep.is_alive()
    assert senders == [("work/a.md", threading.current_thread().name), ("work/b.md", "the sweep")]
    assert [d["doc"] for d in statuses(sub)] == ["work/a.md", "work/b.md"]


def test_a_look_after_a_forget_still_tells_what_the_folder_that_took_the_name_holds(world, put, tmp_path):
    """The control: a look that begins after the forget reads the other folder's row, and tells it."""
    put("a.md", with_threads(thread("c1", "Ada")))
    other = tmp_path / "y" / "work"
    other.mkdir(parents=True)
    (other / "a.md").write_text(with_threads(thread("c1", "Bo"), thread("c2", "Bo")))
    sub = open_index(world)
    sub.drain()
    assert world.hub.forget_root("work").name == "work"
    assert world.hub.roots.address(other / "a.md") == "work/a.md"
    world.hub.index.touch("work/a.md")
    assert [(d["doc"], d["dot"], d["open"]) for d in statuses(sub)] == [("work/a.md", "red", 2)]


@pytest.mark.parametrize("first", ["a look", "a sweep"])
def test_a_send_that_fails_leaves_the_document_to_be_told_at_the_next_look(first, world, put, clock,
                                                                           monkeypatch):
    """The board took the news and the bus refused it: no stream was told, so the board must not
    claim they were, or the document stays as the open indexes last showed it until it moves again."""
    f = put("a.md", with_threads(thread("c1", "Bob")))
    sub = open_index(world)
    sub.drain()
    edit(f, with_threads(thread("c1", "Bob")) + "\nA line more.\n")     # red, moved
    bus, real = world.hub.index_bus, world.hub.index_bus.publish

    def refuses(name, data):
        raise OSError("the bus went away")
    monkeypatch.setattr(bus, "publish", refuses)
    look_or_sweep(first, world, clock, "work/a.md")
    assert statuses(sub) == []
    assert [r for r in diagnostics.read() if r["kind"] == "status-failed"]
    monkeypatch.setattr(bus, "publish", real)
    clock.advance(5)
    world.hub.index.sweep()
    assert [(d["doc"], d["dot"]) for d in statuses(sub)] == [("work/a.md", "red")]


def test_a_send_of_a_deletion_that_fails_is_told_at_the_next_sweep(world, put, clock, monkeypatch):
    """The same for a document that is gone: the board dropped it, no stream was told, and the next
    sweep must still say so."""
    f = put("a.md")
    put("b.md")
    sub = open_index(world)
    sub.drain()
    f.unlink()
    bus, real = world.hub.index_bus, world.hub.index_bus.publish

    def refuses(name, data):
        raise OSError("the bus went away")
    monkeypatch.setattr(bus, "publish", refuses)
    world.hub.index.sweep()
    assert statuses(sub) == []
    monkeypatch.setattr(bus, "publish", real)
    world.hub.index.sweep()
    assert [(d["doc"], d["dot"]) for d in statuses(sub)] == [("work/a.md", None)]


def test_a_failed_move_is_told_again_though_a_dot_only_event_followed_it(world, put, clock, monkeypatch):
    """E1 (the file moved) fails while E2 (only the dot moved: the person read a thread) is queued
    behind it. A member's stream is sent only events of a file that moved, so E2 does not make up for
    E1: the document is told again at the next sweep, with the file marked as moved."""
    f = put("a.md", with_threads(thread("c1", "Bob")))
    sub = open_index(world)
    sub.drain()
    edit(f, with_threads(thread("c1", "Bob")) + "\nA line more.\n")     # E1: red, moved
    bus, real = world.hub.index_bus, world.hub.index_bus.publish

    def refuses_after_a_read(name, data):
        monkeypatch.setattr(bus, "publish", real)
        world.post("/_/seen", {"doc": "work/a.md", "id": "c1", "count": 1})    # E2: blue, not moved
        raise OSError("the bus went away")
    monkeypatch.setattr(bus, "publish", refuses_after_a_read)
    world.hub.index.touch("work/a.md")
    sent = statuses(sub)
    assert [(d["doc"], d["dot"], d.files) for d in sent] == [("work/a.md", "blue", False)]
    world.hub.index.sweep()
    assert [(d["doc"], d["dot"], d.files) for d in statuses(sub)] == [("work/a.md", "blue", True)]


def test_a_failed_deletion_is_not_planted_in_a_board_started_afresh(world, put, clock, monkeypatch):
    """The board was taken again while the deletion was going out: the new stream's page never listed
    the document, so the next sweep must not tell it gone."""
    f = put("a.md")
    put("b.md")
    sub = open_index(world)
    sub.drain()
    f.unlink()
    index, bus = world.hub.index, world.hub.index_bus

    def refuses_after_arm(name, data):
        index.arm()
        raise OSError("the bus went away")
    monkeypatch.setattr(bus, "publish", refuses_after_arm)
    index.sweep()
    assert "work/a.md" not in index._board
    monkeypatch.undo()
    index.sweep()
    assert statuses(sub) == []


def test_a_sweep_that_raises_while_queueing_still_sends_what_it_queued(world, put, clock, monkeypatch):
    """The sweep's events at the head of the queue stop the looks, which leave them to the sweep's
    thread. A sweep that raised after queueing part of them must send that part, or the looks'
    events wait for the next sweep."""
    f, g, h = put("a.md"), put("b.md"), put("c.md")
    sub = open_index(world)
    sub.drain()
    edit(f, "# A, moved\n")
    edit(g, "# B, moved\n")
    index, real = world.hub.index, world.hub.index._event
    told = []

    def event(address, *a):
        told.append(address)
        if len(told) == 2:
            raise ValueError("no event for the second")
        return real(address, *a)
    monkeypatch.setattr(index, "_event", event)
    with pytest.raises(ValueError):
        index.sweep()
    monkeypatch.setattr(index, "_event", real)
    edit(h, "# C, moved\n")
    index.touch("work/c.md")
    assert [d["doc"] for d in statuses(sub)] == ["work/a.md", "work/c.md"]
    index.sweep()
    assert [d["doc"] for d in statuses(sub)] == ["work/b.md"]       # the one it could not queue


# ── a member's index stream (9.9) ────────────────────────────────────────────

def test_the_watchers_pass_reads_each_documents_live_state_once(world, put, clock):
    """Each look reads the state of its own document: a pass over N documents reads N, not N times N."""
    names = ["a.md", "b.md", "c.md", "d.md"]
    for n in names:
        put(n)
    entries = [world.hub.entry("work/" + n) for n in names]
    sub = open_index(world)
    sub.drain()
    reads = []
    for e in entries:
        real = e.live.peek
        e.live.peek = lambda real=real: reads.append(1) or real()
    clock.advance(1)
    world.hub.tick()
    assert len(reads) == len(names)


def test_a_root_forgotten_while_the_watchers_pass_goes_through_the_documents_does_not_colour_the_new_folders_row(
        world, put, clock, tmp_path, monkeypatch):
    """The watcher's pass reads which documents wait or run, and then looks at each one the hub holds.
    A forget inside that loop, and the name taken by another folder, and the old folder's Tell is
    still what the pass holds: the new folder's row would be coloured with it. Each look reads that
    state after it began."""
    put("a.md", with_threads(thread("c1", "Ada")))
    put("b.md")
    other = tmp_path / "y" / "work"
    other.mkdir(parents=True)
    (other / "a.md").write_text("# Another document\n")
    hub = world.hub
    hub.entry("work/b.md")
    e = hub.entry("work/a.md")
    monkeypatch.setattr(hub.tell, "observe", lambda entry: None)
    sub = open_index(world)
    sub.drain()
    e.live.await_reply("c1")                            # a Tell runs on the old folder's a.md
    index, real = hub.index, hub.index.touch

    def forgotten_meanwhile(address, *a, **k):
        if address == "work/b.md":                      # the pass has read the state, and looks at b.md
            monkeypatch.setattr(index, "touch", real)
            assert hub.forget_root("work").name == "work"
            assert hub.roots.address(other / "a.md") == "work/a.md"
        return real(address, *a, **k)
    monkeypatch.setattr(index, "touch", forgotten_meanwhile)
    clock.advance(1)
    hub.tick()
    assert [d["dot"] for d in statuses(sub) if d["doc"] == "work/a.md"] == ["green"]


@pytest.mark.parametrize("first", ["a look", "a sweep"])
@pytest.mark.parametrize("who", ["the hub's person", "a member"])
def test_a_root_forgotten_after_an_event_left_the_queue_is_not_told_to_the_stream_that_takes_it_later(
        who, first, world, put, front, clock, tmp_path, monkeypatch):
    """The event is handed to the streams one by one, and a member's stream judges it when it reads
    it. A forget, and the name taken by another folder, after it left the queue and before a stream
    took it: that stream is sent nothing of the old folder's row."""
    f = put("a.md", with_threads(thread("c1", "Ada")))
    other = tmp_path / "y" / "work"
    other.mkdir(parents=True)
    (other / "a.md").write_text("# Another document\n")
    sub = open_index(front if who == "a member" else world)
    sub.drain()
    edit(f, with_threads(thread("c1", "Ada"), thread("c2", "Ada")))    # the old folder's row is news
    bus, real = world.hub.index_bus, world.hub.index_bus.publish

    def forgotten_meanwhile(name, data):
        monkeypatch.setattr(bus, "publish", real)
        real(name, data)                                # the stream has it in its queue
        assert world.hub.forget_root("work").name == "work"
        assert world.hub.roots.address(other / "a.md") == "work/a.md"
    monkeypatch.setattr(bus, "publish", forgotten_meanwhile)
    look_or_sweep(first, world, clock, "work/a.md")
    assert [d for d in statuses(sub) if d["doc"] == "work/a.md"] == []
    if who == "the hub's person":
        clock.advance(5)
        world.hub.tick()
        assert sorted((d["doc"], d["dot"]) for d in statuses(sub)) == [("work/a.md", "green"),
                                                                        ("work/start.md", None)]


def test_a_root_forgotten_while_a_members_stream_judges_an_event_is_not_told_to_that_stream(
        world, put, front, tmp_path, monkeypatch):
    """The member's stream asks whether the document is theirs, which can ask git: a forget, and the
    name taken by another folder, during that question leaves the answer about the old folder's row."""
    f = put("a.md", with_threads(thread("c1", "Ada")))
    other = tmp_path / "y" / "work"
    other.mkdir(parents=True)
    (other / "a.md").write_text("# Another document\n")
    hub = world.hub
    mine = open_index(front)
    mine.drain()
    edit(f, with_threads(thread("c1", "Ada"), thread("c2", "Ada")))
    hub.index.touch("work/a.md")                        # the event waits in the member's queue
    real = hub.member_owns

    def forgotten_meanwhile(member, address):
        monkeypatch.setattr(hub, "member_owns", real)
        theirs = real(member, address)
        assert hub.forget_root("work").name == "work"
        assert hub.roots.address(other / "a.md") == "work/a.md"
        return theirs
    monkeypatch.setattr(hub, "member_owns", forgotten_meanwhile)
    assert statuses(mine) == []


def test_a_forget_is_remembered_by_a_look_that_reads_on_while_a_sweep_begins_and_ends(
        world, put, clock, tmp_path, monkeypatch):
    """`_forgot_at` stays after a sweep ends (which trims what it kept of the looks): a look that
    began before the forget and ends after the sweep is still told nothing of the old folder's row."""
    f = put("a.md", with_threads(thread("c1", "Ada")))
    other = tmp_path / "y" / "work"
    other.mkdir(parents=True)
    (other / "a.md").write_text("# Another document\n")
    sub = open_index(world)
    sub.drain()
    edit(f, with_threads(thread("c1", "Ada"), thread("c2", "Ada")))
    index, real = world.hub.index, world.hub.index._row

    def forgotten_meanwhile(*a, **k):
        row = real(*a, **k)
        monkeypatch.setattr(index, "_row", real)
        assert world.hub.forget_root("work").name == "work"
        assert world.hub.roots.address(other / "a.md") == "work/a.md"
        clock.advance(5)
        world.hub.tick()                                # a sweep begins and ends inside the look
        sub.drain()
        return row
    monkeypatch.setattr(index, "_row", forgotten_meanwhile)
    index.touch("work/a.md")
    assert statuses(sub) == []
    assert index._board["work/a.md"][0] == "green"      # the board holds the new folder's row


def test_a_forget_is_remembered_by_a_look_that_reads_on_while_the_board_is_started_afresh(
        world, put, tmp_path, monkeypatch):
    """The last stream closes and a first one opens (`arm`) while a look reads: the board is taken
    again, and the look is still told nothing of the folder that held the name when it began."""
    f = put("a.md", with_threads(thread("c1", "Ada")))
    other = tmp_path / "y" / "work"
    other.mkdir(parents=True)
    (other / "a.md").write_text("# Another document\n")
    sub = open_index(world)
    sub.drain()
    edit(f, with_threads(thread("c1", "Ada"), thread("c2", "Ada")))
    index, real = world.hub.index, world.hub.index._row
    later = []

    def forgotten_meanwhile(*a, **k):
        row = real(*a, **k)
        monkeypatch.setattr(index, "_row", real)
        assert world.hub.forget_root("work").name == "work"
        assert world.hub.roots.address(other / "a.md") == "work/a.md"
        sub.close()
        later.append(open_index(world))                 # the first stream of a board started afresh
        later[0].drain()
        return row
    monkeypatch.setattr(index, "_row", forgotten_meanwhile)
    index.touch("work/a.md")
    assert statuses(later[0]) == []
    assert index._board["work/a.md"][0] == "green"


def test_a_members_stream_slow_to_judge_an_event_holds_no_look_no_sweep_and_no_other_stream(
        world, put, front, clock, monkeypatch):
    """A member's index stream asks whether each document is theirs, which can ask git for seconds.
    Asked on the thread that sends, that held the look's request, every index event queued behind
    it and the next sweep. Each stream judges what it is sent when it reads it, on its own thread."""
    f, g, h = put("a.md"), put("b.md"), put("c.md")
    hub = world.hub
    mine, own = open_index(front), open_index(world)
    mine.drain()
    own.drain()
    real, judging, release = hub.member_owns, threading.Event(), threading.Event()

    def slow(member, address):
        if not judging.is_set():
            judging.set()
            release.wait(10)
        return real(member, address)
    monkeypatch.setattr(hub, "member_owns", slow)
    got = []
    first = threading.Thread(target=hub.index.touch, args=("work/a.md",), name="the first look")
    reader = threading.Thread(target=lambda: got.append(mine.get(timeout=10)), name="the member's stream")
    edit(f, "# A, moved\n")
    try:
        first.start()
        reader.start()
        assert judging.wait(5)                          # the member's stream is judging a.md's event
        first.join(5)
        assert not first.is_alive()                     # the look sent it, and was not held
        edit(g, "# B, moved\n")
        hub.index.touch("work/b.md")                    # a second look
        edit(h, "# C, moved\n")
        clock.advance(5)
        hub.tick()                                      # and a sweep
        assert [d["doc"] for d in statuses(own)] == ["work/a.md", "work/b.md", "work/c.md"]
        assert got == []                                # still judging
    finally:
        release.set()
        first.join(5)
        reader.join(5)
    assert not first.is_alive() and not reader.is_alive(), "the judging request and the reader did not finish after the release"
    assert got == [("status", {"doc": "work/a.md", "root": "work"})]
    assert statuses(mine) == [{"doc": "work/b.md", "root": "work"}, {"doc": "work/c.md", "root": "work"}]


def finished(fn, *args, within=5):
    """Runs `fn(*args)` on a thread of its own: (whether it returned within `within` seconds, what it
    returned). One that is still waiting is left to end once what holds it lets go."""
    out = []
    t = threading.Thread(target=lambda: out.append(fn(*args)), name=getattr(fn, "__name__", "a call"), daemon=True)
    t.start()
    t.join(within)
    return not t.is_alive(), out[0] if out else None


def test_a_members_stream_waiting_on_git_holds_no_look_no_sweep_no_page_and_no_other_lookup(
        world, put, front, clock, monkeypatch):
    """A member's stream judges an event by the root 8.2 finds for its file (`Roots.lookup`), which asks
    git, for up to 5 s twice. Asked under the registry's lock, that held everything that reads the
    registry: the registry's `get`, which every request makes, a look at another document, the sweep and
    a page's entry. The registry is read under its lock, and git asked outside it."""
    f, g, h = put("a.md"), put("b.md"), put("c.md")
    hub = world.hub
    mine, own = open_index(front), open_index(world)
    mine.drain()
    own.drain()
    real, judging, release = roots_mod._git_place, threading.Event(), threading.Event()

    def held(*args):
        if threading.current_thread().name == "the member's stream" and not judging.is_set():
            judging.set()
            release.wait(60)
        return real(*args)
    monkeypatch.setattr(roots_mod, "_git_place", held)
    got, waited = [], []
    reader = threading.Thread(target=lambda: got.append(mine.get(timeout=10)), name="the member's stream")
    edit(f, "# A, moved\n")
    hub.index.touch("work/a.md")
    try:
        reader.start()
        assert judging.wait(5)                          # the member's stream is in git, judging a.md's event
        done, root = finished(hub.roots.get, "work")
        if not (done and root.name == "work"):
            waited.append("the registry's get")
        edit(g, "# B, moved\n")
        if not finished(hub.index.touch, "work/b.md")[0]:
            waited.append("a look")
        edit(h, "# C, moved\n")
        clock.advance(5)
        if not finished(hub.tick)[0]:
            waited.append("the sweep")
        done, e = finished(hub.entry, "work/start.md", within=10)
        if not (done and e.address == "work/start.md"):
            waited.append("a page's entry")
        assert waited == [], "these waited for the member's git"
        assert [d["doc"] for d in statuses(own)] == ["work/a.md", "work/b.md", "work/c.md"]
        assert got == []                                # still in git
    finally:
        release.set()
        reader.join(5)
    assert not reader.is_alive(), "the reader did not finish after the release"
    assert got == [("status", {"doc": "work/a.md", "root": "work"})]
    assert statuses(mine) == [{"doc": "work/b.md", "root": "work"}, {"doc": "work/c.md", "root": "work"}]


def test_a_members_index_stream_is_sent_only_their_documents_in_the_order_the_board_took_them(
        world, put, front, other, clock):
    """The control: judged when the stream reads them, a member's events are what they were, in the
    board's order, while the hub's person is told of every root."""
    f, g = put("a.md"), put("b.md")
    n = other / "notes.md"
    n.write_text(PLAN, encoding="utf-8")
    world.hub.roots.for_document(n)
    mine, own = open_index(front), open_index(world)
    mine.drain()
    own.drain()
    edit(f, with_threads(thread("c1", "Bob")))
    edit(n, with_threads(thread("c1", "Bob")))
    world.hub.index.touch("work/a.md")
    world.hub.index.touch("other/notes.md")
    edit(g, "# B, moved\n")
    clock.advance(5)
    world.hub.tick()
    assert [d["doc"] for d in statuses(own)] == ["work/a.md", "other/notes.md", "work/b.md"]
    assert statuses(mine) == [{"doc": "work/a.md", "root": "work"}, {"doc": "work/b.md", "root": "work"}]


def test_a_members_stream_that_fails_to_judge_an_event_writes_it_down_and_goes_on(
        world, put, front, monkeypatch):
    """The control: a failure to judge one event is written down, the member is told nothing of that
    document, and the next event reaches them."""
    f, g = put("a.md"), put("b.md")
    hub = world.hub
    mine = open_index(front)
    mine.drain()
    real = hub.member_owns

    def fails_on_a(member, address):
        if address == "work/a.md":
            raise RuntimeError("git fell over")
        return real(member, address)
    monkeypatch.setattr(hub, "member_owns", fails_on_a)
    edit(f, "# A, moved\n")
    hub.index.touch("work/a.md")
    edit(g, "# B, moved\n")
    hub.index.touch("work/b.md")
    assert statuses(mine) == [{"doc": "work/b.md", "root": "work"}]
    rows = [r for r in diagnostics.read() if r["kind"] == "status-failed"]
    assert [r["doc"] for r in rows] == ["work/a.md"] and "git fell over" in rows[0]["traceback"]


def test_a_stream_read_with_a_timeout_skips_what_it_is_not_sent_and_waits_for_what_it_is():
    """The control: the server reads a stream with `get(timeout=0.25)`. An event the stream refuses
    is no answer: the wait goes on to the next one it is sent, within the same timeout."""
    bus = events.Bus()
    sub = bus.subscribe(accept=lambda name, data: None if name == "refused" else data)
    bus.publish("refused", {})
    later = threading.Timer(0.2, bus.publish, args=("status", {"doc": "work/a.md"}))
    later.start()
    try:
        assert sub.get(timeout=5) == ("status", {"doc": "work/a.md"})
        bus.publish("refused", {})
        t0 = time.monotonic()
        assert sub.get(timeout=0.3) is None and time.monotonic() - t0 >= 0.25
        assert sub.drain() == []
    finally:
        later.cancel()


# ── over a real socket ───────────────────────────────────────────────────────

def test_a_slow_listing_does_not_hold_the_watchers_pass(work, monkeypatch):
    """Listing a root can take git up to 20 s. Made on the watcher's thread, that held the pass that
    gives up on Tell waits and catches open pages up with their files (8.9)."""
    monkeypatch.setattr(index_mod, "SWEEP_SECONDS", 0.5)
    sock = server.bind(0)
    hub = Hub(port=sock.getsockname()[1], key=paths.ensure_key(), started_by="test")
    hub.tell_wait = 1
    f = work / "a.md"
    f.write_text(with_threads(thread("c1", "Bob")), encoding="utf-8")
    hub.roots.for_document(f)
    e = hub.entry("work/a.md")
    real, listing, release = roots_mod.list_documents, threading.Event(), threading.Event()

    def slow(root):
        if hub.index_bus.count() and threading.current_thread() is not threading.main_thread():
            listing.set()                                       # a sweep, not the stream's first look
            release.wait(30)
        return real(root)
    monkeypatch.setattr(roots_mod, "list_documents", slow)
    sub = open_index(browser_on(hub))
    srv = server.HubServer(hub, sock)
    srv.start()
    try:
        assert listing.wait(10)
        assert e.live.await_reply("c1")
        deadline = time.monotonic() + 5
        while e.live.waiting() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert e.live.waiting() == []
    finally:
        release.set()
        sub.close()
        srv.close()


def test_the_index_stream_works_over_a_real_socket(work, monkeypatch):
    monkeypatch.setattr(index_mod, "SWEEP_SECONDS", 0.5)
    sock = server.bind(0)
    port = sock.getsockname()[1]
    hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    f = work / "a.md"
    f.write_text(PLAN, encoding="utf-8")
    hub.roots.for_document(f)
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        c.request("GET", "/_/live", headers={"Cookie": f"{hub.auth.cookie_name}={hub.auth.cookie_value()}"})
        r = c.getresponse()
        assert r.status == 200 and r.getheader("Content-Type") == "text/event-stream"
        assert r.fp.readline() == b"retry: 2000\n" and r.fp.readline() == b"\n"
        (hello,) = read_events(r, 1)
        assert hello[0] == "hello" and hello[1]["boot"] == hub.boot
        edit(f, with_threads(thread("c1", "Bob")))              # written by someone else, no tab open
        (got,) = read_events(r, 1)
        assert got[0] == "status" and got[1]["doc"] == "work/a.md" and got[1]["dot"] == "red"
        assert hub.entries == {}
    finally:
        c.close()
        srv.close()


def test_a_render_with_new_settings_does_not_hold_the_hubs_lock_while_the_page_is_rebuilt(world, put, work):
    f = put("a.md")
    world.hub.render(f, {"title": "One"}, None)
    e = world.hub.entry("work/a.md")
    renderer, release = threading.Event(), threading.Event()

    def rebuilding(*a, **k):
        renderer.set()
        release.wait(15)
    e.live.rebuild = rebuilding
    rendering = threading.Thread(target=lambda: world.hub.render(f, {"title": "Two"}, None), daemon=True)
    rendering.start()
    try:
        assert renderer.wait(5)
        assert world.hub._lock.acquire(timeout=3), "the hub's lock is held while the page is rebuilt"
        world.hub._lock.release()
    finally:
        release.set()
        rendering.join(5)
    assert not rendering.is_alive()


def test_a_render_that_takes_in_a_write_from_disk_does_not_hold_the_hubs_lock_meanwhile(lock_order, world, put):
    """Ticket 182 P: a render of a document written on disk since takes the write in (a refresh, which can render the page)
    with the hub's lock let go, as its rebuild does."""
    f = put("a.md")
    world.hub.render(f, {"title": "One"}, None)
    e = world.hub.entry("work/a.md")
    edit(f, "# Written on disk since\n")
    refreshing, release = threading.Event(), threading.Event()

    def refresh(*a, **k):
        refreshing.set()
        release.wait(15)
    e.live.refresh = refresh
    rendering = threading.Thread(target=lambda: world.hub.render(f, {"title": "One"}, None), daemon=True)
    rendering.start()
    try:
        assert refreshing.wait(5)
        assert world.hub._lock.acquire(timeout=3), "the hub's lock is held while the write on disk is taken in"
        world.hub._lock.release()
    finally:
        release.set()
        rendering.join(5)
    assert not rendering.is_alive()


def test_a_render_whose_page_is_deleted_between_its_locks_says_so_and_tells_no_change_after_gone(lock_order, world, put, monkeypatch):
    """Ticket 182 R: a delete between the part of a render under the hub's lock and its rebuild leaves no file to read. The
    render says the page went away (not a raw FileNotFoundError), and the page open on it hears nothing after `gone`."""
    from sheafmd.render import RenderError
    f = put("a.md")
    world.hub.render(f, {"title": "One"}, None)
    e = world.hub.entry("work/a.md")
    sub = e.bus.subscribe()
    sub.drain()
    original = world.hub._render_entry

    def then_deleted(*a, **k):
        got = original(*a, **k)
        f.unlink()
        world.hub.forget_document("work/a.md")
        return got
    monkeypatch.setattr(world.hub, "_render_entry", then_deleted)
    with pytest.raises(RenderError, match="went away"):
        world.hub.render(f, {"title": "Two"}, None)
    names = [name for name, _ in sub.drain()]
    assert "gone" in names and "changed" not in names[names.index("gone"):], names


def test_a_write_that_a_refresh_could_not_decide_is_taken_in_on_the_next_tick(world, put):
    """Ticket 183 AO: a refresh that cannot stat the file it read keeps what the tabs hold and comes back later. The watcher
    must come back: the file's (mtime, size) are not marked as seen, so the next tick refreshes the unchanged file again."""
    f = put("a.md")
    e = world.hub.entry("work/a.md")
    sub = e.bus.subscribe()
    world.hub.tick()
    sub.drain()
    edit(f, "# Written on disk since\n")
    real, undecided = e.live._stamp, [True]

    def stamp():
        if undecided:
            undecided.pop()
            return None         # the file cannot be stat-ed this once (a name the hub cannot decide now)
        return real()
    e.live._stamp = stamp
    world.hub.tick()
    assert "changed" not in [name for name, _ in sub.drain()]
    world.hub.tick()
    assert "changed" in [name for name, _ in sub.drain()]


def test_a_render_whose_root_is_forgotten_while_the_page_is_rebuilt_makes_no_entry_again(world, put):
    f = put("a.md")
    world.hub.render(f, {"title": "One"}, None)
    e = world.hub.entry("work/a.md")
    e.live.rebuild = lambda: world.hub.forget_root("work")
    world.hub.render(f, {"title": "Two"}, None)
    assert "work/a.md" not in world.hub.entries


# ── a forget does not wait for a render under the hub's lock (SPEC 8.2) ─────────

def _holding(live):
    """A thread that holds the document's lock, as a render does, until `release` is set."""
    held, release = threading.Event(), threading.Event()

    def run():
        with live.exclusive():
            held.set()
            release.wait(15)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    assert held.wait(5)
    return t, release


def _forgetting(hub, name):
    t = threading.Thread(target=lambda: hub.forget_root(name), daemon=True)
    t.start()
    return t


def _until(check, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not check():
        time.sleep(0.01)
    return check()


def test_a_forget_does_not_hold_the_hubs_lock_while_a_render_of_its_document_runs(world, put):
    put("a.md")
    e = world.hub.entry("work/a.md")
    renderer, release = _holding(e.live)
    forgetting = _forgetting(world.hub, "work")
    try:
        assert _until(lambda: "work/a.md" not in world.hub.entries)
        assert world.hub._lock.acquire(timeout=3), "the hub's lock is held while the forget waits for a render"
        world.hub._lock.release()
        assert forgetting.is_alive()        # the forget itself still waits: the page is told `gone` after the write
    finally:
        release.set()
        renderer.join(5)
        forgetting.join(5)
    assert not forgetting.is_alive()


def test_a_text_stored_while_the_registry_lets_the_root_go_is_not_taken_by_the_late_forget(world, put, monkeypatch):
    """Ticket 182, follow-up of #611: a store that takes no lock of the forget's (a landing's) writes, just after the registry
    let the root go, the text the forgotten document wrote. The document's forget must leave it: that write may be
    the folder's that takes the name, so the watch is open before the name is let go."""
    put("a.md")
    e = world.hub.entry("work/a.md")
    text = e.live._text
    forget = roots_mod.forget

    def letting_go(*args, **kwargs):
        root = forget(*args, **kwargs)
        world.hub.versions.put("work/a.md", text)
        return root
    monkeypatch.setattr(roots_mod, "forget", letting_go)
    assert world.hub.forget_root("work").name == "work"
    assert world.hub.versions.get("work/a.md", md_hash(text)) == text


def test_a_forget_whose_registry_write_fails_leaves_the_roots_documents_as_they_were(world, put, monkeypatch):
    """Ticket 182, follow-up of #611 (the other half of the test above): the watches open before the registry lets go; when it cannot (its file is not written), the root stays, and so do
    its documents: their watch ends and their texts reach the store again."""
    put("a.md")
    e = world.hub.entry("work/a.md")

    def failing(*args, **kwargs):
        raise OSError("no space left on device")
    monkeypatch.setattr(roots_mod, "forget", failing)
    with pytest.raises(OSError):
        world.hub.forget_root("work")
    assert world.hub.entries.get("work/a.md") is e and not state.Versions._claims
    text = "# Written after the failed forget\n"
    e.live._remember(text)
    assert world.hub.versions.get("work/a.md", md_hash(text)) == text


def test_a_forget_that_fails_after_the_registry_let_go_goes_on_with_its_documents_detached(world, put, monkeypatch):
    """Ticket 182, follow-up of #611: the registry let the name go and an entry store then failed. Another folder may take the
    name now, so the documents are not reattached: the forget goes on, and the failure is a row in the diagnostics log."""
    put("a.md")
    e = world.hub.entry("work/a.md")

    def failing(reg, *args, **kwargs):
        reg.forget("work")
        raise OSError("no space left on device")
    monkeypatch.setattr(roots_mod, "forget", failing)
    assert world.hub.forget_root("work").name == "work"
    assert world.hub.roots.get("work") is None and "work/a.md" not in world.hub.entries
    assert e.live._stored() is None and not state.Versions._claims
    assert any(r.get("kind") == "forget-failed" for r in diagnostics.read())


def test_one_documents_forget_that_raises_does_not_keep_the_others_of_the_root_from_theirs(world, put, monkeypatch):
    """Ticket 182, follow-up of #611: one entry's forget raises. The others of the root are forgotten all the same (their
    watch ends, their pages are told `gone`), and the failure is a row in the diagnostics log."""
    put("a.md")
    put("b.md")
    a, b = world.hub.entry("work/a.md"), world.hub.entry("work/b.md")
    told = []
    b.bus.publish = lambda name, data: told.append(name)
    monkeypatch.setattr(a.live, "forget", lambda: 1 / 0)
    assert list(world.hub.entries).index("work/a.md") < list(world.hub.entries).index("work/b.md")    # a's forget first
    world.hub.forget_root("work")
    assert "gone" in told
    assert world.hub.versions._folder("work/b.md") not in state.Versions._claims
    assert any(r.get("kind") == "forget-failed" for r in diagnostics.read())


def test_a_late_forget_leaves_the_versions_of_the_folder_that_took_the_name(world, put, tmp_path):
    put("a.md")
    e = world.hub.entry("work/a.md")
    renderer, release = _holding(e.live)
    forgetting = _forgetting(world.hub, "work")
    try:
        assert _until(lambda: "work/a.md" not in world.hub.entries)
        other = tmp_path / "y" / "work"
        other.mkdir(parents=True)
        text = "# The other folder's document\n"
        (other / "a.md").write_text(text)
        world.hub.roots.for_document(other / "a.md")
        world.hub.entry("work/a.md")
        assert world.hub.versions.get("work/a.md", md_hash(text)) == text
    finally:
        release.set()
        renderer.join(5)
        forgetting.join(5)
    assert not forgetting.is_alive()
    assert world.hub.versions.get("work/a.md", md_hash(text)) == text
