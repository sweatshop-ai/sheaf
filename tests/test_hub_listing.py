"""Which documents a root holds, and forgetting a root (SPEC 8.2, 8.6): the listing the index
page and `sheaf list` are made from."""
import errno
import os
import subprocess
import threading
from pathlib import Path

import pytest

from helpers import (BY_ID, GIT_FAILS, PLAN, comment, git_dirs_in, git_fails, hold_job, make_repo, md, page_meta,
                     write_executable)
from sheafmd import paths
from sheafmd.blocks import split_md_blocks
from sheafmd.hub import roots
from sheafmd.hub import state as hub_state
from sheafmd.hub.core import Hub
from sheafmd.source import md_hash


def git(cwd: Path, *args: str):
    subprocess.run(["git", "-c", "user.name=G", "-c", "user.email=g@example.com", *args],
                   cwd=cwd, check=True, capture_output=True, text=True)


def listed(root: roots.Root) -> list[str]:
    return [d.rel for d in roots.list_documents(root).docs]


# ── a git root: what git says is there (8.6) ─────────────────────────────────

@pytest.fixture
def repo(tmp_path):
    return roots.Root("proj", make_repo(tmp_path / "proj"), True)


def test_a_git_root_lists_tracked_and_untracked_markdown(repo):
    md(repo.path / "tracked.md")
    git(repo.path, "add", "tracked.md")
    md(repo.path / "docs" / "new.md")
    md(repo.path / "notes.txt")
    assert listed(repo) == ["docs/new.md", "tracked.md"]


def test_a_git_root_leaves_out_what_gitignore_ignores(repo):
    md(repo.path / ".gitignore", "drafts/\n*.tmp.md\n")
    md(repo.path / "drafts" / "x.md")
    md(repo.path / "a.tmp.md")
    md(repo.path / "kept.md")
    assert listed(repo) == ["kept.md"]


def test_a_git_root_leaves_out_node_modules_at_any_depth_and_never_lists_git(repo):
    md(repo.path / "node_modules" / "pkg" / "README.md")
    md(repo.path / "web" / "node_modules" / "pkg" / "README.md")
    md(repo.path / "a.md")
    assert listed(repo) == ["a.md"]


def test_a_git_root_leaves_out_a_tracked_file_that_was_deleted(repo):
    md(repo.path / "gone.md")
    md(repo.path / "here.md")
    git(repo.path, "add", ".")
    (repo.path / "gone.md").unlink()
    assert listed(repo) == ["here.md"]


def test_a_git_root_lists_names_with_spaces_and_non_ascii_letters(repo):
    md(repo.path / "a b" / "ünï #1.md")
    assert listed(repo) == ["a b/ünï #1.md"]


def test_a_git_root_that_git_cannot_read_is_walked_instead(tmp_path):
    folder = tmp_path / "was-a-repo"
    md(folder / "a.md")
    md(folder / ".hidden" / "b.md")
    assert listed(roots.Root("x", folder.resolve(), True)) == ["a.md"]


@pytest.mark.parametrize("fake_git", [None, "fatal: detected dubious ownership in repository"])
def test_a_git_root_when_git_gives_no_answer_lists_nothing_rather_than_what_it_ignores(
        repo, tmp_path, monkeypatch, fake_git):
    md(repo.path / ".gitignore", "private/\n")
    md(repo.path / "private" / "notes.md")
    md(repo.path / "kept.md")
    assert listed(repo) == ["kept.md"]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if fake_git:                     # git is there and refuses; otherwise git is not there at all
        script = bin_dir / "git"
        write_executable(script, f"#!/bin/sh\necho '{fake_git}' >&2\nexit 128\n")
    monkeypatch.setenv("PATH", str(bin_dir))
    assert listed(repo) == []


# ── another root: a walk (8.6, D15) ──────────────────────────────────────────

@pytest.fixture
def plain(tmp_path):
    return roots.Root("wiki", (tmp_path / "wiki").resolve(), False)


def test_a_plain_root_is_walked_and_sorted(plain):
    for p in ("b.md", "a/z.md", "a/y.md", "c/d/e.md", "a/note.txt"):
        md(plain.path / p)
    assert listed(plain) == ["a/y.md", "a/z.md", "b.md", "c/d/e.md"]


def test_a_plain_root_skips_git_node_modules_and_dot_folders(plain):
    for p in (".git/x.md", "node_modules/x.md", "a/node_modules/x.md", ".cache/x.md",
              "a/.hidden/x.md", "kept.md", ".dotfile.md"):
        md(plain.path / p)
    assert listed(plain) == [".dotfile.md", "kept.md"]


