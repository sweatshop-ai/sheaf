"""The index data: every document of every root with its dot, read state and tabs, in
`/_/index.json` (SPEC 8.5, 8.6, 8.7). The page made from it is in test_hub_index_page.py."""
import os

import pytest

import sheafmd.comments as rdc
from helpers import NOW, PLAN, hold_job, make_repo, thread, with_threads
from sheafmd.agents.base import State
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


def test_an_ask_running_on_the_document_is_orange_and_the_dot_goes_back_when_it_ends(world, put):
    put("a.md", with_threads(thread("c1", "Ada")))
    assert row(world, "work/a.md")["dot"] == "blue"
    job, release = hold_job(world.hub, "work/a.md")
    try:
        assert row(world, "work/a.md")["dot"] == "orange"
        assert world.hub.jobs_asking() == [["work/a.md", "c1"]]
    finally:
        release.set()
    world.hub.runner.join(5)
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
