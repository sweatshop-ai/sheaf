"""The index data: every document of every root with its dot, read state and tabs, in
`/_/index.json` (SPEC 8.5, 8.6, 8.7). The page made from it is in test_hub_index_page.py."""
import os
import subprocess
import threading

import pytest

import sheafmd.comments as rdc
from helpers import NOW, PLAN, hub_rows, make_repo, thread, with_threads
from sheafmd.agents.base import State
from sheafmd.hub import client as hubclient
from sheafmd.hub import core
from sheafmd.hub import index as index_mod


def data(browser, **kw):
    r = browser.get("/_/index.json", **kw)
    assert r.status == 200, r.text
    return r.json()


def data_of(browser, query):
    r = browser.get("/_/index.json" + query)
    assert r.status == 200, r.text
    return r.json()


def row(browser, address):
    for root in data(browser)["roots"]:
        for d in root["docs"]:
            if d["doc"] == address:
                return d
    raise AssertionError(f"{address} is not in the index")


def listed(browser) -> list:
    """The addresses on the index, root by root."""
    return [d["doc"] for root in data(browser)["roots"] for d in root["docs"]]


# ── the shape ────────────────────────────────────────────────────────────────

def test_the_index_lists_every_root_and_every_document(world, work, put, tmp_path):
    put("sub/deep.md")
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.md").write_text("# X\n")
    world.hub.roots.for_document(other / "x.md")
    got = data(world)
    assert got["ok"] is True and got["more"] == {}
    by_name = {r["name"]: r for r in got["roots"]}
    assert set(by_name) == {"work", "other"}
    assert by_name["work"]["path"] == str(work.resolve()) and by_name["work"]["missing"] is False
    assert sorted(d["doc"] for d in by_name["work"]["docs"]) == ["work/start.md", "work/sub/deep.md"]
    assert [d["doc"] for d in by_name["other"]["docs"]] == ["other/x.md"]


def test_a_document_row_has_the_fields_of_the_spec(world):
    d = row(world, "work/start.md")
    assert set(d) == {"doc", "url", "dot", "open", "unread", "mtime", "tabs", "opened", "rendered"}
    assert d["url"] == f"http://127.0.0.1:{world.hub.port}/work/start.md"
    assert d["dot"] == "green" and d["open"] == 0 and d["unread"] == 0
    assert d["mtime"] == pytest.approx(NOW, abs=5)
    assert (d["tabs"], d["opened"], d["rendered"]) == (0, False, False)


def test_the_url_of_a_row_is_percent_encoded(world, put):
    put("a b/ünï #1.md")
    assert row(world, "work/a b/ünï #1.md")["url"].endswith("/work/a%20b/%C3%BCn%C3%AF%20%231.md")


def test_the_index_needs_the_cookie_or_the_key(world):
    assert world.get("/_/index.json", cookie=False).status == 401
    assert world.get("/_/index.json", cookie=False, key=True).status == 200
    assert world.get("/_/index.json", cookie=True).status == 200


def test_the_index_is_not_cached_and_has_no_key_in_it(world):
    r = world.get("/_/index.json")
    assert r.headers["Cache-Control"] == "no-store"
    assert world.hub.auth.key not in r.text


# ── the dot (8.6) ────────────────────────────────────────────────────────────

def test_a_document_with_no_comments_is_green(world):
    assert row(world, "work/start.md")["dot"] == "green"


def test_open_comments_are_blue_with_their_count(world, put):
    put("a.md", with_threads(thread("c1", "Ada"), thread("c2", "Ada")))
    d = row(world, "work/a.md")
    assert (d["dot"], d["open"], d["unread"]) == ("blue", 2, 0)


def test_resolved_comments_do_not_count(world, put):
    put("a.md", with_threads(thread("c1", "Ada", status="resolved")))
    d = row(world, "work/a.md")
    assert (d["dot"], d["open"]) == ("green", 0)


def test_malformed_and_foreign_comments_never_count(world, put):
    put("a.md", PLAN.replace("First paragraph", 'First paragraph<!-- a note for later -->')
        + '\nBroken<!-- sheaf-comment id=c9 by="Ada" never closed\n'
        + "\ntail of a deleted line\n-->\n")
    d = row(world, "work/a.md")
    assert (d["dot"], d["open"], d["unread"]) == ("green", 0, 0)


def test_a_comment_in_a_code_example_is_not_a_comment(world, put):
    put("a.md", PLAN + "\nWrite `<!-- sheaf-comment id=c1 by=\"Bob\" at=2026-10-13T10:00 "
        "status=open quote=\"x\" body -->` like this.\n")
    assert row(world, "work/a.md")["open"] == 0


def test_a_thread_by_someone_else_that_was_never_opened_is_red(world, put):
    put("a.md", with_threads(thread("c1", "Bob")))
    d = row(world, "work/a.md")
    assert (d["dot"], d["open"], d["unread"]) == ("red", 1, 1)


def test_a_reply_by_someone_else_makes_my_own_thread_unread(world, put):
    put("a.md", with_threads(thread("c1", "Ada", "Bob")))
    assert row(world, "work/a.md")["dot"] == "red"


def test_a_thread_whose_last_message_is_mine_is_read(world, put):
    put("a.md", with_threads(thread("c1", "Bob", "Ada")))
    d = row(world, "work/a.md")
    assert (d["dot"], d["unread"]) == ("blue", 0)


def test_a_resolved_thread_is_never_unread(world, put):
    put("a.md", with_threads(thread("c1", "Bob", status="resolved")))
    assert row(world, "work/a.md")["dot"] == "green"