def test_a_plain_root_stops_at_the_cap_and_says_how_many_more(plain, monkeypatch):
    monkeypatch.setattr(roots, "LIST_CAP", 3)
    for i in range(7):
        md(plain.path / f"d{i}.md")
    got = roots.list_documents(plain)
    assert [d.rel for d in got.docs] == ["d0.md", "d1.md", "d2.md"] and got.more == 4


def test_a_git_root_stops_at_the_cap_and_says_how_many_more(repo, monkeypatch):
    """The cap holds for what git lists too: a repository with thousands of documents is not
    parsed in full at every sweep."""
    monkeypatch.setattr(roots, "LIST_CAP", 3)
    for i in range(7):
        md(repo.path / f"d{i}.md")
    md(repo.path / "zz.txt")
    got = roots.list_documents(repo)
    assert [d.rel for d in got.docs] == ["d0.md", "d1.md", "d2.md"] and got.more == 4


def test_a_git_root_counts_past_the_cap_only_what_it_would_list(repo, tmp_path, monkeypatch):
    """"and N more" are documents the root holds: not a tracked file deleted from the work tree
    (`ls-files -c` still names it), a bare repo's page (8.2 keeps it from the root), a link that
    leads out of the root, or a folder whose name ends in `.md`."""
    monkeypatch.setattr(roots, "LIST_CAP", 3)
    for i in range(7):
        md(repo.path / f"d{i}.md")
    md(repo.path / "gone.md")
    git(repo.path, "add", "gone.md")
    (repo.path / "gone.md").unlink()
    git(repo.path, "init", "-q", "--bare", "keep.git")
    md(repo.path / "keep.git" / "x.md")
    md(tmp_path / "outside.md")
    (repo.path / "out.md").symlink_to(tmp_path / "outside.md")
    md(repo.path / "folder.md" / "inner.txt")
    got = roots.list_documents(repo)
    assert [d.rel for d in got.docs] == ["d0.md", "d1.md", "d2.md"] and got.more == 4


def test_a_plain_root_counts_past_the_cap_only_what_it_would_list(plain, tmp_path, monkeypatch):
    """The walk counts as git does: a bare repo's page, a link out of the root and a name a URL
    cannot carry are left out of "and N more" as they are left out of the list."""
    monkeypatch.setattr(roots, "LIST_CAP", 3)
    for i in range(7):
        md(plain.path / f"d{i}.md")
    git_dirs_in(plain.path, "# T\n")                   # sub/keep.git/x.md is the bare repo's; sub/b.md is kept
    md(tmp_path / "outside.md")
    (plain.path / "out.md").symlink_to(tmp_path / "outside.md")
    try:                                               # APFS refuses the name (EILSEQ): there it cannot be counted
        os.close(os.open(os.path.join(os.fsencode(plain.path), b"\xff.md"), os.O_CREAT | os.O_WRONLY))
    except OSError as e:
        if e.errno != errno.EILSEQ:
            raise
    got = roots.list_documents(plain)
    assert [d.rel for d in got.docs] == ["d0.md", "d1.md", "d2.md"] and got.more == 5


def stats_for_names_past_the_cap(root, monkeypatch, per_folder: int) -> int:
    """The `lstat` and `stat` calls (`islink` and `realpath` make theirs through `os.lstat`) one
    listing makes of `root`, which holds three folders of `per_folder` documents, cap 3."""
    monkeypatch.setattr(roots, "LIST_CAP", 3)
    for folder in ("a", "b", "c"):
        for i in range(per_folder):
            md(root.path / folder / f"d{i:03}.md")
    calls = []
    for name in ("lstat", "stat"):
        real = getattr(os, name)
        monkeypatch.setattr(os, name, lambda *a, _real=real, **k: (calls.append(1), _real(*a, **k))[1])
    got = roots.list_documents(root)
    assert got.more == 3 * per_folder - 3
    return len(calls)


@pytest.mark.parametrize("git_root", [False, True])
def test_a_root_costs_one_stat_for_each_name_past_the_cap(tmp_path, monkeypatch, git_root):
    """"and N more" is judged at every sweep: a name past the cap costs the one `lstat` that tells it
    is a regular file, not a stat to see whether it is a link and another for its size."""
    def root(name):
        return roots.Root(name, make_repo(tmp_path / name) if git_root else tmp_path / name, git_root)
    few = stats_for_names_past_the_cap(root("few"), monkeypatch, 10)
    many = stats_for_names_past_the_cap(root("many"), monkeypatch, 20)
    assert many - few <= 3 * (20 - 10)                  # three folders, ten more names in each, one call each


def mixed_tree(root: roots.Root, outside: Path) -> None:
    md(root.path / "a.md")
    md(root.path / "docs" / "b.md")
    md(root.path / "docs" / "deep" / "c.md")
    (root.path / "folder.md").mkdir()
    md(outside / "out.md")
    md(outside / "dir" / "o.md")
    (root.path / "inlink.md").symlink_to(root.path / "a.md")
    (root.path / "outlink.md").symlink_to(outside / "out.md")
    (root.path / "dirlink").symlink_to(root.path / "docs")
    (root.path / "outdir").symlink_to(outside / "dir")
    (root.path / "broken.md").symlink_to(root.path / "nothing.md")


