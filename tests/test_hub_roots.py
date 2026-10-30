"""Roots: which folder a document belongs to, what it is called, and how an address in a
URL becomes a file again (SPEC 8.2, 8.3)."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from helpers import GIT_FAILS, git_fails, make_repo, md, undecodable_names_or_skip

from sheafmd import paths
from sheafmd.hub import roots


def git(cwd: Path, *args: str):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def commit(repo: Path):
    git(repo, "-c", "user.name=G", "-c", "user.email=g@example.com", "commit", "-q", "--allow-empty", "-m", "x")


# ── names ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("folder,name", [
    ("notes", "notes"), ("My Notes", "My-Notes"), ("a.b_c-d", "a.b_c-d"), (".hidden", "hidden"),
    ("_private", "private"), ("._x", "x"), ("é", "-"), ("a/b", "a-b"), ("...", "root"),
    ("", "root"), ("__", "root"), ("a b c", "a-b-c")])
def test_a_root_is_named_for_its_folder_cleaned(folder, name):
    assert roots.clean_name(folder) == name


def test_the_root_of_an_address_is_what_stands_before_the_first_slash():
    assert roots.Address.parse("proj/docs/a.md").root == "proj"
    assert roots.Address.parse("proj/a.md").root == "proj"
    assert roots.Address.parse("proj").root == "proj"           # no "/": the whole address
    assert roots.Address.parse("").root == ""


# ── the rules (8.2) ──────────────────────────────────────────────────────────

def test_inside_a_git_work_tree_the_root_is_its_top(tmp_path):
    repo = make_repo(tmp_path / "proj")
    r = roots.Roots().for_document(md(repo / "docs" / "deep" / "a.md"))
    assert (r.name, r.path, r.git) == ("proj", repo, True)


def test_each_worktree_is_its_own_root(tmp_path):
    repo = make_repo(tmp_path / "proj")
    commit(repo)
    wt = tmp_path / "proj-wt"
    git(repo, "worktree", "add", "-q", str(wt), "-b", "side")
    reg = roots.Roots()
    a, b = reg.for_document(md(repo / "a.md")), reg.for_document(md(wt / "a.md"))
    assert a.path == repo and b.path == wt.resolve() and a.name != b.name


def test_a_document_outside_git_and_outside_any_root_is_its_own_root(tmp_path):
    r = roots.Roots().for_document(md(tmp_path / "loose" / "a.md"))
    assert (r.name, r.path, r.git) == ("loose", (tmp_path / "loose").resolve(), False)


def test_a_document_inside_a_registered_plain_root_belongs_to_it(tmp_path):
    reg = roots.Roots()
    top = reg.for_document(md(tmp_path / "wiki" / "a.md"))
    inner = reg.for_document(md(tmp_path / "wiki" / "sub" / "deep" / "b.md"))
    assert inner == top


def test_the_deepest_registered_plain_root_wins(tmp_path):
    reg = roots.Roots()
    outer = reg.for_document(md(tmp_path / "wiki" / "a.md"))
    reg._add(tmp_path / "wiki" / "sub", git=False)           # a deeper one registered by hand
    deep = reg.for_document(md(tmp_path / "wiki" / "sub" / "x" / "b.md"))
    assert deep.path == (tmp_path / "wiki" / "sub").resolve() and deep != outer


def test_git_wins_over_a_registered_plain_root_around_it(tmp_path):
    reg = roots.Roots()
    reg.for_document(md(tmp_path / "wiki" / "a.md"))
    repo = make_repo(tmp_path / "wiki" / "code")
    assert reg.for_document(md(repo / "n.md")).path == repo


def test_a_second_folder_with_a_taken_name_gets_a_number(tmp_path):
    reg = roots.Roots()
    names = [reg.for_document(md(tmp_path / d / "notes" / "a.md")).name for d in "xyz"]
    assert names == ["notes", "notes-2", "notes-3"]


def test_names_never_start_with_an_underscore(tmp_path):
    r = roots.Roots().for_document(md(tmp_path / "_" / "a.md"))
    assert r.name == "root"


def test_a_name_that_is_not_free_after_cleaning_is_numbered(tmp_path):
    reg = roots.Roots()
    a = reg.for_document(md(tmp_path / "a" / "My Notes" / "x.md"))
    b = reg.for_document(md(tmp_path / "b" / "My-Notes" / "x.md"))
    assert (a.name, b.name) == ("My-Notes", "My-Notes-2")


# ── roots.json survives a restart ────────────────────────────────────────────

def test_names_are_saved_and_survive_a_restart(tmp_path):
    first = roots.Roots()
    a = first.for_document(md(tmp_path / "x" / "notes" / "a.md"))
    b = first.for_document(md(tmp_path / "y" / "notes" / "a.md"))
    saved = json.loads((paths.state_dir() / "roots.json").read_text())
    assert saved[a.name]["path"] == str(a.path) and saved[a.name]["git"] is False
    assert "added" in saved[a.name]
    again = roots.Roots()
    assert again.for_document(md(tmp_path / "y" / "notes" / "b.md")) == b
    assert again.for_document(md(tmp_path / "x" / "notes" / "b.md")) == a
    assert [r.name for r in again.all()] == ["notes", "notes-2"]


def test_each_root_has_an_id_that_survives_a_restart_and_a_forget_of_another_root(tmp_path):
    """The id a page compares when its stream comes back (10.7): random, kept in roots.json, the same
    after a restart and after `sheaf roots forget` of another root with no hub. A folder registered again
    after a forget is another root, with another id."""
    first = roots.Roots()
    a = first.for_document(md(tmp_path / "x" / "notes" / "a.md"))
    b = first.for_document(md(tmp_path / "y" / "keep" / "b.md"))
    assert a.id and b.id and a.id != b.id
    saved = json.loads((paths.state_dir() / "roots.json").read_text())
    assert (saved[a.name]["id"], saved[b.name]["id"]) == (a.id, b.id)
    assert roots.Roots().get(a.name) == a and roots.Roots().get(b.name) == b
    assert roots.forget_offline(a.name) == a
    assert json.loads((paths.state_dir() / "roots.json").read_text())[b.name]["id"] == b.id
    assert roots.Roots().get(b.name) == b
    again = roots.Roots().for_document(tmp_path / "x" / "notes" / "a.md")
    assert again.name == a.name and again.id not in (a.id, b.id)


def test_a_root_saved_without_an_id_gets_one_at_once_and_keeps_it(tmp_path):
    """A roots.json written before roots had ids: the first registry that writes gives each root one and
    saves it, so the next start reads the same one. A look that changes nothing on disk (`writes=False`)
    leaves the file as it is."""
    folder = tmp_path / "notes"
    folder.mkdir()
    f = paths.state_dir() / "roots.json"
    paths.private_dir(f.parent)
    old = {"notes": {"path": str(folder.resolve()), "git": False, "added": "2026-01-01T00:00:00+0000"}}
    f.write_text(json.dumps(old))
    assert roots.Roots(writes=False).get("notes").id
    assert json.loads(f.read_text()) == old
    got = roots.Roots().get("notes").id
    assert got and json.loads(f.read_text()) == {"notes": {**old["notes"], "id": got}}
    assert roots.Roots().get("notes").id == got


def test_a_root_is_added_by_a_document_never_by_a_scan(tmp_path):
    md(tmp_path / "unseen" / "a.md")
    assert roots.Roots().all() == []


def test_a_root_that_is_gone_keeps_its_name(tmp_path):
    reg = roots.Roots()
    r = reg.for_document(md(tmp_path / "gone" / "a.md"))
    (tmp_path / "gone" / "a.md").unlink()
    (tmp_path / "gone").rmdir()
    assert roots.Roots().get(r.name) == r


# ── address and path (8.3) ───────────────────────────────────────────────────

@pytest.fixture
def one(tmp_path):
    reg = roots.Roots()
    repo = make_repo(tmp_path / "proj")
    doc = md(repo / "docs" / "a b" / "plan.md")
    r = reg.for_document(doc)
    return reg, r, doc


def test_the_address_is_the_root_and_the_path_in_it(one):
    reg, r, doc = one
    assert reg.address(doc) == "proj/docs/a b/plan.md"


def test_an_address_resolves_back_to_its_file(one):
    reg, r, doc = one
    assert reg.resolve("proj/docs/a b/plan.md") == doc.resolve()


def test_the_url_is_the_address_with_each_segment_percent_encoded(one):
    reg, r, doc = one
    assert roots.url_path("proj/docs/a b/plan.md") == "/proj/docs/a%20b/plan.md"
    assert roots.url_path("proj/dir/ünï #1.md") == "/proj/dir/%C3%BCn%C3%AF%20%231.md"
    assert roots.address_of_url("/proj/docs/a%20b/plan.md") == "proj/docs/a b/plan.md"


@pytest.mark.parametrize("target", ["/", "", "/proj", "/proj/", "/proj/a%2Fb.md", "/proj//a.md",
                                    "/proj/a%00.md", "/proj/%ff.md"])
def test_a_url_that_is_not_an_address_has_none(target):
    assert roots.address_of_url(target) is None


@pytest.mark.parametrize("addr", [
    "proj/../../etc/passwd.md", "proj/docs/../../x.md", "proj/./docs/a b/plan.md",
    "nothere/docs/a b/plan.md", "proj/docs/a b/missing.md", "proj/docs/a b/plan.txt",
    "proj/docs/a b/plan.MD", "proj", "proj/", "", "proj//docs/a b/plan.md", "proj/docs",
    "_/x.md", "proj/docs/a b/plan.md/x.md", "proj/docs\\..\\a.md"])
def test_an_address_that_is_not_a_markdown_file_in_a_root_is_not_found(one, addr):
    reg, r, doc = one
    with pytest.raises(roots.NotFound):
        reg.resolve(addr)


def test_a_symlink_out_of_the_root_is_not_followed(one, tmp_path):
    reg, r, doc = one
    outside = md(tmp_path / "elsewhere" / "secret.md", "secret\n")
    (r.path / "docs" / "link.md").symlink_to(outside)
    (r.path / "docs" / "dir").symlink_to(outside.parent)
    with pytest.raises(roots.NotFound):
        reg.resolve("proj/docs/link.md")
    with pytest.raises(roots.NotFound):
        reg.resolve("proj/docs/dir/secret.md")


def test_a_symlink_that_stays_inside_the_root_is_followed(one):
    reg, r, doc = one
    (r.path / "docs" / "alias.md").symlink_to(doc)
    assert reg.resolve("proj/docs/alias.md") == doc.resolve()


def test_a_folder_named_like_a_markdown_file_is_not_a_document(one):
    reg, r, doc = one
    (r.path / "docs" / "folder.md").mkdir()
    with pytest.raises(roots.NotFound):
        reg.resolve("proj/docs/folder.md")


# ── lookup: the same rules, and nothing registered (SPEC 9.7) ────────────────

def test_lookup_finds_the_root_for_document_would_give_and_registers_nothing(tmp_path):
    repo = make_repo(tmp_path / "proj")
    reg = roots.Roots()
    assert reg.lookup(md(repo / "docs" / "a.md")) is None and reg.all() == []
    made = reg.for_document(md(repo / "docs" / "a.md"))
    assert reg.lookup(md(repo / "b.md")) == made and reg.lookup(md(repo / "deep" / "c.md")) == made
    assert roots.Roots().lookup(repo / "b.md") == made                     # after a restart too
    assert len(reg.all()) == 1


def test_lookup_follows_the_nesting_rules_of_for_document(tmp_path):
    reg = roots.Roots()
    outer = reg.for_document(md(tmp_path / "wiki" / "a.md"))
    inner_repo = make_repo(tmp_path / "wiki" / "sub")
    # the repo is the document's root by rule 1 even though `wiki` holds it: not registered yet
    assert reg.lookup(md(inner_repo / "b.md")) is None
    assert reg.lookup(tmp_path / "wiki" / "other" / "c.md") == outer
    made = reg.for_document(inner_repo / "b.md")
    assert made.path == inner_repo and reg.lookup(inner_repo / "b.md") == made


def test_a_folder_that_is_not_there_is_judged_by_the_nearest_one_that_is(tmp_path):
    reg = roots.Roots()
    outer = reg.for_document(md(tmp_path / "wiki" / "a.md"))
    inner = reg.for_document(md(make_repo(tmp_path / "wiki" / "sub") / "b.md"))
    assert reg.lookup(inner.path / "guess" / "deeper" / "c.png") == inner
    assert reg.lookup(tmp_path / "wiki" / "guess" / "c.png") == outer
    gone = reg.for_document(md(tmp_path / "gone" / "d.md"))
    (gone.path / "d.md").unlink()
    gone.path.rmdir()
    assert reg.lookup(gone.path / "d.md") == gone                  # a root that is gone keeps its documents


@pytest.fixture
def gone_inside_a_repo(tmp_path):
    """A git root, `outer/wt`, registered and then removed, inside the git root `outer`."""
    reg = roots.Roots()
    reg.for_document(md(make_repo(tmp_path / "outer") / "a.md"))
    inner = reg.for_document(md(make_repo(tmp_path / "outer" / "wt") / "d.md"))
    subprocess.run(["rm", "-rf", str(inner.path)], check=True)
    return reg, inner


def test_a_git_root_that_is_gone_keeps_its_documents_inside_the_repo_that_held_it(gone_inside_a_repo):
    reg, inner = gone_inside_a_repo
    assert reg.lookup(inner.path / "d.md") == inner


def test_a_git_root_that_is_gone_keeps_its_documents_inside_a_root_that_is_not_a_repo(tmp_path):
    reg = roots.Roots()
    reg.for_document(md(tmp_path / "wiki" / "a.md"))
    inner = reg.for_document(md(make_repo(tmp_path / "wiki" / "r") / "d.md"))
    subprocess.run(["rm", "-rf", str(inner.path)], check=True)
    assert reg.lookup(inner.path / "x.png") == inner


def test_a_document_deeper_in_a_root_that_is_gone_is_that_roots_too(gone_inside_a_repo):
    reg, inner = gone_inside_a_repo
    assert reg.lookup(inner.path / "deep" / "e.md") == inner


@pytest.mark.skipif(os.geteuid() == 0, reason="root enters any folder")
def test_a_folder_git_cannot_enter_is_judged_by_the_nearest_one_it_can(tmp_path):
    reg = roots.Roots()
    reg.for_document(md(tmp_path / "wiki" / "a.md"))
    inner = reg.for_document(md(make_repo(tmp_path / "wiki" / "sub") / "b.md"))
    (inner.path / "locked").mkdir(mode=0)
    try:
        assert reg.lookup(inner.path / "locked" / "c.png") == inner
    finally:
        (inner.path / "locked").chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root enters any folder")
def test_a_root_git_cannot_enter_keeps_what_is_under_it(tmp_path):
    reg = roots.Roots()
    reg.for_document(md(tmp_path / "wiki" / "a.md"))
    inner = reg.for_document(md(make_repo(tmp_path / "wiki" / "sub") / "b.md"))
    inner.path.chmod(0)
    try:
        assert reg.lookup(inner.path / "c.png") == inner
    finally:
        inner.path.chmod(0o700)


@pytest.fixture
def git_dirs(tmp_path):
    """A root that is not a git repo, `wiki`, holding a git repo `wiki/sub`, which holds a bare repo
    `keep.git`."""
    reg = roots.Roots()
    outer = reg.for_document(md(tmp_path / "wiki" / "a.md"))
    inner = make_repo(tmp_path / "wiki" / "sub")
    git(inner, "init", "-q", "--bare", "keep.git")
    return reg, outer, inner


# Paths in `sub`'s git directories, there or not, and under a bare repo that is not there (`gone.git`),
# which is a folder of `sub`'s work tree: the outer root gets none of them.
GIT_DIR_PATHS = [".git/x.png", ".git/objects/x.png", ".git/nope/x.png", "keep.git/x.png",
                 "keep.git/refs/x.md", "keep.git/nope/x.png", "gone.git/x.png"]


@pytest.mark.parametrize("inside", GIT_DIR_PATHS)
def test_a_path_in_a_git_directory_of_a_nested_repo_is_not_the_outer_roots(git_dirs, inside):
    reg, outer, inner = git_dirs
    assert reg.lookup(inner / inside) is None
    reg.for_document(md(inner / "b.md"))
    assert reg.lookup(inner / inside) != outer


def test_a_document_in_a_git_directory_is_its_own_folders_root_by_rule_3(git_dirs):
    reg, outer, inner = git_dirs
    for inside in (".git/x.md", "keep.git/x.md"):
        made = reg.for_document(md(inner / inside))
        assert made.path == (inner / inside).parent and not made.git
        assert reg.lookup(inner / inside) == made


@pytest.mark.parametrize("make", [["init", "-q", "--bare", "keep.git"],
                                  ["init", "-q", "--separate-git-dir", "keep.git", "../elsewhere"]])
def test_a_git_directory_in_a_root_that_is_not_a_repo_is_not_that_roots(git_dirs, make):
    reg, outer, _ = git_dirs
    assert reg.lookup(outer.path / "keep.git" / "x.md") == outer             # a folder that is not there yet
    git(outer.path, *make)
    assert reg.lookup(outer.path / "keep.git" / "x.md") is None


def test_a_bare_repo_git_refuses_to_use_is_a_git_directory_too(git_dirs, monkeypatch):
    reg, outer, inner = git_dirs
    for k, v in {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.bareRepository",
                 "GIT_CONFIG_VALUE_0": "explicit"}.items():
        monkeypatch.setenv(k, v)
    assert reg.lookup(inner / "keep.git" / "x.png") is None
    assert reg.lookup(inner / "b.png") is None and reg.lookup(outer.path / "c.png") == outer


def test_a_submodules_git_directory_is_no_root_even_where_git_names_its_work_tree(git_dirs):
    reg, outer, inner = git_dirs
    gd, wt = inner / ".git" / "modules" / "lib", inner / "lib"       # as `git submodule add` lays them out
    gd.parent.mkdir()
    git(inner, "init", "-q", "--separate-git-dir", str(gd), str(wt))
    git(inner, "--git-dir", str(gd), "config", "core.worktree", str(wt))
    lib = reg.for_document(md(wt / "c.md"))
    assert lib.path == wt
    for inside in ("x.png", "nope/x.png", "refs/x.png"):
        assert reg.lookup(gd / inside) is None, inside


@pytest.mark.parametrize("name", ["nl\nrepo", "ends in a space "])
def test_a_repo_whose_path_has_a_newline_or_a_trailing_space_is_still_its_own_root(tmp_path, name):
    repo = make_repo(tmp_path / name)
    gd, wt = tmp_path / f"g{name}d", tmp_path / f"w{name}t"
    git(tmp_path, "init", "-q", "--separate-git-dir", str(gd), str(wt))
    reg = roots.Roots()
    for top in (repo, wt.resolve()):
        made = reg.for_document(md(top / "a.md"))
        assert (made.path, made.git) == (top, True)
        assert reg.lookup(top / "deep" / "x.png") == made


def test_a_nested_repo_whose_name_is_not_utf8_is_not_the_outer_roots(git_dirs):
    reg, outer, _ = git_dirs
    undecodable_names_or_skip(outer.path)
    odd = make_repo(outer.path / os.fsdecode(b"not-utf8-\xff"))
    assert reg.lookup(odd / "x.png") is None and reg.lookup(odd / ".git" / "x.png") is None


def test_a_folder_of_a_bare_repos_worktree_layout_outside_its_git_directory_is_judged_by_rule_2(tmp_path):
    project = tmp_path / "project"
    bare = make_repo(tmp_path / "src")
    commit(bare)
    git(tmp_path, "clone", "-q", "--bare", str(bare), str(project / ".bare"))
    (project / ".git").write_text("gitdir: ./.bare\n", encoding="utf-8")
    reg = roots.Roots()
    assert reg.address(md(project / "a.md")) == "project/a.md"
    assert reg.address(md(project / "docs" / "b.md")) == "project/docs/b.md"
    assert reg.lookup(project / "docs" / "sub" / "fig.png") == reg.get("project")


# ── where git names neither a work tree nor a git directory (8.2): the path tells one ──

# Paths in `sub`'s git directories, there or not: its `.git` folder and the bare repo `keep.git`.
IN_A_GIT_DIR = [p for p in GIT_DIR_PATHS if not p.startswith("gone.git")]


@pytest.mark.parametrize("how", GIT_FAILS)
@pytest.mark.parametrize("inside", IN_A_GIT_DIR)
def test_where_git_fails_a_path_in_a_nested_repos_git_directory_is_not_the_outer_roots(git_dirs, monkeypatch,
                                                                                    tmp_path, how, inside):
    reg, outer, inner = git_dirs
    git_fails(how, monkeypatch, tmp_path)
    assert reg.lookup(inner / inside) is None


@pytest.mark.parametrize("how", GIT_FAILS)
def test_where_git_fails_a_nested_repos_work_tree_is_the_outer_roots_as_before(git_dirs, monkeypatch, tmp_path,
                                                                            how):
    reg, outer, inner = git_dirs
    git_fails(how, monkeypatch, tmp_path)
    for path in (inner / "b.png", inner / "deep" / "c.md", outer.path / "img" / "x.png", outer.path / "a.md"):
        assert reg.lookup(path) == outer, path


@pytest.mark.parametrize("how", GIT_FAILS)
def test_where_git_fails_the_members_own_repo_its_git_directories_are_not_their_roots(tmp_path, monkeypatch, how):
    """A root that is a git repo git refuses or cannot ask (owned by another account, or no git) is
    registered as a root that is not a git repo, and only the path keeps its git directories from it."""
    repo = make_repo(tmp_path / "pages")
    git(repo, "init", "-q", "--bare", "keep.git")
    git_fails(how, monkeypatch, tmp_path)
    reg = roots.Roots()
    own = reg.for_document(md(repo / "a.md"))
    assert (own.path, own.git) == (repo, False)
    assert reg.lookup(repo / "img" / "x.png") == own
    for inside in (".git/x.png", ".git/refs/x.md", ".git/nope/x.png", "keep.git/x.png", "keep.git/nope/x.png"):
        assert reg.lookup(repo / inside) is None, inside


@pytest.mark.parametrize("how", GIT_FAILS)
def test_where_git_fails_a_document_in_a_git_directory_is_its_own_folders_root_as_where_it_runs(git_dirs,
                                                                                             monkeypatch,
                                                                                             tmp_path, how):
    reg, outer, inner = git_dirs
    git_fails(how, monkeypatch, tmp_path)
    for inside, address in ((".git/x.md", "git/x.md"), ("keep.git/x.md", "keep.git/x.md")):
        assert reg.address(md(inner / inside)) == address


@pytest.mark.skipif(os.geteuid() == 0, reason="root enters any folder")
def test_a_nested_git_directory_the_hub_cannot_enter_is_not_the_outer_roots(git_dirs):
    reg, outer, inner = git_dirs
    (inner / ".git").chmod(0)
    try:
        assert reg.lookup(inner / "b.png") == outer       # git sees no repo: its work tree is the outer root's
        assert reg.lookup(inner / ".git" / "x.png") is None
    finally:
        (inner / ".git").chmod(0o755)


def test_a_submodules_git_directory_whose_work_tree_is_gone_is_not_the_outer_roots(git_dirs):
    reg, outer, inner = git_dirs
    gd = inner / ".git" / "modules" / "lib"
    gd.parent.mkdir()
    git(inner, "init", "-q", "--separate-git-dir", str(gd), str(inner / "lib"))
    git(inner, "--git-dir", str(gd), "config", "core.worktree", "../../../lib")
    subprocess.run(["rm", "-rf", str(inner / "lib")], check=True)        # as `git rm lib` leaves it
    for inside in ("x.png", "refs/x.png", "nope/x.png"):
        assert reg.lookup(gd / inside) is None, inside


def test_a_git_file_planted_in_a_nested_repos_git_directory_does_not_open_it(git_dirs, tmp_path):
    reg, outer, inner = git_dirs
    git(tmp_path, "init", "-q", "--bare", str(tmp_path / "elsewhere.git"))
    (inner / ".git" / "evil").mkdir()
    (inner / ".git" / "evil" / ".git").write_text(f"gitdir: {tmp_path / 'elsewhere.git'}\n", encoding="utf-8")
    assert reg.lookup(inner / ".git" / "evil" / "x.png") is None


@pytest.mark.parametrize("how", GIT_FAILS)
def test_where_git_fails_a_git_directory_named_by_commondir_or_holding_a_refs_file_is_closed_too(
        git_dirs, monkeypatch, tmp_path, how):
    """Git takes both for git directories: it follows `commondir`, and asks only that `refs` can be
    searched, which a file with its x bit set can. Git makes neither but under a `.git`'s `worktrees`."""
    reg, outer, inner = git_dirs
    linked, filed = outer.path / "adm", outer.path / "rf"
    linked.mkdir()
    (linked / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (linked / "commondir").write_text(f"{inner / 'keep.git'}\n", encoding="utf-8")
    (filed / "objects").mkdir(parents=True)
    (filed / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (filed / "refs").write_text("", encoding="utf-8")
    (filed / "refs").chmod(0o755)
    git_fails(how, monkeypatch, tmp_path)
    for folder in (linked, filed):
        assert reg.lookup(folder / "x.png") is None, folder


@pytest.mark.parametrize("spoil", ["empty HEAD", "closed"])
def test_in_a_git_root_a_nested_git_directory_git_does_not_take_for_one_is_not_that_roots(tmp_path, spoil):
    """Git names the outer work tree for a path in a `.git` whose `HEAD` is empty, as a crash can leave
    it, or which this account cannot enter."""
    if spoil == "closed" and os.geteuid() == 0:
        pytest.skip("root enters any folder")
    reg = roots.Roots()
    own = reg.for_document(md(make_repo(tmp_path / "pages") / "a.md"))
    nested = make_repo(own.path / "sub")
    if spoil == "empty HEAD":
        (nested / ".git" / "HEAD").write_text("", encoding="utf-8")
    else:
        (nested / ".git").chmod(0)
    try:
        assert reg.lookup(nested / "x.png") == own        # a folder of `pages` to git
        for inside in (".git/x.png", ".git/objects/x.png"):
            assert reg.lookup(nested / inside) is None, inside
    finally:
        (nested / ".git").chmod(0o755)


@pytest.fixture
def git_dir_worktrees(git_dirs, tmp_path):
    """Two work trees whose folders lie inside a git directory: a worktree of the bare repo `wiki/wiki.git`
    at `wiki.git/w1`, and a repo at `sub/.git/inner`."""
    reg, outer, inner = git_dirs
    seed = make_repo(tmp_path / "seed")
    commit(seed)
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(outer.path / "wiki.git"))
    git(outer.path / "wiki.git", "worktree", "add", "-q", "-b", "side", "w1")
    return reg, outer, [(outer.path / "wiki.git" / "w1").resolve(), make_repo(inner / ".git" / "inner")]


def test_a_work_tree_inside_a_git_directory_is_still_its_own_root(git_dir_worktrees):
    reg, _, tops = git_dir_worktrees
    for top in tops:
        made = reg.for_document(md(top / "a.md"))
        assert (made.path, made.git) == (top, True)
        assert reg.lookup(top / "img" / "x.png") == made


@pytest.mark.parametrize("how", GIT_FAILS)
def test_where_git_fails_a_work_tree_inside_a_git_directory_is_closed_with_it(git_dir_worktrees, monkeypatch,
                                                                           tmp_path, how):
    reg, _, tops = git_dir_worktrees
    git_fails(how, monkeypatch, tmp_path)
    for top in tops:
        assert reg.lookup(top / "img" / "x.png") is None, top


# ── the walk stops at the root rule 2 gives: what lies above it is not the member's (8.2) ──

# (path in the member's root, root it gives where git runs, where git fails): "own" for the member's root,
# None for none. A plain folder, a git work tree, a plain folder holding a repo `sub` with a bare `keep.git`.
ROOT_KINDS = {
    "plain": [("x.png", "own", "own"), ("d/x.png", "own", "own"), ("d/e/c.md", "own", "own"),
              ("gone/x.png", "own", "own")],
    "git": [("x.png", "own", "own"), ("d/x.png", "own", "own"), ("d/e/c.md", "own", "own"),
            (".git/x.png", None, None), (".git/refs/c.md", None, None)],
    "nested": [("x.png", "own", "own"), ("sub/x.png", None, "own"), ("sub/d/c.md", None, "own"),
               ("sub/.git/x.png", None, None), ("sub/keep.git/x.png", None, None),
               ("sub/keep.git/refs/c.md", None, None)],
}


@pytest.mark.parametrize("how", ["runs", *GIT_FAILS])
@pytest.mark.parametrize("kind", ROOT_KINDS)
def test_a_member_root_that_is_a_plain_folder_a_git_work_tree_or_holds_a_nested_repo_answers_as_before(
        tmp_path, monkeypatch, kind, how):
    top = tmp_path / kind
    top.mkdir()
    if kind == "git":
        git(top, "init", "-q")
    if kind == "nested":
        make_repo(top / "sub")
        git(top / "sub", "init", "-q", "--bare", "keep.git")
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)
    reg = roots.Roots()
    own = reg.for_document(md(top / "a.md"))
    assert (own.path, own.git) == (top.resolve(), kind == "git" and how == "runs")
    for rel, runs, fails in ROOT_KINDS[kind]:
        want = runs if how == "runs" else fails
        assert reg.lookup(top / rel) == (own if want == "own" else None), rel