def test_opening_a_thread_on_the_page_turns_red_into_blue(world, put):
    put("a.md", with_threads(thread("c1", "Bob", "Cy")))              # two messages
    assert row(world, "work/a.md")["dot"] == "red"
    assert world.post("/_/seen", {"doc": "work/a.md", "id": "c1", "count": 1}).status == 200
    assert row(world, "work/a.md")["dot"] == "red"                    # one of two seen
    assert world.post("/_/seen", {"doc": "work/a.md", "id": "c1", "count": 2}).status == 200
    d = row(world, "work/a.md")
    assert (d["dot"], d["unread"], d["open"]) == ("blue", 0, 1)


def test_a_new_message_after_the_thread_was_seen_is_unread_again(world, put):
    f = put("a.md", with_threads(thread("c1", "Bob")))
    world.post("/_/seen", {"doc": "work/a.md", "id": "c1", "count": 1})
    assert row(world, "work/a.md")["dot"] == "blue"
    f.write_text(with_threads(thread("c1", "Bob", "Bob")), encoding="utf-8")
    assert row(world, "work/a.md")["dot"] == "red"


def test_a_tell_running_on_the_document_is_orange(world, put):
    put("a.md", with_threads(thread("c1", "Ada")))
    e = world.hub.entry("work/a.md")
    assert row(world, "work/a.md")["dot"] == "blue"
    assert e.live.await_reply("c1")
    assert row(world, "work/a.md")["dot"] == "orange"
    e.live.stop_waiting("c1")
    assert row(world, "work/a.md")["dot"] == "blue"


def test_a_session_waiting_on_you_is_red_even_while_a_tell_runs(world, put):
    put("a.md", with_threads(thread("c1", "Ada")))
    e = world.hub.entry("work/a.md")
    e.live.await_reply("c1")
    e.live.observe(State("waiting", "Which one?"))
    assert row(world, "work/a.md")["dot"] == "red"
    e.live.observe(State("working"))
    assert row(world, "work/a.md")["dot"] == "orange"


def test_unread_beats_running_beats_open_beats_none(world, put):
    put("unread.md", with_threads(thread("c1", "Bob")))
    put("open.md", with_threads(thread("c1", "Ada")))
    put("none.md")
    put("running.md", with_threads(thread("c1", "Ada")))
    world.hub.entry("work/running.md").live.await_reply("c1")
    got = {d["doc"]: d["dot"] for d in data(world)["roots"][0]["docs"]}
    assert got == {"work/unread.md": "red", "work/running.md": "orange", "work/open.md": "blue",
                   "work/none.md": "green", "work/start.md": "green"}


# ── the order (8.6) ──────────────────────────────────────────────────────────

def test_rows_sort_by_dot_then_by_last_change(world, put):
    put("g-new.md", age=10)
    put("g-old.md", age=900)
    put("b-new.md", with_threads(thread("c1", "Ada")), age=20)
    put("b-old.md", with_threads(thread("c1", "Ada")), age=800)
    put("r-old.md", with_threads(thread("c1", "Bob")), age=5000)
    put("start.md", age=3000)
    docs = [d["doc"] for d in data(world)["roots"][0]["docs"]]
    assert docs == ["work/r-old.md", "work/b-new.md", "work/b-old.md", "work/g-new.md",
                    "work/g-old.md", "work/start.md"]


def test_roots_sort_by_their_most_recently_changed_document(world, put, tmp_path):
    put("start.md", age=500)
    older, newer = tmp_path / "older", tmp_path / "newer"
    for folder, age in ((older, 5000), (newer, 5)):
        folder.mkdir()
        f = folder / "a.md"
        f.write_text("# A\n")
        os.utime(f, (NOW - age, NOW - age))
        world.hub.roots.for_document(f)
    assert [r["name"] for r in data(world)["roots"]] == ["newer", "work", "older"]


def test_a_root_shows_its_worst_dot(world, put):
    put("a.md", with_threads(thread("c1", "Ada")))
    assert data(world)["roots"][0]["dot"] == "blue"
    put("b.md", with_threads(thread("c1", "Bob")))
    assert data(world)["roots"][0]["dot"] == "red"


# ── roots with nothing to list ───────────────────────────────────────────────

def test_a_root_whose_folder_is_gone_is_missing_and_has_no_dot(world, work):
    for f in work.iterdir():
        f.unlink()
    work.rmdir()
    got = data(world)["roots"][0]
    assert got["name"] == "work" and got["missing"] is True and got["docs"] == []
    assert got["dot"] is None


def test_a_root_behind_a_folder_the_hub_may_not_enter_is_not_missing(world, tmp_path, closed):
    """Python 3.14's `is_dir` says False there, 3.13's raises (a 500); the folder is not gone, and
    the hint of a missing one, `sheaf roots forget`, would drop its versions and read state."""
    notes = tmp_path / "srv" / "notes"
    notes.mkdir(parents=True)
    (notes / "a.md").write_text(PLAN, encoding="utf-8")
    world.hub.roots.for_document(notes / "a.md")
    closed(tmp_path / "srv")
    by_name = {r["name"]: r for r in data(world)["roots"]}
    got = by_name["notes"]
    assert got["missing"] is False and got["closed"] == "Permission denied"
    assert got["docs"] == [] and got["dot"] is None
    assert by_name["work"]["missing"] is False and by_name["work"]["closed"] is None


def test_a_root_with_no_markdown_has_no_dot(world, work):
    (work / "start.md").unlink()
    got = data(world)["roots"][0]
    assert got["missing"] is False and got["docs"] == [] and got["dot"] is None