@pytest.mark.parametrize("cap", [2000, 3])
@pytest.mark.parametrize("git_root", [False, True])
def test_a_listing_of_a_tree_with_links_lists_only_the_regular_files_inside_the_root(
        tmp_path, monkeypatch, git_root, cap):
    """Pins `list_documents` on files, folders, a link to a file, a link to a folder (inside the root
    and out of it) and a broken link, with the cap out of reach and at 3."""
    monkeypatch.setattr(roots, "LIST_CAP", cap)
    path = make_repo(tmp_path / "r") if git_root else tmp_path / "r"
    root = roots.Root("r", path, git_root)
    mixed_tree(root, tmp_path / "outside")
    got = roots.list_documents(root)
    every = ["a.md", "docs/b.md", "docs/deep/c.md", "inlink.md"]     # not the links out, the broken one or a folder
    walked = ["a.md", "inlink.md", "docs/b.md", "docs/deep/c.md"]       # the walk's order: a folder's files, then its folders
    assert [d.rel for d in got.docs] == sorted((every if git_root else walked)[:cap])
    assert got.more == len(every) - min(cap, len(every))
    assert all(d.stat.st_size == os.stat(path / d.rel).st_size for d in got.docs)


def test_the_cap_is_two_thousand_files():
    assert roots.LIST_CAP == 2000


# ── what a git directory holds is no root's (8.2) ────────────────────────────

@pytest.mark.parametrize("how", ["runs", *GIT_FAILS])
def test_a_plain_root_leaves_out_what_its_git_directories_hold(plain, monkeypatch, tmp_path, how):
    """The walk enters a bare repo, whose name has no dot. 8.2 gives what it holds the folder's own
    root, and the door names it no document under this one (12); the work tree of the repo around it
    stays this root's."""
    git_dirs_in(plain.path, "# T\n")
    md(plain.path / "sub" / "keep.git" / "refs" / "y.md")
    md(plain.path / "a.md")
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)
    assert listed(plain) == ["a.md", "sub/b.md"]


def test_a_git_root_leaves_out_what_a_bare_repo_inside_it_holds(repo):
    """`git ls-files -o` lists the files of a bare repo inside the work tree."""
    git(repo.path, "init", "-q", "--bare", "keep.git")
    for p in ("keep.git/x.md", "keep.git/refs/y.md", "a.md"):
        md(repo.path / p)
    assert listed(repo) == ["a.md"]


@pytest.mark.parametrize("how", ["runs", *GIT_FAILS])
def test_a_work_tree_inside_a_git_directory_is_listed_where_git_runs_and_left_out_where_it_fails(
        plain, monkeypatch, tmp_path, how):
    """As the door reaches it by address (8.2: a work tree to git keeps rule 1; where git refuses to
    run it is closed with the git directory that holds it)."""
    seed = make_repo(tmp_path / "seed")
    md(seed / "s.md")
    git(seed, "add", "s.md")
    git(seed, "commit", "-q", "-m", "s")
    plain.path.mkdir()
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(plain.path / "wiki.git"))
    git(plain.path / "wiki.git", "worktree", "add", "-q", "-b", "side", "w1")
    md(plain.path / "a.md")
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)
    assert listed(plain) == (["a.md", "wiki.git/w1/s.md"] if how == "runs" else ["a.md"])


def test_listing_asks_git_nothing_of_a_folder_not_shaped_like_a_git_directory(plain, repo,
                                                                              monkeypatch):
    """The index lists every root at every look: the closure costs no git run where no git
    directory can be."""
    for top in (plain.path, repo.path):
        for p in ("a.md", "x/b.md", "x/y/c.md"):
            md(top / p)
    asked, run = [], subprocess.run

    def spy(argv, *args, **kw):
        if "rev-parse" in argv:
            asked.append(argv)
        return run(argv, *args, **kw)
    monkeypatch.setattr(subprocess, "run", spy)
    assert listed(plain) == listed(repo) == ["a.md", "x/b.md", "x/y/c.md"]
    assert asked == []


def test_a_document_comes_with_its_stat(plain):
    f = md(plain.path / "a.md", "hello\n")
    d = roots.list_documents(plain).docs[0]
    assert d.stat.st_size == 6 and d.stat.st_mtime_ns == f.stat().st_mtime_ns


# ── both: what is not served is not listed ───────────────────────────────────