@pytest.mark.parametrize("how", GIT_FAILS)
def test_where_git_fails_a_root_that_is_a_worktree_in_a_bare_repo_keeps_what_is_under_it(
        tmp_path, monkeypatch, how):
    """`git clone --bare` then `git worktree add`: where git refuses the root is registered as one that is not a
    git repo, and the bare repo above it is no git directory of the member's."""
    seed = make_repo(tmp_path / "seed")
    commit(seed)
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(tmp_path / "proj.git"))
    git(tmp_path / "proj.git", "worktree", "add", "-q", "-b", "side", "main")
    main = (tmp_path / "proj.git" / "main").resolve()
    git(main, "init", "-q", "--bare", "keep.git")
    git_fails(how, monkeypatch, tmp_path)
    reg = roots.Roots()
    own = reg.for_document(md(main / "a.md"))
    assert (own.path, own.git) == (main, False)
    for path in (main / "x.png", main / "sub" / "x.png", main / "sub" / "deep" / "c.md"):
        assert reg.lookup(path) == own, path
    for inside in (".git/x.png", "keep.git/x.png", "keep.git/refs/x.md"):     # at or below the root: closed
        assert reg.lookup(main / inside) is None, inside


@pytest.mark.parametrize("how", GIT_FAILS)
def test_where_git_fails_a_git_root_inside_a_worktree_root_in_a_bare_repo_is_the_outer_roots_work_tree(
        tmp_path, monkeypatch, how):
    """A repo `r` registered while git ran, in a root that is a worktree of a bare repo and was registered where git
    refuses: where git fails, `r` is a nested repo's work tree like any other, the outer root's (rule 2)."""
    seed = make_repo(tmp_path / "seed")
    commit(seed)
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(tmp_path / "proj.git"))
    git(tmp_path / "proj.git", "worktree", "add", "-q", "-b", "side", "main")
    main = (tmp_path / "proj.git" / "main").resolve()
    reg = roots.Roots()
    inner = reg.for_document(md(make_repo(main / "r") / "a.md"))
    assert (inner.path, inner.git) == (main / "r", True)
    git_fails(how, monkeypatch, tmp_path)
    own = reg.for_document(md(main / "a.md"))
    assert (own.path, own.git) == (main, False)
    for path in (main / "r" / "a.md", main / "r" / "s" / "x.png"):
        assert reg.lookup(path) == own, path
    assert reg.lookup(main / "r" / ".git" / "x.png") is None