def test_a_root_over_the_cap_says_how_many_more(world, put, monkeypatch):
    from sheafmd.hub import roots
    monkeypatch.setattr(roots, "LIST_CAP", 2)
    for i in range(5):
        put(f"d{i}.md")
    got = data(world)
    assert len(got["roots"][0]["docs"]) == 2 and got["more"] == {"work": 4}


def test_a_git_root_is_listed_by_git(world, tmp_path):
    repo = make_repo(tmp_path / "proj")
    (repo / ".gitignore").write_text("drafts/\n")
    for p in ("a.md", "drafts/x.md", "node_modules/y.md", "docs/z.md"):
        (repo / p).parent.mkdir(parents=True, exist_ok=True)
        (repo / p).write_text("# T\n")
    world.hub.roots.for_document(repo / "a.md")
    got = next(r for r in data(world)["roots"] if r["name"] == "proj")
    assert sorted(d["doc"] for d in got["docs"]) == ["proj/a.md", "proj/docs/z.md"]


# ── tabs, opened, rendered (8.5) ─────────────────────────────────────────────

def test_a_document_that_was_rendered_says_so_and_was_not_opened(world, work):
    world.hub.render(work / "start.md", {}, None)
    d = row(world, "work/start.md")
    assert (d["rendered"], d["opened"], d["tabs"]) == (True, False, 0)


def test_a_tab_makes_the_document_opened_and_counts_in_tabs(world, work):
    world.hub.render(work / "start.md", {}, None)
    first = world.get("/_/live?doc=work/start.md")
    second = world.get("/_/live?doc=work/start.md")
    d = row(world, "work/start.md")
    assert (d["tabs"], d["opened"], d["rendered"]) == (2, True, True)
    first.stream.close()
    second.stream.close()
    d = row(world, "work/start.md")
    assert (d["tabs"], d["opened"]) == (0, True)


def test_a_new_render_clears_opened(world, work):
    world.hub.render(work / "start.md", {}, None)
    world.get("/_/live?doc=work/start.md").stream.close()
    assert row(world, "work/start.md")["opened"] is True
    world.hub.render(work / "start.md", {}, None)
    assert row(world, "work/start.md")["opened"] is False


def _join_renders():
    """Wait for the threads the hub renders a page on (199): `Hub.render` names them `render <address>`."""
    for t in [t for t in threading.enumerate() if t.name.startswith("render ")]:
        t.join(10)


def test_a_render_behind_a_lock_held_past_120_s_renders_the_page_whose_own_pandoc_runs_are_fast(world, work, monkeypatch):
    """199 G (198 G, round 2 of #669): the time a render waits for the document's lock (behind a save, a refresh or another
    render) is never counted against pandoc's 120 s; only pandoc's own running time is. The lock is held while the render
    waits for it, and every pandoc run of the render is then given its whole 120 s: the page is rendered, no run is cut."""
    from sheafmd import _pandoc
    world.hub.render(work / "start.md", {}, None)
    limits, real = [], subprocess.run

    def timed(cmd, timeout=None, **kw):
        if cmd[0] == _pandoc.pypandoc.get_pandoc_path():
            limits.append(timeout)
        return real(cmd, timeout=timeout, **kw)
    monkeypatch.setattr(_pandoc.subprocess, "run", timed)
    started, taken, failed = threading.Event(), threading.Event(), []
    entered = world.hub._render_entry

    def entry_then_tell(*a, **kw):             # the render has begun and goes on to the document's lock
        got = entered(*a, **kw)
        started.set()
        return got
    monkeypatch.setattr(world.hub, "_render_entry", entry_then_tell)

    def hold():                                # a save that holds the document's lock while the render waits for it
        with world.hub.page_lock("work/start.md"):
            taken.set()
            if not started.wait(10):
                failed.append("the render never began")
    holder = threading.Thread(target=hold)
    holder.start()
    assert taken.wait(10)
    got = world.hub.render(work / "start.md", {"title": "Held"}, None)      # other settings: the page is rendered again
    holder.join(10)
    assert not failed, failed
    assert not got.get("pending"), got
    assert limits and all(t == _pandoc.TIMEOUT for t in limits), limits
    page = world.get("/work/start.md").body.decode()
    assert "apples" in page and "did not finish" not in page, page[-2000:]


def test_a_render_longer_than_sheaf_open_waits_answers_pending_and_publishes_the_finished_page(world, work, monkeypatch):
    """199 H (198 H, round 2 of #669): a render whose pandoc runs together take longer than `sheaf open` waits, each under
    its own 120 s, is no failure. The hub answers `pending` before the client's wait runs out, the
    render goes on and publishes the finished page, never a failed one, and the next render with the same settings
    serves that page without running pandoc again. The runs are held until the hub has answered, and each is given its
    whole 120 s."""
    from sheafmd import _pandoc
    limits, real, go = [], subprocess.run, threading.Event()

    def slow(cmd, timeout=None, **kw):         # every pandoc run outlasts the hub's answer limit
        if cmd[0] != _pandoc.pypandoc.get_pandoc_path():
            return real(cmd, timeout=timeout, **kw)
        limits.append(timeout)
        go.wait(10)                            # held until the request has answered
        return real(cmd, timeout=timeout, **kw)
    monkeypatch.setattr(_pandoc.subprocess, "run", slow)
    monkeypatch.setattr(core, "RENDER_ANSWER_WITHIN", 0.5)   # the hub's answer limit, below the client's wait
    got = world.hub.render(work / "start.md", {}, None)
    assert core.RENDER_ANSWER_WITHIN < hubclient.RENDER_TIMEOUT
    assert got.get("pending") is True, got
    assert (got["doc"], got["url"]) == ("work/start.md", world.hub.url("work/start.md")), got
    go.set()
    _join_renders()
    assert len(limits) >= 2 and all(t == _pandoc.TIMEOUT for t in limits), limits
    runs = len(limits)
    again = world.hub.render(work / "start.md", {}, None)
    assert not again.get("pending") and len(limits) == runs, (again, limits)
    page = world.get("/work/start.md").body.decode()
    assert "apples" in page and "did not finish" not in page, page[-2000:]