@pytest.mark.parametrize("kind", ["git", "plain"])
def test_a_symlink_out_of_the_root_is_not_listed(tmp_path, kind):
    r = (roots.Root("proj", make_repo(tmp_path / "proj"), True) if kind == "git"
         else roots.Root("proj", (tmp_path / "proj").resolve(), False))
    outside = md(tmp_path / "elsewhere" / "secret.md", "secret\n")
    md(r.path / "a.md")
    (r.path / "link.md").symlink_to(outside)
    (r.path / "dir").symlink_to(outside.parent)
    assert listed(r) == ["a.md"]


def test_a_tracked_file_under_a_folder_that_became_a_link_out_of_the_root_is_not_listed(tmp_path):
    """git lists `docs/a.md` while it is tracked, though `docs` is now a link to a folder outside the
    root, where `resolve` refuses it: the listing must not name what the root does not serve."""
    r = roots.Root("proj", make_repo(tmp_path / "proj"), True)
    md(r.path / "a.md")
    md(r.path / "docs" / "a.md")
    git(r.path, "add", "a.md", "docs/a.md")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    md(outside / "a.md", "secret\n")
    (r.path / "docs" / "a.md").unlink()
    (r.path / "docs").rmdir()
    (r.path / "docs").symlink_to(outside)
    assert listed(r) == ["a.md"]


def test_a_tracked_file_under_a_folder_that_became_a_link_inside_the_root_is_listed(tmp_path):
    """The control: a folder link that stays inside the root is served, so its tracked file is listed."""
    r = roots.Root("proj", make_repo(tmp_path / "proj"), True)
    md(r.path / "docs" / "a.md")
    git(r.path, "add", "docs/a.md")
    md(r.path / "real" / "a.md")
    (r.path / "docs" / "a.md").unlink()
    (r.path / "docs").rmdir()
    (r.path / "docs").symlink_to(r.path / "real")
    assert "docs/a.md" in listed(r)


def test_a_tracked_file_under_a_folder_that_became_a_link_into_the_roots_sheaf_folder_is_not_listed(tmp_path):
    """#38: inside the root, but in its `.sheaf/`, which `resolve` refuses whether or not the file is a link."""
    r = roots.Root("proj", make_repo(tmp_path / "proj"), True)
    md(r.path / "a.md")
    md(r.path / "docs" / "v.md")
    git(r.path, "add", "a.md", "docs/v.md")
    md(r.path / ".sheaf" / "versions" / "0123456789abcdef" / "v.md")
    (r.path / "docs" / "v.md").unlink()
    (r.path / "docs").rmdir()
    (r.path / "docs").symlink_to(r.path / ".sheaf" / "versions" / "0123456789abcdef")
    assert listed(r) == ["a.md"]


@pytest.mark.parametrize("kind", ["git", "plain"])
def test_a_symlink_that_stays_inside_the_root_is_listed(tmp_path, kind):
    r = (roots.Root("proj", make_repo(tmp_path / "proj"), True) if kind == "git"
         else roots.Root("proj", (tmp_path / "proj").resolve(), False))
    md(r.path / "a.md")
    (r.path / "alias.md").symlink_to(r.path / "a.md")
    assert listed(r) == ["a.md", "alias.md"]


@pytest.mark.parametrize("kind", ["git", "plain"])
def test_a_folder_named_like_a_markdown_file_is_not_listed(tmp_path, kind):
    r = (roots.Root("proj", make_repo(tmp_path / "proj"), True) if kind == "git"
         else roots.Root("proj", (tmp_path / "proj").resolve(), False))
    (r.path / "folder.md").mkdir(parents=True, exist_ok=True)
    md(r.path / "folder.md" / "inner.md")
    assert listed(r) == ["folder.md/inner.md"]


def test_a_dangling_symlink_is_not_listed(plain):
    md(plain.path / "a.md")
    (plain.path / "dead.md").symlink_to(plain.path / "nowhere.md")
    assert listed(plain) == ["a.md"]


def test_a_root_whose_folder_is_gone_lists_nothing_and_is_missing(tmp_path):
    r = roots.Root("gone", tmp_path / "gone", False)
    assert roots.list_documents(r).docs == [] and r.missing()
    (tmp_path / "gone").mkdir()
    assert not r.missing()


# ── forgetting a root (8.2) ──────────────────────────────────────────────────

def test_forgetting_a_root_removes_it_and_it_stays_removed(tmp_path):
    reg = roots.Roots()
    a = reg.for_document(md(tmp_path / "x" / "notes" / "a.md"))
    b = reg.for_document(md(tmp_path / "y" / "notes" / "a.md"))
    assert reg.forget(a.name) == a
    assert [r.name for r in reg.all()] == [b.name]
    assert [r.name for r in roots.Roots().all()] == [b.name]


def test_forgetting_a_name_that_is_not_a_root_is_none(tmp_path):
    assert roots.Roots().forget("nothing") is None