@pytest.fixture
def git_lookalikes(git_dirs):
    """In the outer root, which is no repo, two folders git takes for no repository: `notes/.git`, an empty
    folder, and `copy`, which holds `HEAD`, `objects` and `refs` with a `HEAD` that is no ref."""
    reg, outer, _ = git_dirs
    named, shaped = outer.path / "notes" / ".git", outer.path / "copy"
    named.mkdir(parents=True)
    for d in ("objects", "refs"):
        (shaped / d).mkdir(parents=True)
    (shaped / "HEAD").write_text("not a ref\n", encoding="utf-8")
    return reg, outer, named, shaped


def test_a_folder_named_git_or_shaped_like_a_git_directory_is_closed_though_git_sees_no_repo(git_lookalikes):
    reg, outer, named, shaped = git_lookalikes
    assert reg.lookup(outer.path / "notes" / "x.png") == outer
    for folder in (named, shaped, shaped / "refs"):
        assert reg.lookup(folder / "x.png") is None, folder
    assert reg.address(md(named / "n.md")) == "git/n.md"          # its own folder's, by rule 3


def test_a_root_inside_a_folder_named_git_or_shaped_like_a_git_directory_keeps_what_is_under_it(git_lookalikes):
    reg, _, named, shaped = git_lookalikes
    for holder in (named, shaped):
        pages = reg.for_document(md(holder / "pages" / "a.md"))
        assert (pages.path, pages.git) == (holder / "pages", False)
        assert reg.lookup(holder / "pages" / "b.md") == pages
        assert reg.lookup(holder / "pages" / "img" / "x.png") == pages
        (holder / "pages" / "lib" / ".git").mkdir(parents=True)          # below the root: closed
        assert reg.lookup(holder / "pages" / "lib" / ".git" / "x.png") is None