def test_a_render_the_hub_answers_in_time_raises_its_error_in_the_request(world, work, monkeypatch):
    """199: the render runs on a thread of its own, and a failure it meets within the answer limit is the request's, as
    before (`/_/render` answers 422 with its words)."""
    from sheafmd.render import RenderError
    def broken(*a, **kw):
        raise RenderError("no page for you")
    monkeypatch.setattr(world.hub, "_render_entry", broken)
    with pytest.raises(RenderError, match="no page for you"):
        world.hub.render(work / "start.md", {}, None)


def _late_warnings(world, monkeypatch, go):
    """The render's entry is found, given a link-rule warning, and held until `go`: past the hub's answer limit."""
    entered = world.hub._render_entry

    def warned(*a, **kw):
        got = entered(*a, **kw)
        got[0].warnings = ["a link that no longer leads anywhere"]
        go.wait(10)
        return got
    monkeypatch.setattr(world.hub, "_render_entry", warned)
    monkeypatch.setattr(core, "RENDER_ANSWER_WITHIN", 0.2)
    return entered


def test_the_warnings_of_a_render_that_answered_pending_go_to_the_next_open(world, work, monkeypatch):
    """199 (review round 1): a render answered `pending` hands its link-rule warnings to nobody; they stay with the
    document, and the next `sheaf open` gets them."""
    go, within = threading.Event(), core.RENDER_ANSWER_WITHIN
    entered = _late_warnings(world, monkeypatch, go)
    assert world.hub.render(work / "start.md", {}, None).get("pending") is True
    go.set()
    _join_renders()
    monkeypatch.setattr(world.hub, "_render_entry", entered)
    monkeypatch.setattr(core, "RENDER_ANSWER_WITHIN", within)      # the next open waits its answer out, on a slow runner too
    assert world.hub.render(work / "start.md", {}, None)["warnings"] == ["a link that no longer leads anywhere"]


def test_the_warnings_of_a_late_render_are_with_the_document_before_its_locks_are_let_go(world, work, monkeypatch):
    """200 (Codex, round 3 of #673): the warnings of a render answered `pending` are back on the entry before the render
    lets go of the name's lock and the hub's, so an open that comes in right then is handed them, never an empty list."""
    go, seen = threading.Event(), []
    entered = _late_warnings(world, monkeypatch, go)
    held = world.hub._render_held

    def then_the_next_open(*a, **kw):          # the next open, at once after the late render let go of its locks
        got = held(*a, **kw)
        monkeypatch.setattr(world.hub, "_render_entry", entered)
        seen.append(held(a[0], a[1], {}, None)["warnings"])
        return got
    monkeypatch.setattr(world.hub, "_render_held", then_the_next_open)
    assert world.hub.render(work / "start.md", {}, None).get("pending") is True
    go.set()
    _join_renders()
    assert seen == [["a link that no longer leads anywhere"]], seen


def test_a_render_whose_rebuild_for_new_settings_failed_is_rebuilt_by_the_next_render_with_the_same_settings(world, work,
                                                                                                         monkeypatch):
    """199 (spec review): the settings of a render are recorded before its rebuild runs, so a rebuild that failed (after
    the hub answered `pending`, nobody heard of it) left the next `sheaf open` with the same settings serving the page of
    the old ones. The next render rebuilds instead, until one rebuild goes through."""
    from sheafmd.render import RenderError
    world.hub.render(work / "start.md", {}, None)
    live = world.hub.entries["work/start.md"].live
    real, calls = live.rebuild, []

    def once_broken():
        calls.append(1)
        if len(calls) == 1:
            raise RenderError("pandoc could not read this document")
        return real()
    monkeypatch.setattr(live, "rebuild", once_broken)
    with pytest.raises(RenderError):
        world.hub.render(work / "start.md", {"title": "New"}, None)
    world.hub.render(work / "start.md", {"title": "New"}, None)
    world.hub.render(work / "start.md", {"title": "New"}, None)
    assert len(calls) == 2, calls
    assert "New" in world.get("/work/start.md").body.decode()


def test_a_render_that_fails_after_the_hub_answered_pending_is_written_down(world, work, monkeypatch):
    """199: a render that fails after the request was answered `pending` has nobody to tell; its failure is a
    `render-failed` row, and the next open meets it in its own render."""
    from sheafmd.render import RenderError
    go = threading.Event()

    def broken(*a, **kw):
        go.wait(10)
        raise RenderError("pandoc could not read this document")
    monkeypatch.setattr(world.hub, "_render_entry", broken)
    monkeypatch.setattr(core, "RENDER_ANSWER_WITHIN", 0.2)
    assert world.hub.render(work / "start.md", {}, None).get("pending") is True
    go.set()
    _join_renders()
    assert [r["error"] for r in hub_rows("render-failed")] == ["RenderError: pandoc could not read this document"]


def test_a_document_opened_from_the_index_is_opened_but_not_rendered(world):
    world.get("/work/start.md")
    world.get("/_/live?doc=work/start.md").stream.close()
    d = row(world, "work/start.md")
    assert (d["opened"], d["rendered"]) == (True, False)