def test_the_folder_of_a_forgotten_root_is_a_root_again_when_a_document_in_it_is_named(tmp_path):
    reg = roots.Roots()
    doc = md(tmp_path / "x" / "notes" / "a.md")
    first = reg.for_document(doc)
    reg.forget(first.name)
    assert reg.for_document(doc).name == first.name


def test_the_hub_forgets_a_root_with_its_documents_entries(tmp_path):
    hub = Hub(port=27419, key=paths.ensure_key(), started_by="test")
    keep = md(tmp_path / "keep" / "a.md")
    drop = md(tmp_path / "drop" / "a.md")
    for f in (keep, drop):
        hub.render(f, {}, None)
    hub.seen.mark("drop/a.md", "c1", 2)
    hub.seen.mark("keep/a.md", "c1", 1)
    assert hub.forget_root("drop").name == "drop"
    assert "drop/a.md" not in hub.entries and "keep/a.md" in hub.entries
    assert hub.docs.get("drop/a.md") == {} and hub.docs.get("keep/a.md") != {}
    assert hub.seen.get("drop/a.md") == {} and hub.seen.get("keep/a.md") == {"c1": 1}
    assert hub.roots.get("drop") is None
    assert hub.forget_root("drop") is None


def test_forgetting_a_root_cancels_the_asks_and_tells_running_on_its_documents(tmp_path):
    hub = Hub(port=27419, key=paths.ensure_key(), started_by="test")
    for f in (md(tmp_path / "drop" / "a.md"), md(tmp_path / "keep" / "a.md")):
        hub.render(f, {}, None)
    ask, release_ask = hold_job(hub, "drop/a.md", "c1", "ask")
    tell, release_tell = hold_job(hub, "drop/a.md", "c2", "tell")
    stop, release_stop = hold_job(hub, "drop/a.md", "c2", "stop")
    kept, release_kept = hold_job(hub, "keep/a.md", "c1", "ask")
    try:
        assert hub.forget_root("drop").name == "drop"
        assert (ask.cancelled, tell.cancelled) == (True, True)
        assert (stop.cancelled, kept.cancelled) == (False, False)    # the stop message goes on
        # The job's thread may take a moment to end; the name must not read as asked meanwhile.
        assert hub.jobs_asking() == [["keep/a.md", "c1"]]
        assert hub.jobs()["asking"] == [["keep/a.md", "c1"]]
    finally:
        for r in (release_ask, release_tell, release_stop, release_kept):
            r.set()
        hub.runner.join(5)


def test_a_page_of_a_forgotten_root_cannot_save_into_a_new_folder_that_takes_the_name(
        browser, tmp_path):
    """A name freed by `forget` goes to the next folder of that name. A page still open on the
    old document holds a version the hub must no longer know, or its save would be merged
    into a document it was never made from."""
    hub = browser.hub
    hub.render(md(tmp_path / "x" / "notes" / "a.md", PLAN), {}, None)
    assert hub.forget_root("notes").name == "notes"
    new = md(tmp_path / "y" / "notes" / "a.md", PLAN + "\nThe new document.\n")
    assert hub.render(new, {}, None)["doc"] == "notes/a.md"
    block = next(i for i, b in enumerate(split_md_blocks(PLAN))
                 if b.content.startswith("Second paragraph"))
    r = browser.post("/_/save", {"doc": "notes/a.md", "hash": md_hash(PLAN),
                                 "edits": [{"i": block, "html": "<p>From the old page.</p>"}]})
    assert r.status == 409
    assert new.read_text(encoding="utf-8") == PLAN + "\nThe new document.\n"


def test_a_page_opened_by_its_url_and_never_rendered_cannot_save_into_the_folder_that_takes_the_name(
        browser, tmp_path):
    """`forget` finds a document's versions by the addresses in docs.json and seen.json. A
    document opened by its URL and never rendered is in neither; its versions are on disk
    all the same, and after a restart the old page's save would merge into the folder that
    takes the name."""
    from sheafmd.hub.handler import Handler
    from helpers import Browser
    old = md(tmp_path / "x" / "notes" / "a.md", PLAN)
    browser.hub.roots.for_document(old)
    assert browser.get("/notes/a.md").status == 200
    assert browser.hub.docs.get("notes/a.md") == {} and browser.hub.seen.get("notes/a.md") == {}
    again = Browser(h := Hub(port=browser.hub.port, key=paths.ensure_key(), started_by="test"),
                    Handler(h))
    assert again.hub.forget_root("notes").name == "notes"
    new = md(tmp_path / "y" / "notes" / "a.md", PLAN + "\nThe new document.\n")
    assert again.hub.render(new, {}, None)["doc"] == "notes/a.md"
    block = next(i for i, b in enumerate(split_md_blocks(PLAN))
                 if b.content.startswith("Second paragraph"))
    r = again.post("/_/save", {"doc": "notes/a.md", "hash": md_hash(PLAN),
                               "edits": [{"i": block, "html": "<p>From the old page.</p>"}]})
    assert r.status == 409
    assert new.read_text(encoding="utf-8") == PLAN + "\nThe new document.\n"