@pytest.mark.parametrize("how", ["runs", *GIT_FAILS])
def test_a_root_whose_own_folder_is_shaped_like_a_git_directory_keeps_only_that_folder(tmp_path, monkeypatch, how):
    """The root's own folder is looked at: a git directory at the root stays closed (rule 3 keeps its folder)."""
    folder = tmp_path / "copy"
    for d in ("objects", "refs"):
        (folder / d).mkdir(parents=True)
    (folder / "HEAD").write_text("not a ref\n", encoding="utf-8")
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)
    reg = roots.Roots()
    own = reg.for_document(md(folder / "a.md"))
    assert (own.path, own.git) == (folder, False)
    assert reg.lookup(folder / "x.png") == own
    for inside in ("img/x.png", "refs/x.md"):
        assert reg.lookup(folder / inside) is None, inside


@pytest.mark.parametrize("how", ["runs", *GIT_FAILS])
def test_a_root_inside_a_git_directory_keeps_what_is_under_it_where_git_fails_and_its_own_folder_where_it_runs(
        git_dirs, monkeypatch, tmp_path, how):
    """The key made it a root by rendering a document there (rule 3). Where git runs, git's own answer says the
    folder is in a git directory; the walk of the path is what stops at the root."""
    reg, outer, inner = git_dirs
    for holder in (inner / ".git" / "notes", inner / "keep.git" / "notes"):
        made = reg.for_document(md(holder / "a.md"))
        assert (made.path, made.git) == (holder, False)
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)
    for holder in (inner / ".git" / "notes", inner / "keep.git" / "notes"):
        made = reg.lookup(holder / "a.md")
        assert made is not None and made.path == holder
        assert reg.lookup(holder / "img" / "x.png") == (None if how == "runs" else made), holder