def test_rendered_means_since_this_hub_started(world, work):
    world.hub.render(work / "start.md", {}, None)
    assert "rendered" in world.hub.docs.get("work/start.md")
    from sheafmd import paths
    from sheafmd.hub.core import Hub
    from sheafmd.hub.handler import Handler
    from helpers import Browser
    again = Browser(h := Hub(port=world.hub.port, key=paths.ensure_key(), started_by="test"),
                    Handler(h))
    assert row(again, "work/start.md")["rendered"] is False


def test_a_rendered_document_that_the_listing_leaves_out_is_still_in_the_index(world, tmp_path):
    repo = make_repo(tmp_path / "proj")
    (repo / ".gitignore").write_text("drafts/\n")
    (repo / "a.md").write_text("# A\n")
    (repo / "drafts").mkdir()
    (repo / "drafts" / "x.md").write_text("# X\n")
    world.hub.render(repo / "a.md", {}, None)
    assert "proj/drafts/x.md" not in listed(world)
    world.hub.render(repo / "drafts" / "x.md", {}, None)
    d = row(world, "proj/drafts/x.md")
    assert d["rendered"] is True


def test_a_rendered_document_under_node_modules_is_in_the_index_and_none_is_under_git(world, tmp_path):
    """The listing leaves `node_modules` and `.git` out (8.6). A document under `node_modules` that the
    person rendered is on the index, as a gitignored one is and as `sheaf list` shows it. One under a
    `.git` folder is never its repository's (8.2): it has a root of its own, and no address on the
    index holds `.git`."""
    repo = make_repo(tmp_path / "proj")
    (repo / "a.md").write_text("# A\n")
    readme = repo / "node_modules" / "pkg" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("# Pkg\n")
    world.hub.render(repo / "a.md", {}, None)
    assert "proj/a.md" in listed(world) and "proj/node_modules/pkg/README.md" not in listed(world)
    assert world.hub.render(readme, {}, None)["doc"] == "proj/node_modules/pkg/README.md"
    assert row(world, "proj/node_modules/pkg/README.md")["rendered"] is True
    inner = repo / ".git" / "notes.md"
    inner.write_text("# Notes\n")
    assert world.hub.render(inner, {}, None)["doc"] == "git/notes.md"
    assert row(world, "git/notes.md")["rendered"] is True
    assert not [a for a in listed(world) if ".git" in a.split("/")]


# ── the status cache (8.6) ───────────────────────────────────────────────────

@pytest.fixture
def parses(monkeypatch):
    seen = []
    real = rdc.parse

    def counting(text):
        seen.append(len(text))
        return real(text)
    monkeypatch.setattr(index_mod.rdc, "parse", counting)
    return seen


def test_a_file_is_parsed_again_only_when_its_mtime_or_size_changes(world, put, parses):
    f = put("a.md", with_threads(thread("c1", "Ada")), age=100)
    for _ in range(3):
        assert row(world, "work/a.md")["open"] == 1
    assert len(parses) == 1
    f.write_text(with_threads(thread("c1", "Ada"), thread("c2", "Ada")), encoding="utf-8")
    assert row(world, "work/a.md")["open"] == 2
    assert len(parses) == 2


def test_a_change_of_mtime_alone_parses_again(world, put, parses):
    f = put("a.md", with_threads(thread("c1", "Ada")), age=100)
    row(world, "work/a.md")
    os.utime(f, (NOW - 50, NOW - 50))
    row(world, "work/a.md")
    assert len(parses) == 2


def test_asking_for_the_rendered_documents_alone_keeps_the_others_in_the_parse_cache(world, put, parses):
    """`sheaf list` asks for the rendered documents with no listing of any folder: the documents it
    does not look at are still there, and parsing them again on the next look would be for nothing."""
    put("a.md", with_threads(thread("c1", "Ada")), age=100)
    put("b.md", with_threads(thread("c1", "Ada")), age=100)
    world.hub.render(world.hub.roots.resolve("work/a.md"), {}, None)
    parses.clear()                                  # the page's own
    data(world)
    assert len(parses) == 2
    data_of(world, "?rendered=1")
    data(world)
    assert len(parses) == 2


def test_a_look_at_every_folder_still_drops_what_a_gone_file_parsed_to(world, put, parses):
    """The control of the one above: the file comes back with the same (mtime, size), so only a
    summary that was dropped makes it parsed again."""
    text = with_threads(thread("c1", "Ada"))
    put("a.md", text, age=100)
    b = put("b.md", text, age=100)
    data(world)
    assert len(parses) == 2
    b.unlink()
    data(world)
    put("b.md", text, age=100)
    data(world)
    assert len(parses) == 3


def test_a_file_with_no_comment_marker_is_not_parsed_at_all(world, parses):
    assert row(world, "work/start.md")["open"] == 0
    assert parses == []


def test_a_file_that_cannot_be_read_is_listed_with_no_comments(world, put):
    f = put("a.md", with_threads(thread("c1", "Ada")))
    f.chmod(0)
    try:
        if os.access(f, os.R_OK):
            pytest.skip("this user reads files whatever their mode")
        d = row(world, "work/a.md")
    finally:
        f.chmod(0o644)
    assert (d["dot"], d["open"]) == ("green", 0)


def test_the_index_never_renders_a_document_nobody_asked_for(world, put):
    for i in range(3):
        put(f"d{i}.md")
    data(world)
    assert world.hub.entries == {}


# ── only what was rendered (what `sheaf list` asks) ──────────────────────────