def test_a_page_asked_for_while_the_hub_forgets_its_root_does_not_come_back(browser, tmp_path,
                                                                           monkeypatch):
    """The hub takes the root out of its registry before it drops the root's entries. A request for one
    of its pages that comes meanwhile finds no such document; one that found it would make its entry
    again once the forget let go of the hub, with the old file's versions on disk under the address,
    and the folder that takes the name would be served the old file and, after a restart, take the
    old page's save."""
    from sheafmd.hub.handler import Handler
    from helpers import Browser
    hub = browser.hub
    hub.render(md(tmp_path / "x" / "notes" / "a.md", PLAN), {}, None)
    real, asked = hub.docs.forget_prefix, {}

    def meanwhile(prefix):
        t = threading.Thread(target=lambda: asked.setdefault("status", browser.get("/notes/a.md").status))
        t.start()
        t.join(1)                       # it found the document, and waits for the hub's lock
        asked["thread"] = t
        return real(prefix)
    monkeypatch.setattr(hub.docs, "forget_prefix", meanwhile)
    assert hub.forget_root("notes").name == "notes"
    asked["thread"].join(10)
    assert asked["status"] == 404 and "notes/a.md" not in hub.entries
    new = md(tmp_path / "y" / "notes" / "a.md", PLAN + "\nThe new document.\n")
    assert hub.render(new, {}, None)["doc"] == "notes/a.md"
    assert hub.entries["notes/a.md"].path == new.resolve()
    again = Browser(h := Hub(port=hub.port, key=paths.ensure_key(), started_by="test"), Handler(h))
    block = next(i for i, b in enumerate(split_md_blocks(PLAN)) if b.content.startswith("Second paragraph"))
    r = again.post("/_/save", {"doc": "notes/a.md", "hash": md_hash(PLAN),
                               "edits": [{"i": block, "html": "<p>From the old page.</p>"}]})
    assert r.status == 409
    assert new.read_text(encoding="utf-8") == PLAN + "\nThe new document.\n"


def test_a_page_whose_file_was_found_just_before_its_root_was_forgotten_is_not_made(browser, tmp_path,
                                                                                   monkeypatch):
    """A document's entry is made under the hub's lock, its file found before. A forget that took the
    lock in between must not find the entry made after it: it would stay under the name the next
    folder takes, holding the old file."""
    hub = browser.hub
    hub.roots.for_document(md(tmp_path / "x" / "notes" / "a.md", PLAN))
    real = hub.roots.document

    def forgotten_meanwhile(address):
        found = real(address)
        monkeypatch.setattr(hub.roots, "document", real)
        assert hub.forget_root("notes").name == "notes"
        return found
    monkeypatch.setattr(hub.roots, "document", forgotten_meanwhile)
    assert browser.get("/notes/a.md").status == 404
    assert "notes/a.md" not in hub.entries
    new = md(tmp_path / "y" / "notes" / "a.md", PLAN + "\nThe new document.\n")
    assert hub.render(new, {}, None)["doc"] == "notes/a.md"
    assert hub.entries["notes/a.md"].path == new.resolve()


@pytest.mark.parametrize("op, fields", BY_ID, ids=[op for op, _ in BY_ID])
def test_a_page_of_a_forgotten_root_cannot_act_on_a_comment_of_the_folder_that_takes_the_name(
        browser, tmp_path, op, fields):
    """A comment is found by its id, and the folder that takes the name has a c1 of its own. The
    old page's version is one the new document never handed out, so nothing is written to it;
    the new document's own page still writes."""
    hub = browser.hub
    old = md(tmp_path / "x" / "notes" / "a.md", PLAN)
    comment(old, body="The old question.")
    hub.render(old, {}, None)
    old_hash = md_hash(old.read_text(encoding="utf-8"))
    assert hub.forget_root("notes").name == "notes"
    new = md(tmp_path / "y" / "notes" / "a.md", PLAN + "\nThe new document.\n")
    comment(new, quote="First paragraph", body="The new question.")
    assert hub.render(new, {}, None)["doc"] == "notes/a.md"
    kept = new.read_text(encoding="utf-8")
    r = browser.post("/_/comment", {"doc": "notes/a.md", "op": op, "hash": old_hash, **fields})
    assert r.status == 409, r.json()
    assert "no longer known to the hub" in r.json()["error"]
    assert new.read_text(encoding="utf-8") == kept
    assert browser.post("/_/comment", {"doc": "notes/a.md", "op": op, "hash": md_hash(kept),
                                       **fields}).status == 200
    assert new.read_text(encoding="utf-8") != kept


