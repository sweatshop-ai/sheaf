"""The door's `documents` tool, in memory (SPEC 12, 8.6, 8.7): which documents wait for an agent."""
import subprocess
from pathlib import Path

import pytest

import sheafmd.comments as rdc
from helpers import GIT_FAILS, PLAN, call, comment, git_fails, hold_job, ok, refused
from sheafmd.agents.base import State
from sheafmd.hub.state import Tokens
from sheafmd.source import update_file

ROW = ["doc", "dot", "open", "path", "unread", "url"]


def doc(root: Path, name: str, text: str = PLAN) -> Path:
    f = root / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    return f


def docs(browser, **args):
    return ok(browser, "documents", **args)


def names(rows):
    return sorted(r["doc"] for r in rows)


@pytest.fixture
def notes(browser, tmp_path):
    """A root `notes` (outside git) with a document that has two open comments, one whose only
    comment is resolved, and one with none."""
    root = tmp_path / "notes"
    busy, done, quiet = doc(root, "busy.md"), doc(root, "sub/done.md"), doc(root, "quiet.md")
    browser.hub.roots.for_document(busy)
    comment(busy)
    comment(busy, "First paragraph", "And apples?")
    comment(done)
    update_file(done, lambda t: rdc.set_status(t, "c1", "resolved"))
    return root


def test_documents_lists_those_with_open_comments_and_says_where_they_are(browser, notes):
    rows = docs(browser)
    assert names(rows) == ["notes/busy.md"]
    [r] = rows
    assert sorted(r) == ROW
    assert r["open"] == 2 and r["dot"] == "blue"
    assert r["url"] == f"http://127.0.0.1:{browser.hub.port}/notes/busy.md"
    assert r["path"] == str(notes.resolve() / "busy.md")


def test_every_document_with_open_only_false(browser, notes):
    rows = docs(browser, open_only=False)
    assert names(rows) == ["notes/busy.md", "notes/quiet.md", "notes/sub/done.md"]
    by = {r["doc"]: r for r in rows}
    assert (by["notes/quiet.md"]["open"], by["notes/quiet.md"]["dot"]) == (0, "green")
    assert (by["notes/sub/done.md"]["open"], by["notes/sub/done.md"]["dot"]) == (0, "green")


def test_the_most_urgent_come_first(browser, notes):
    rows = docs(browser, open_only=False)
    assert rows[0]["doc"] == "notes/busy.md" and rows[-1]["dot"] == "green"


def test_a_root_can_be_asked_for_by_name(browser, notes, tmp_path):
    other = doc(tmp_path / "other", "o.md")
    browser.hub.roots.for_document(other)
    comment(other)
    assert names(docs(browser)) == ["notes/busy.md", "other/o.md"]
    assert names(docs(browser, root="other")) == ["other/o.md"]
    assert "nowhere" in refused(browser, "documents", root="nowhere")


def test_a_comment_that_cannot_be_read_does_not_count(browser, notes):
    update_file(notes / "quiet.md", lambda t: t + "\n-->\n")
    assert dict((r["doc"], r["open"]) for r in docs(browser, open_only=False))["notes/quiet.md"] == 0


def test_a_change_to_a_file_is_seen_on_the_next_call(browser, notes):
    assert names(docs(browser)) == ["notes/busy.md"]
    comment(notes / "quiet.md")
    assert names(docs(browser)) == ["notes/busy.md", "notes/quiet.md"]
    update_file(notes / "busy.md", lambda t: rdc.set_status(rdc.set_status(t, "c1", "resolved"), "c2", "resolved"))
    assert names(docs(browser)) == ["notes/quiet.md"]


# ── unread, and the red and orange dots (8.6, 8.7) ───────────────────────────

def test_a_thread_whose_last_message_is_not_by_the_person_is_unread_until_it_is_seen(browser, notes):
    busy = notes / "busy.md"
    update_file(busy, lambda t: rdc.reply(t, "c1", "Because.", "Claude", "2026-10-14T11:00", role="answer"))
    [r] = docs(browser)
    assert r["unread"] == 1 and r["dot"] == "red"              # c1 answered by an agent; c2 is Ada's own
    browser.hub.seen.mark("notes/busy.md", "c1", 2)            # the comment and its reply
    [r] = docs(browser)
    assert r["unread"] == 0 and r["dot"] == "blue"


def test_the_persons_own_last_message_is_never_unread(browser, notes):
    update_file(notes / "busy.md", lambda t: rdc.reply(t, "c1", "Thanks.", "Ada", "2026-10-14T11:00"))
    [r] = docs(browser)
    assert r["unread"] == 0 and r["dot"] == "blue"


def test_a_thread_that_was_told_and_waits_makes_the_dot_orange(browser, notes):
    e = browser.hub.entry("notes/busy.md")
    e.live.await_reply("c1")
    [r] = docs(browser)
    assert r["dot"] == "orange"
    ok(browser, "reply", doc="notes/busy.md", id="c1", text="Done.", role="action")
    [r] = docs(browser)
    assert (r["dot"], r["unread"]) == ("red", 1)                # the wait is over; the person has an answer to read
    browser.hub.seen.mark("notes/busy.md", "c1", 2)
    assert docs(browser)[0]["dot"] == "blue"


def test_an_ask_running_on_the_document_makes_the_dot_orange_and_it_goes_back_when_the_ask_ends(browser, notes):
    """SPEC 8.6: orange is "an Ask or Tell is running", the same as on the index page."""
    assert docs(browser)[0]["dot"] == "blue"
    job, release = hold_job(browser.hub, "notes/busy.md")
    try:
        assert docs(browser)[0]["dot"] == "orange"
    finally:
        release.set()
    browser.hub.runner.join(5)
    assert docs(browser)[0]["dot"] == "blue"