def test_index_json_can_ask_for_only_the_documents_rendered_since_the_start(world, work, put, tmp_path):
    put("other.md")
    world.hub.render(work / "start.md", {}, None)
    loose = tmp_path / "scratch" / "z.md"
    loose.parent.mkdir()
    loose.write_text("# Z\n")
    world.hub.roots.for_document(loose)                           # a root, nothing rendered in it
    got = data_of(world, "?rendered=1")
    assert [(r["name"], [d["doc"] for d in r["docs"]]) for r in got["roots"]] == [
        ("work", ["work/start.md"])]
    assert got["more"] == {} and got["roots"][0]["docs"][0]["rendered"] is True


def test_index_json_asked_for_rendered_lists_a_gitignored_document_that_was_named(world, tmp_path):
    repo = make_repo(tmp_path / "proj")
    (repo / ".gitignore").write_text("drafts/\n")
    (repo / "drafts").mkdir()
    (repo / "drafts" / "x.md").write_text("# X\n")
    world.hub.render(repo / "drafts" / "x.md", {}, None)
    got = data_of(world, "?rendered=1")
    assert [d["doc"] for r in got["roots"] for d in r["docs"]] == ["proj/drafts/x.md"]


def test_index_json_with_nothing_rendered_has_no_roots(world):
    assert data_of(world, "?rendered=1")["roots"] == []


@pytest.mark.parametrize("q", ["?rendered=yes", "?rendered=2", "?rendered="])
def test_index_json_refuses_a_rendered_that_is_not_0_or_1(world, q):
    assert world.get("/_/index.json" + q).status == 400


def test_a_legacy_action_reply_counts_as_claudes_as_the_door_counts_it():
    """The index and the door's `documents` feed one unread rule (8.7) the same last author: a legacy
    `"Claude (action)"` reply is Claude's (5.3), so for a person named Claude it is their own on both."""
    text = with_threads(thread("c1", "Bob", "Claude (action)"))
    assert index_mod.summarize(text).threads == (("c1", 2, "Claude"),)
    assert [c.last_by for c in rdc.parse(text).comments] == ["Claude"]


# ── 200: a first render runs outside the hub's lock ──────────────────────────
HELD_MARK = "quinces held by the test"


@pytest.fixture
def held_pandoc(monkeypatch):
    """Pandoc held for every document whose text carries HELD_MARK, until `go` is set; every run is counted in `runs`
    (held or not), and `begun` is set when a held run starts."""
    from sheafmd import _pandoc
    real, go, begun, runs = subprocess.run, threading.Event(), threading.Event(), []

    def run(cmd, timeout=None, input=None, **kw):
        if cmd[0] == _pandoc.pypandoc.get_pandoc_path():
            runs.append(HELD_MARK in (input or ""))
            if HELD_MARK in (input or ""):
                begun.set()
                go.wait(20)
        return real(cmd, timeout=timeout, input=input, **kw)
    monkeypatch.setattr(_pandoc.subprocess, "run", run)
    yield go, begun, runs
    go.set()
    _join_renders()


def _in_thread(fn, *a):
    """Run `fn(*a)` on a thread; gives (the thread, the list its result or exception lands in)."""
    out = []

    def work():
        try:
            out.append(fn(*a))
        except BaseException as ex:
            out.append(ex)
    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t, out


def _timed(fn, *a, within=1.0):
    """`fn(*a)` on a thread, joined for `within` seconds: gives its result, or fails when it is still waiting."""
    t, out = _in_thread(fn, *a)
    t.join(within)
    assert not t.is_alive(), f"{fn} still waits after {within} s"
    if isinstance(out[0], BaseException):
        raise out[0]
    return out[0]


def test_a_first_render_held_in_pandoc_never_delays_a_document_already_opened(world, work, put, held_pandoc):
    """200 A: while the first render of document A waits in pandoc, the entry of an opened document B and a render of B with
    the same settings answer at once: the hub's lock is not held by A's render."""
    go, begun, _ = held_pandoc
    world.hub.render(work / "start.md", {}, None)
    put("held.md", PLAN + f"\n{HELD_MARK}\n")
    world.hub.roots.for_document(work / "held.md")
    a, out = _in_thread(world.hub.entry, "work/held.md")
    assert begun.wait(10)
    assert _timed(world.hub.entry, "work/start.md").address == "work/start.md"
    assert not _timed(world.hub.render, work / "start.md", {}, None).get("pending")
    assert a.is_alive() and not out, "A's render ended before its pandoc was let go"
    go.set()
    a.join(10)
    assert out and out[0].address == "work/held.md", out


def test_a_first_render_held_in_pandoc_never_delays_the_first_render_of_another_document(world, work, put, held_pandoc):
    """200 B: two first renders run side by side; B's is made and rendered while A's pandoc is held."""
    go, begun, _ = held_pandoc
    put("held.md", PLAN + f"\n{HELD_MARK}\n")
    world.hub.roots.for_document(work / "held.md")
    a, out = _in_thread(world.hub.entry, "work/held.md")
    assert begun.wait(10)
    e = _timed(world.hub.entry, "work/start.md", within=10)
    assert e.address == "work/start.md" and "apples" in e.html
    assert a.is_alive() and not out
    go.set()
    a.join(10)
    assert out and out[0].address == "work/held.md", out