@pytest.mark.parametrize("write", ["reply", "save", "answer"])
def test_a_write_under_way_while_its_root_is_forgotten_leaves_no_version_the_next_folder_knows(
        browser, tmp_path, monkeypatch, write):
    """A page's write still under way when its root is forgotten puts the text it wrote among the
    document's versions on disk after the forget dropped them, and the page takes that text's hash.
    Once another folder takes the name, the document there would know the hash, and take the old
    page's comment by id, its Ask, its Tell or its save as made against a version it handed out. An
    Ask's answer is written as the job writes it, and the page takes its hash from `ask-done`."""
    hub = browser.hub
    old = md(tmp_path / "x" / "notes" / "a.md", PLAN)
    comment(old, body="The old question.")
    hub.render(old, {}, None)
    forget, done = [], {}

    def forgotten_meanwhile():
        t = threading.Thread(target=lambda: done.setdefault("root", hub.forget_root("notes")))
        t.start()
        t.join(1)                       # the forget waits for the write to end
        forget.append(t)
    live = hub.entries["notes/a.md"].live
    monkeypatch.setattr(live, "_after_write", forgotten_meanwhile)
    held = md_hash(old.read_text(encoding="utf-8"))
    block = next(i for i, b in enumerate(split_md_blocks(PLAN)) if b.content.startswith("Second paragraph"))
    if write == "answer":
        adopted = live.reply_as("c1", "Under way.", "Claude", "answer", "ask-done")["hash"]
    else:
        r = (browser.post("/_/comment", {"doc": "notes/a.md", "op": "reply", "id": "c1", "hash": held,
                                         "body": "Under way."}) if write == "reply" else
             browser.post("/_/save", {"doc": "notes/a.md", "hash": held,
                                      "edits": [{"i": block, "html": "<p>Under way.</p>"}]}))
        assert r.status == 200, r.json()
        adopted = r.json()["hash"]
    forget[0].join(10)
    assert done["root"].name == "notes" and "notes/a.md" not in hub.entries
    assert adopted == md_hash(old.read_text(encoding="utf-8"))
    assert hub.versions.get("notes/a.md", adopted) is None
    new = md(tmp_path / "y" / "notes" / "a.md", PLAN + "\nThe new document.\n")
    comment(new, quote="First paragraph", body="The new question.")
    assert hub.render(new, {}, None)["doc"] == "notes/a.md"
    kept = new.read_text(encoding="utf-8")
    assert browser.post("/_/comment", {"doc": "notes/a.md", "op": "reply", "id": "c1", "hash": adopted,
                                       "body": "From the old page."}).status == 409
    assert browser.post("/_/save", {"doc": "notes/a.md", "hash": adopted,
                                    "edits": [{"i": block, "html": "<p>From the old page.</p>"}]}).status == 409
    assert new.read_text(encoding="utf-8") == kept


def test_a_document_stream_open_when_its_root_is_forgotten_is_told_the_document_is_gone(browser, tmp_path):
    """Its entry goes, and with it the stream's bus: a page told nothing would go on listening to a
    document the hub no longer serves, and after a reconnect find another folder's under the address."""
    hub = browser.hub
    hub.render(md(tmp_path / "x" / "notes" / "a.md", PLAN), {}, None)
    hub.render(md(tmp_path / "x" / "keep" / "b.md", PLAN), {}, None)
    tab, other = (browser.get(f"/_/live?doc={d}").stream for d in ("notes/a.md", "keep/b.md"))
    assert [n for n, _ in tab.drain()] == [n for n, _ in other.drain()] == ["hello"]
    assert hub.forget_root("notes").name == "notes"
    assert tab.drain() == [("gone", {"doc": "notes/a.md"})]
    assert other.drain() == []


def test_a_document_stream_that_opens_as_its_root_is_forgotten_is_told_the_document_is_gone(
        browser, tmp_path, monkeypatch):
    """The route finds the entry before it subscribes: a forget in between drops the entry and tells
    the streams it had, and this one was not among them yet."""
    hub = browser.hub
    hub.render(md(tmp_path / "x" / "notes" / "a.md", PLAN), {}, None)
    real = hub.entry

    def forgotten_meanwhile(address):
        e = real(address)
        monkeypatch.setattr(hub, "entry", real)
        assert hub.forget_root("notes").name == "notes"
        return e
    monkeypatch.setattr(hub, "entry", forgotten_meanwhile)
    tab = browser.get("/_/live?doc=notes/a.md").stream
    assert [e for e in tab.drain() if e[0] != "hello"] == [("gone", {"doc": "notes/a.md"})]