def test_a_session_waiting_for_the_person_makes_the_dot_red(browser, notes):
    e = browser.hub.entry("notes/busy.md")
    e.live.await_reply("c1")
    e.live.observe(State("waiting", "Which pears?"))
    assert docs(browser)[0]["dot"] == "red"


# ── which files are documents (8.6) ──────────────────────────────────────────

def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_in_a_git_root_tracked_and_untracked_files_count_and_ignored_ones_do_not(browser, tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / ".gitignore").write_text("ignored.md\nbuild/\n", encoding="utf-8")
    for n in ("tracked.md", "ignored.md", "build/b.md", "node_modules/pkg/readme.md",
              "docs/deep/untracked.md", "notes.txt"):
        doc(repo, n)
    git(repo, "add", "tracked.md")
    browser.hub.roots.for_document(repo / "tracked.md")
    for n in ("tracked.md", "docs/deep/untracked.md", "ignored.md", "node_modules/pkg/readme.md"):
        comment(repo / n)
    assert names(docs(browser)) == ["proj/docs/deep/untracked.md", "proj/tracked.md"]


def test_in_a_plain_folder_hidden_folders_and_node_modules_are_not_walked(browser, tmp_path):
    root = tmp_path / "wiki"
    for n in ("a.md", "sub/b.md", ".hidden/c.md", "node_modules/d.md", ".git/e.md", "sub/.x/f.md"):
        doc(root, n)
    browser.hub.roots.for_document(root / "a.md")
    for n in ("a.md", "sub/b.md", ".hidden/c.md", "node_modules/d.md", ".git/e.md", "sub/.x/f.md"):
        comment(root / n)
    assert names(docs(browser)) == ["wiki/a.md", "wiki/sub/b.md"]


def test_a_link_out_of_the_root_is_not_listed_and_never_read(browser, tmp_path):
    root = tmp_path / "wiki"
    doc(root, "a.md")
    browser.hub.roots.for_document(root / "a.md")
    secret = doc(tmp_path / "private", "secret.md")
    comment(secret)
    (root / "link.md").symlink_to(secret)
    assert names(docs(browser, open_only=False)) == ["wiki/a.md"]


def test_a_root_whose_folder_has_gone_is_skipped(browser, notes, tmp_path):
    gone = doc(tmp_path / "gone", "g.md")
    browser.hub.roots.for_document(gone)
    gone.unlink()
    gone.parent.rmdir()
    assert names(docs(browser)) == ["notes/busy.md"]


@pytest.mark.parametrize("who", ["key", "token"])
def test_a_root_whose_folder_cannot_be_entered_is_a_row_that_says_why_and_names_no_folder(browser, notes, tmp_path,
                                                                                         closed, who):
    """The index says it under the root, `/_/index.json` in `closed` (8.6). 3.13 raised out of the call, which then
    listed no root at all; 3.14 skipped the root as one that holds nothing."""
    shut = doc(tmp_path / "locked" / "shut", "s.md")
    browser.hub.roots.for_document(shut)
    comment(shut)
    closed(tmp_path / "locked")
    token = Tokens().add("codex") if who == "token" else None
    told = {"root": "shut", "closed": "Permission denied"}
    rows = docs(browser, token=token)
    assert names(rows[:-1]) == ["notes/busy.md"] and rows[-1] == told
    assert docs(browser, token=token, open_only=False)[-1] == told
    assert docs(browser, token=token, root="shut") == [told]


def test_a_walked_root_stops_at_two_thousand_files(browser, tmp_path, monkeypatch):
    import sheafmd.mcp as mcp
    monkeypatch.setattr(mcp, "WALK_LIMIT", 3)
    root = tmp_path / "wiki"
    for i in range(6):
        doc(root, f"{i}.md")
    browser.hub.roots.for_document(root / "0.md")
    assert len(docs(browser, open_only=False)) == 3


# ── who may ask ──────────────────────────────────────────────────────────────

def test_a_token_sees_the_same_documents(browser, notes):
    token = Tokens().add("codex")
    is_error, rows = call(browser, "documents", token=token)
    assert not is_error and names(rows) == ["notes/busy.md"]


@pytest.mark.parametrize("args,why", [({"root": 5}, "root"), ({"open_only": "no"}, "open_only"),
                                      ({"nope": 1}, "nope")])
def test_documents_checks_its_arguments(browser, notes, args, why):
    assert why in refused(browser, "documents", **args)


# ── a git directory is not listed (8.2) ──────────────────────────────────────

@pytest.mark.parametrize("how", ["runs", *GIT_FAILS])
@pytest.mark.parametrize("who", ["key", "token"])
def test_a_document_in_a_git_directory_is_not_listed_whether_its_root_is_a_git_repo_or_not(browser, tmp_path,
                                                                                           monkeypatch, who, how):
    """A walk enters a bare repo, whose name has no dot, and `git ls-files -o` lists what is in one."""
    wiki, proj = tmp_path / "wiki", tmp_path / "proj"
    for top, repo in ((wiki, wiki / "sub"), (proj, proj)):
        repo.mkdir(parents=True)
        git(repo, "init", "-q")
        git(repo, "init", "-q", "--bare", "keep.git")
        browser.hub.roots.for_document(doc(top, "a.md"))
        for f in (top / "a.md", doc(repo, "b.md"), doc(repo, "keep.git/x.md"), doc(repo, "keep.git/refs/y.md")):
            comment(f)
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)
    token = Tokens().add("codex") if who == "token" else None
    assert names(docs(browser, token=token)) == ["proj/a.md", "proj/b.md", "wiki/a.md", "wiki/sub/b.md"]