def test_a_root_forgotten_during_a_held_first_render_leaves_its_address_naming_nothing(world, work, put, held_pandoc):
    """200 C1: `forget_root` while A's first render is held in pandoc: A's open is NotFound, the hub keeps no entry, and
    the version its first render stored is taken out of the store, as a forgotten document's are."""
    from sheafmd.hub import roots as roots_mod
    go, begun, _ = held_pandoc
    put("held.md", PLAN + f"\n{HELD_MARK}\n")
    world.hub.roots.for_document(work / "held.md")
    store = world.hub._versions_of(world.hub.roots.get("work"))
    a, out = _in_thread(world.hub.entry, "work/held.md")
    assert begun.wait(10)
    _timed(world.hub.forget_root, "work", within=10)
    go.set()
    a.join(10)
    assert out and isinstance(out[0], roots_mod.NotFound), out
    assert "work/held.md" not in world.hub.entries
    assert store.texts("work/held.md") == []


def test_two_opens_of_one_new_document_make_one_entry_rendered_once(world, work, put, held_pandoc):
    """200 C2: two threads open the same new document while its pandoc is held: one entry, one render."""
    go, begun, runs = held_pandoc
    put("held.md", PLAN + f"\n{HELD_MARK}\n")
    world.hub.roots.for_document(work / "held.md")
    first, first_out = _in_thread(world.hub.entry, "work/held.md")
    assert begun.wait(10)
    second, second_out = _in_thread(world.hub.entry, "work/held.md")
    second.join(0.5)
    assert second.is_alive(), "the second open did not wait for the first one's render"
    go.set()
    first.join(10)
    second.join(10)
    assert first_out and second_out and first_out[0] is second_out[0] is world.hub.entries["work/held.md"]
    one_render = runs.count(True)
    assert one_render >= 1
    # the second open rendered nothing: a fresh first render of the same text runs pandoc as many times as both opens did
    world.hub.forget_document("work/held.md")
    world.hub.entry("work/held.md")
    assert runs.count(True) == 2 * one_render, runs


def test_a_document_deleted_during_its_held_first_render_keeps_no_entry(world, work, put, held_pandoc):
    """200 D: a delete (`forget_document`, its file gone) while the first render is held in pandoc: the maker keeps no entry
    for the file that went; it looks again and finds the address names nothing."""
    from sheafmd.hub import roots as roots_mod
    go, begun, _ = held_pandoc
    f = put("held.md", PLAN + f"\n{HELD_MARK}\n")
    world.hub.roots.for_document(work / "held.md")
    a, out = _in_thread(world.hub.entry, "work/held.md")
    assert begun.wait(10)
    f.unlink()
    _timed(world.hub.forget_document, "work/held.md")
    go.set()
    a.join(10)
    assert out and isinstance(out[0], roots_mod.NotFound), out
    assert "work/held.md" not in world.hub.entries


def test_a_new_entry_that_cannot_be_made_leaves_no_mark_for_the_next_open(world, work, monkeypatch):
    """200 D: an entry whose making raises before its render (a private root not seen) leaves no mark of a render under
    way: the next open of the address makes it, and does not wait for a render that never comes."""
    made = world.hub._new_entry

    def refused(*a, **kw):
        monkeypatch.setattr(world.hub, "_new_entry", made)
        raise RuntimeError("not now")
    monkeypatch.setattr(world.hub, "_new_entry", refused)
    with pytest.raises(RuntimeError):
        world.hub.entry("work/start.md")
    assert _timed(world.hub.entry, "work/start.md", within=10).address == "work/start.md"


def test_a_page_moved_away_and_back_during_its_held_first_render_keeps_its_versions(world, work, put, held_pandoc):
    """200 (Codex, round 2 of #679): a move of the address while its first render is held drops that entry, and the entry
    given up takes out only what it stored itself: the versions the page brought back to the address stay."""
    go, begun, _ = held_pandoc
    put("held.md", PLAN + f"\n{HELD_MARK}\n")
    world.hub.roots.for_document(work / "held.md")
    store = world.hub._versions_of(world.hub.roots.get("work"))
    a, out = _in_thread(world.hub.entry, "work/held.md")
    assert begun.wait(10)
    world.hub.moved_page("work/held.md", "work/away.md", "test")
    store.put("work/held.md", "# Back\n\nThe page came back with this version.\n")    # as a move back carries it
    go.set()
    a.join(10)
    assert any("came back" in t for t in store.texts("work/held.md")), store.texts("work/held.md")


def _render_ends_in(monkeypatch, step, go, maker):
    """`step` of a move (a function of `core.loose_mod`, the last store a move carries) lets the held first render end,
    and waits for its maker: pandoc finishes after the versions were carried, before the move lets go of the entry."""
    was = getattr(core.loose_mod, step)

    def then_the_render_ends(*a, **kw):
        got = was(*a, **kw)
        go.set()
        maker.join(10)
        return got
    monkeypatch.setattr(core.loose_mod, step, then_the_render_ends)


def test_a_first_render_that_ends_while_its_page_moves_leaves_no_version_at_the_old_address(world, work, put, held_pandoc,
                                                                                            monkeypatch):
    """200 (Codex, round 7 of #679): the entry being made is let go of before the move carries the versions, so a first
    render that ends meanwhile stores nothing under the address the page left."""
    go, begun, _ = held_pandoc
    (work / ".sheaf.toml").write_text('versions = "root"\n', encoding="utf-8")     # kept in the root, never forgotten
    put("held.md", PLAN + f"\n{HELD_MARK}\n")
    world.hub.roots.for_document(work / "held.md")
    store = world.hub._versions_of(world.hub.roots.get("work"))
    a, _ = _in_thread(world.hub.entry, "work/held.md")
    assert begun.wait(10)
    _render_ends_in(monkeypatch, "marks_moved", go, a)
    os.replace(work / "held.md", work / "away.md")        # a move renames the file before the hub carries the rest
    world.hub.moved_page("work/held.md", "work/away.md", "test")
    assert not any(HELD_MARK in t for t in store.texts("work/held.md")), store.texts("work/held.md")