def test_doc_names_the_root_under_the_addresss_name_whose_id_the_page_holds(browser, tmp_path):
    """A page carries the id of the root it was served from (10.1) and compares it with the one `/_/doc`
    names when its stream comes back (10.7). The folder that takes the name after a forget is another root,
    with another id, even with the very same text; the same root keeps its id whatever its file does, and
    the 404 of an address under its name names it too, or null once no root holds the name."""
    hub = browser.hub
    hub.render(md(tmp_path / "x" / "notes" / "a.md", PLAN), {}, None)
    first = hub.roots.get("notes").id
    assert first and page_meta(browser.get("/notes/a.md").text)["root"] == first
    assert browser.get("/_/doc?doc=notes/a.md").json()["root"] == first
    missing = browser.get("/_/doc?doc=notes/nothing.md")
    assert missing.status == 404 and missing.json() == {"ok": False, "error": "no such document", "root": first}
    assert hub.forget_root("notes").name == "notes"
    gone = browser.get("/_/doc?doc=notes/a.md")
    assert gone.status == 404 and gone.json() == {"ok": False, "error": "no such document", "root": None}
    assert hub.render(md(tmp_path / "y" / "notes" / "a.md", PLAN), {}, None)["doc"] == "notes/a.md"
    got = browser.get("/_/doc?doc=notes/a.md").json()
    assert got["hash"] == md_hash(PLAN) and got["root"] == hub.roots.get("notes").id != first
    assert page_meta(browser.get("/notes/a.md").text)["root"] == got["root"]
    assert "known" not in browser.get(f"/_/doc?doc=notes/a.md&hash={md_hash(PLAN)}").json()


def test_forgetting_a_root_leaves_no_version_of_its_documents_on_disk(tmp_path):
    reg, docs, seen, versions = roots.Roots(), hub_state.Docs(), hub_state.Seen(), hub_state.Versions()
    doc = md(tmp_path / "x" / "notes" / "a.md")
    root = reg.for_document(doc)
    docs.put("notes/a.md", {"path": str(doc)})
    keep = versions.put("keep/b.md", "# Keep\n")
    gone = versions.put("notes/a.md", "# Gone\n")
    assert roots.forget(reg, docs, seen, versions, root.name, members=hub_state.MemberSeen()).name == "notes"
    assert versions.get("notes/a.md", gone) is None
    assert versions.get("keep/b.md", keep) == "# Keep\n"


# ── the box: two repos and a folder outside git ──────────────────────────────

def test_two_repos_and_a_loose_folder_each_get_a_root_with_a_name_that_survives_a_restart(tmp_path):
    one = make_repo(tmp_path / "a" / "site")
    two = make_repo(tmp_path / "b" / "site")
    loose = tmp_path / "scratch"
    docs = [md(one / "docs" / "x.md"), md(two / "y.md"), md(loose / "z.md")]
    hub = Hub(port=27419, key=paths.ensure_key(), started_by="test")
    got = [hub.render(f, {}, None)["doc"] for f in docs]
    assert got == ["site/docs/x.md", "site-2/y.md", "scratch/z.md"]
    assert [(r.name, r.git) for r in hub.roots.all()] == [("site", True), ("site-2", True),
                                                          ("scratch", False)]
    again = Hub(port=27419, key=paths.ensure_key(), started_by="test")
    assert sorted((r.name, r.path, r.git) for r in again.roots.all()) == sorted(
        (r.name, r.path, r.git) for r in hub.roots.all())
    assert [again.render(f, {}, None)["doc"] for f in reversed(docs)] == list(reversed(got))
    assert os.path.realpath(again.roots.resolve("site-2/y.md")) == str(two / "y.md")


# ── the route (the key) ──────────────────────────────────────────────────────

def test_forget_by_the_key_removes_the_root_and_says_what_it_was(browser, work):
    f = md(work / "plan.md")
    browser.post("/_/render", {"path": str(f)}, key=True, cookie=False)
    r = browser.post("/_/forget", {"name": "work"}, key=True, cookie=False)
    assert r.status == 200 and r.json() == {"ok": True, "name": "work", "path": str(work.resolve())}
    assert browser.hub.roots.get("work") is None
    assert browser.get("/work/plan.md").status == 404


def test_forget_of_a_name_that_is_no_root_is_404(browser):
    r = browser.post("/_/forget", {"name": "nothing"}, key=True, cookie=False)
    assert r.status == 404 and r.json() == {"ok": False, "error": "no such root"}


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": 3}, {"name": ["work"]}])
def test_forget_needs_a_name(browser, body):
    assert browser.post("/_/forget", body, key=True, cookie=False).status == 400


def test_forget_is_for_the_key_and_not_for_a_page(browser, work):
    md(work / "plan.md")
    browser.hub.roots.for_document(work / "plan.md")
    assert browser.post("/_/forget", {"name": "work"}).status == 403              # the cookie
    assert browser.post("/_/forget", {"name": "work"}, cookie=False).status == 401
    assert browser.hub.roots.get("work") is not None