def test_a_path_through_a_git_that_is_no_folder_is_no_roots(git_dirs, tmp_path):
    """No file can be there: not there, or the `.git` file of a worktree."""
    reg, outer, _ = git_dirs
    repo = make_repo(tmp_path / "proj")
    commit(repo)
    git(repo, "worktree", "add", "-q", str(tmp_path / "proj-wt"), "-b", "side")
    wt = reg.for_document(md(tmp_path / "proj-wt" / "a.md"))
    own = reg.for_document(md(repo / "a.md"))
    assert reg.lookup(wt.path / "x.png") == wt
    for path in (wt.path / ".git" / "x.png", outer.path / ".git" / "x.png", own.path / "nope" / ".git" / "x.png"):
        assert reg.lookup(path) is None, path


# ── two processes, one registry ──────────────────────────────────────────────

_REGISTER = """
import os, sys, time
from pathlib import Path
from sheafmd.hub import roots
go = Path(sys.argv[1])
Path(f"{go}.ready.{os.getpid()}").touch()
for _ in range(30000):
    if go.exists():
        break
    time.sleep(0.001)
else:
    sys.exit("no start signal")
reg = roots.Roots()
for folder in sys.argv[2:]:
    reg.for_document(Path(folder) / "a.md")
print(" ".join(f"{r.name}={r.id}" for r in reg.all()))
"""