def test_a_first_render_that_ends_while_its_page_lands_elsewhere_leaves_no_version_at_the_old_address(world, work, put,
                                                                                                     held_pandoc, monkeypatch):
    """200 (Codex, round 7 of #679): as for a move in the hub, for a page that lands on another tiroir: the entry being
    made is let go of before its versions are forgotten."""
    go, begun, _ = held_pandoc
    (work / ".sheaf.toml").write_text('versions = "root"\n', encoding="utf-8")     # kept in the root, never forgotten
    put("held.md", PLAN + f"\n{HELD_MARK}\n")
    world.hub.roots.for_document(work / "held.md")
    store = world.hub._versions_of(world.hub.roots.get("work"))
    a, _ = _in_thread(world.hub.entry, "work/held.md")
    assert begun.wait(10)
    _render_ends_in(monkeypatch, "marks_gone", go, a)
    finish = world.hub.moved_remote("work/held.md", "https://other.example", "work/held.md", "test", "0" * 64)
    os.unlink(work / "held.md")                           # as the move does, before its `finish`
    finish()
    assert not any(HELD_MARK in t for t in store.texts("work/held.md")), store.texts("work/held.md")


# ── 213: a render never answers with a page of settings older than its own ───
def test_a_render_with_the_settings_another_render_just_set_waits_for_a_page_of_them(world, work, monkeypatch):
    """213 C (Codex round 9 of #679): renders with settings A, then B, then B again, at once. The third found its settings
    already recorded (old == new), skipped the rebuild and answered while the page was still the one of the settings before
    A: B's rebuild had not run yet. A render answers with a page built from its settings or newer ones."""
    world.hub.render(work / "start.md", {}, None)
    live = world.hub.entries["work/start.md"].live
    real, calls, a_built, a_go, b_go = live.rebuild, [], threading.Event(), threading.Event(), threading.Event()

    def held():
        calls.append(1)
        if len(calls) == 1:                     # A's rebuild: built with A, then held before it says it is done
            got = real()
            a_built.set()
            a_go.wait(20)
            return got
        if len(calls) == 2:                     # B's rebuild: held before it begins
            b_go.wait(20)
        return real()
    monkeypatch.setattr(live, "rebuild", held)
    first, _ = _in_thread(world.hub._render_held, "work/start.md", work / "start.md", {"title": "Apricot"}, None)
    second = None
    try:
        assert a_built.wait(10)
        second, _ = _in_thread(world.hub._render_held, "work/start.md", work / "start.md", {"title": "Bramble"}, None)
        for _ in range(200):
            if len(calls) == 2:
                break
            threading.Event().wait(0.05)
        assert len(calls) == 2, calls
        a_go.set()
        first.join(10)
        assert "Apricot" in world.hub.entries["work/start.md"].html
        _timed(world.hub._render_held, "work/start.md", work / "start.md", {"title": "Bramble"}, None, within=10)
        assert "Bramble" in world.hub.entries["work/start.md"].html
    finally:
        a_go.set()
        b_go.set()
        first.join(10)
        if second is not None:
            second.join(10)


def test_an_open_after_its_root_was_forgotten_and_its_name_taken_never_waits_for_the_old_roots_render(world, work, put,
                                                                                                    held_pandoc, tmp_path):
    """213 D (Codex round 9 of #679): the mark of an entry being made was the address alone. A root forgotten during a
    held first render, its name taken by another folder holding the same page: the open of that page waited for the
    forgotten root's render, up to pandoc's whole time."""
    go, begun, _ = held_pandoc
    put("held.md", PLAN + f"\n{HELD_MARK}\n")
    world.hub.roots.for_document(work / "held.md")
    a, out = _in_thread(world.hub.entry, "work/held.md")
    assert begun.wait(10)
    _timed(world.hub.forget_root, "work", within=10)
    other = tmp_path / "again" / "work" / "held.md"
    other.parent.mkdir(parents=True)
    other.write_text(PLAN, encoding="utf-8")
    assert world.hub.roots.for_document(other).name == "work"
    e = _timed(world.hub.entry, "work/held.md", within=10)
    assert e.file() == other and "apples" in e.html
    go.set()
    a.join(10)


def test_a_first_render_that_fails_after_its_page_landed_elsewhere_leaves_no_watch_behind(world, work, put, monkeypatch):
    """213 E (Codex round 9 of #679): a landing on another tiroir detached the entry being made without marking it so; a
    first render that then failed was given up without its forget, and the watch the detach opened in the versions store
    stayed for the life of the hub."""
    from sheafmd.hub import state
    from sheafmd.render import RenderError
    put("held.md", PLAN)
    world.hub.roots.for_document(work / "held.md")
    store = world.hub._versions_of(world.hub.roots.get("work")) or world.hub.versions
    made, begun, go = world.hub._new_entry, threading.Event(), threading.Event()

    def failing(*a, **kw):
        e = made(*a, **kw)

        def refresh(force=False):
            begun.set()
            go.wait(10)
            raise RenderError("pandoc could not read this document")
        e.live.refresh = refresh
        return e
    monkeypatch.setattr(world.hub, "_new_entry", failing)
    a, out = _in_thread(world.hub.entry, "work/held.md")
    assert begun.wait(10)
    finish = world.hub.moved_remote("work/held.md", "https://other.example", "work/held.md", "test", "0" * 64)
    go.set()
    a.join(10)
    assert out and isinstance(out[0], RenderError), out
    os.unlink(work / "held.md")
    finish()
    assert store._folder("work/held.md") not in state.Versions._claims