def _together(tmp_path, folders_per_process):
    """One Python process per entry, each registering its folders in a registry it opens after
    a common start signal; every process's answer, as `{name: id}`."""
    go = tmp_path / "go"
    procs = [subprocess.Popen([sys.executable, "-c", _REGISTER, str(go), *map(str, folders)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              env=os.environ.copy())
             for folders in folders_per_process]
    answers = []
    try:
        deadline = time.monotonic() + 30
        while len(list(tmp_path.glob("go.ready.*"))) < len(procs):
            assert time.monotonic() < deadline, "a process never reached the start"
            time.sleep(0.01)
        go.write_text("go")
        for p in procs:
            out, err = p.communicate(timeout=60)
            assert p.returncode == 0, err
            answers.append(dict(pair.split("=") for pair in out.split()))
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait()
    return answers


def test_processes_registering_roots_together_keep_every_root_and_each_id(tmp_path):
    folders = [[tmp_path / f"p{i}-{j}" for j in range(3)] for i in range(6)]
    for group in folders:
        for f in group:
            f.mkdir()
    answers = _together(tmp_path, folders)
    on_disk = {n: e["id"] for n, e in json.loads((paths.state_dir() / "roots.json").read_text()).items()}
    assert len(on_disk) == 18
    for answer in answers:                      # an id a process handed out is the id on disk
        for name, rid in answer.items():
            assert on_disk[name] == rid


def test_processes_that_start_on_a_file_without_ids_give_each_root_one_id(tmp_path):
    folders = [tmp_path / f"r{i}" for i in range(4)]
    for f in folders:
        f.mkdir()
    state = paths.state_dir()
    state.mkdir(parents=True)
    (state / "roots.json").write_text(json.dumps(
        {f.name: {"path": str(f), "git": False, "added": "2026-01-01T00:00:00+0000"} for f in folders}))
    answers = _together(tmp_path, [[] for _ in range(6)])
    on_disk = {n: e["id"] for n, e in json.loads((state / "roots.json").read_text()).items()}
    assert set(on_disk) == {f.name for f in folders}
    for answer in answers:
        assert answer == on_disk


def test_a_registry_opened_before_another_process_added_a_root_does_not_drop_it(tmp_path):
    reg = roots.Roots()
    other = tmp_path / "other"
    other.mkdir()
    _together(tmp_path, [[other]])
    mine = tmp_path / "mine"
    mine.mkdir()
    reg.for_document(mine / "a.md")
    on_disk = json.loads((paths.state_dir() / "roots.json").read_text())
    assert set(on_disk) == {"other", "mine"}
    assert {r.name for r in reg.all()} == {"other", "mine"}


def test_a_hub_forgetting_a_root_another_process_already_forgot_still_gets_the_root_back(tmp_path):
    """The offline forget edits the file, then tells the hub: the hub's cleanup runs on what it returns."""
    folder = tmp_path / "held"
    folder.mkdir()
    hub = roots.Roots()
    held = hub.for_document(folder / "a.md")
    assert roots.forget_offline("held") is not None
    assert hub.forget("held") == held


def test_a_registry_that_missed_a_parent_root_registered_meanwhile_gives_the_child_to_the_parent(tmp_path):
    hub = roots.Roots()
    parent = tmp_path / "parent"
    (parent / "child").mkdir(parents=True)
    _together(tmp_path, [[parent]])
    made = hub.for_document(parent / "child" / "a.md")
    assert made.path == parent
    assert [r.path for r in hub.all()] == [parent]


def test_a_roots_file_that_went_missing_or_unreadable_does_not_empty_a_running_registry(tmp_path):
    hub = roots.Roots()
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    hub.for_document(first / "a.md")
    (paths.state_dir() / "roots.json").write_text("{not json")
    hub.for_document(second / "a.md")
    assert {r.name for r in hub.all()} == {"first", "second"}
    assert set(json.loads((paths.state_dir() / "roots.json").read_text())) == {"first", "second"}

