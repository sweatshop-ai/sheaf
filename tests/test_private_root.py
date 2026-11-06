"""A member's `private_root` (SPEC 9.9): a git root of theirs alone, beside the list's. Its configuration is checked at
the start, a hub without one reads none of the new code, and one with one registers it as a root marked private."""
import os
import shutil
import subprocess
import textwrap

import pytest
from helpers import hub_rows
from two_roots import A, TwoRoots, git, two_roots

from sheafmd import paths
from sheafmd.hub import proxy
from sheafmd.hub.core import Hub
from sheafmd.hub.proxy import ProxyError


@pytest.fixture
def roots(tmp_path) -> TwoRoots:
    return two_roots(tmp_path)


def nested_repo(parent):
    """A git work tree of its own inside `parent`."""
    inner = parent / "inner"
    subprocess.run(["git", "init", "-q", str(inner)], check=True)
    return inner


def test_a_private_root_that_is_checked_gives_the_member_its_folder(roots):
    assert roots.config().members[A].private_root == str(roots.private_repo.resolve())


def test_member_without_private_root_unchanged(roots):
    table = roots.table()
    del table["members"][A]["private_root"]
    got = proxy.parse(table, "the test", roots.list_table())
    assert got.members[A] == proxy.Member(A, "Member A", (str(roots.list_repo), str(roots.private_repo)),
                                          short="a")
    assert got.members[A].private_root == ""


def cases(roots):
    """(id, replacement keys of A's block, of B's block, the [list] table or None, the words of the refusal)."""
    own, lists, base = roots.private_repo, roots.list_table(), roots.base
    inside_list, inside_own = nested_repo(roots.list_repo), nested_repo(own)
    worktree = base / "worktree"
    git(roots.list_repo, "worktree", "add", "-q", str(worktree))
    other_wt = base / "other-worktree"
    git(own, "worktree", "add", "-q", str(other_wt))
    clone = base / "clone"
    subprocess.run(["git", "clone", "-q", str(base / "list.git"), str(clone)], check=True, capture_output=True)
    gitfile = base / "gitfile"
    gitfile.mkdir()
    (gitfile / ".git").write_text(f"gitdir: {roots.list_repo / '.git'}\n", encoding="utf-8")
    (base / "plain").mkdir()
    mine = lambda path: {"private_root": str(path), "roots": [str(path)]}      # noqa: E731
    return [
        ("relative", {"private_root": "private"}, {}, lists, "must be an absolute path"),
        ("two", {"private_root": [str(own), str(base / "x")]}, {}, lists, "one absolute path, not a list"),
        ("not in roots", {"roots": [str(roots.list_repo)]}, {}, lists, "must also be one of the member's 'roots'"),
        ("in another member's roots", {}, {"roots": [str(roots.list_repo), str(own)]}, lists,
         "also, or is inside or around, a root of Member B"),
        ("another member's root around it", {}, {"roots": [str(roots.list_repo), str(base)]}, lists,
         "also, or is inside or around, a root of Member B"),
        ("another member's root inside it", {}, {"roots": [str(roots.list_repo), str(inside_own)]}, lists,
         "also, or is inside or around, a root of Member B"),
        ("the list's root", mine(roots.list_repo), {}, lists, "is the same as the list's root"),
        ("inside the list's root", mine(inside_list), {}, lists, "is inside the list's root"),
        ("around the list's root", mine(base), {}, lists, "is around the list's root"),
        ("another private root inside it", {}, {**mine(inside_own), "roots": [str(roots.list_repo), str(inside_own)]},
         lists, "also, or is inside or around, a root of Member B"),
        ("another private root around it", mine(inside_own),
         {"private_root": str(own), "roots": [str(roots.list_repo), str(own)]}, lists,
         "also, or is inside or around, a root of Member B"),
        ("a gitfile pointing at the list's git dir", mine(gitfile), {}, lists, "same git repo as the list's root"),
        ("a linked worktree of the list", mine(worktree), {}, lists, "same git repo as the list's root"),
        ("a clone with the list's origin", mine(clone), {}, lists, "same git repo as the list's root"),
        ("a linked worktree of another private root", {},
         {**mine(other_wt), "roots": [str(roots.list_repo), str(other_wt)]}, lists,
         "same git repo as the private root of Member B"),
        ("a folder inside a repo", mine(own / "sub"), {}, lists, "top folder of a git work tree"),
        ("a folder that is no repo", mine(base / "plain"), {}, lists, "top folder of a git work tree"),
        ("a folder that is not there", mine(base / "absent"), {}, lists, "top folder of a git work tree"),
        ("no list", {}, {}, None, "needs a \\[list\\] table"),
    ]


def test_private_root_config_refused(roots):
    """Each way a `private_root` can be wrong is a ProxyError that says which."""
    for how, a, b, lists, words in cases(roots):
        with pytest.raises(ProxyError, match=words):
            proxy.parse(roots.table(a, b), "the test", lists)


def test_private_root_config_is_read_from_the_file_with_its_list_table(roots, tmp_path):
    """Through config.toml, `load()` hands the [list] table over: with it the key is accepted, without it refused."""
    me = roots.table()["proxy_user"]
    body = textwrap.dedent(f'''
        [proxy]
        origin = "https://front.example.com"
        socket = "/run/sheaf-proxy/hub.sock"
        proxy_user = "{me}"
        [proxy.members."{A}"]
        name = "Member A"
        roots = ["{roots.list_repo}", "{roots.private_repo}"]
        private_root = "{roots.private_repo}"
        ''')
    listed = f'[list]\nroot = "{roots.list_repo}"\nrepo = "o/r"\nproject = 1\ntoken' f'_file = "{tmp_path}/t"\n'
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(body + listed, encoding="utf-8")
    assert proxy.load().members[A].private_root == str(roots.private_repo.resolve())
    paths.config_file().write_text(body, encoding="utf-8")
    with pytest.raises(ProxyError, match="needs a \\[list\\] table"):
        proxy.load()


def test_two_members_cannot_name_one_private_root(roots):
    table = roots.table(b={"private_root": str(roots.private_repo), "roots": [str(roots.private_repo)]})
    with pytest.raises(ProxyError, match="also, or is inside or around, a root of Member B"):
        proxy.parse(table, "the test", roots.list_table())


def test_private_roots_registered_at_start(roots):
    hub = roots.hub()
    mine = hub.roots.lookup(roots.private_repo / "x.md")
    assert mine is not None and mine.path == roots.private_repo.resolve() and mine.git
    assert hub.private_roots == {mine.id: A}
    assert mine in hub.roots.all()                              # the commits need it
    assert hub.the_list.root().id not in hub.private_roots


def test_no_private_roots_without_the_key(roots):
    table = roots.table()
    del table["members"][A]["private_root"]
    hub = roots.hub(proxy.parse(table, "the test", roots.list_table()))
    assert hub.private_roots == {}
    assert Hub(port=hub.port, key=paths.ensure_key(), started_by="test").private_roots == {}     # loopback mode


def test_a_private_root_that_stops_being_a_repo_is_not_marked_and_a_row_says_so(roots):
    cfg = roots.config()
    (roots.private_repo / ".git").rename(roots.private_repo.with_name("gone-git"))
    assert roots.hub(cfg).private_roots == {}
    assert [r["member"] for r in hub_rows("private-root-refused")] == [A]


def independent_repo(base, name, remotes: dict) -> str:
    """A repo of its own (its own first commit) with the given remotes, name -> `(url, pushurl)` or `url`."""
    repo = base / name
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "commit", "-q", "--allow-empty", "-m", f"first of {name}")
    for remote, urls in remotes.items():
        url, push = urls if isinstance(urls, tuple) else (urls, None)
        git(repo, "remote", "add", remote, url)
        if push:
            git(repo, "remote", "set-url", "--push", remote, push)
    return str(repo)


def refused_as_the_lists(roots, private: str):
    with pytest.raises(ProxyError, match="same git repo as the list's root"):
        proxy.parse(roots.table({"private_root": private, "roots": [private]}), "the test", roots.list_table())


def test_private_root_config_refused_same_repo_spelled_otherwise(roots):
    """Repos with a first commit of their own are the list's by their remote alone, however it is spelled; a copy of
    the list repo is its by the root commit alone. (A shallow clone holds no root commit: the known exception.)"""
    base, bare = roots.base, str(roots.base / "list.git")
    for how, remotes in {"file url": {"origin": "file://" + bare}, "trailing slash": {"origin": bare + "/"},
                         "renamed remote": {"upstream": bare},
                         "pushurl only": {"origin": ("https://elsewhere.example/x/y", bare)}}.items():
        refused_as_the_lists(roots, independent_repo(base, how.replace(" ", "-"), remotes))
    git(roots.list_repo, "remote", "set-url", "origin", "git@host.example:Org/repo.git")
    refused_as_the_lists(roots, independent_repo(base, "https-spelling", {"origin": "https://host.example/org/repo/"}))
    refused_as_the_lists(roots, independent_repo(base, "ssh-url", {"origin": "ssh://git@host.example:22/org/repo.git"}))
    for place in (roots.list_repo, roots.list_repo / ".git", str(roots.list_repo) + "/"):      # a remote that is the list itself
        refused_as_the_lists(roots, independent_repo(base, f"points-at-{len(list(base.iterdir()))}", {"origin": str(place)}))
    elsewhere = independent_repo(base, "history-on-a-branch", {})
    git(elsewhere, "fetch", "-q", str(roots.list_repo), "main:borrowed")
    refused_as_the_lists(roots, elsewhere)                                    # the list's history is on another branch
    copy = base / "copy"
    subprocess.run(["cp", "-a", str(roots.list_repo), str(copy)], check=True)
    git(copy, "remote", "remove", "origin")
    refused_as_the_lists(roots, str(copy))
    apart = independent_repo(base, "apart", {"origin": "https://host.example/org/other"})
    got = proxy.parse(roots.table({"private_root": apart, "roots": [apart]}), "the test", roots.list_table())
    assert got.members[A].private_root == apart                     # a repo of its own is accepted


def test_private_root_config_refused_when_git_gives_no_answer(roots, tmp_path, monkeypatch):
    """A git that does not answer for the list's folder is no "not the same": the config is refused."""
    real = shutil.which("git")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "git").write_text(f'#!/bin/sh\n[ "$2" = "{roots.list_repo.resolve()}" ] && exec sleep 5\nexec {real} "$@"\n')
    (bin_ / "git").chmod(0o755)
    clone = roots.base / "clone"
    subprocess.run(["git", "clone", "-q", str(roots.base / "list.git"), str(clone)], check=True, capture_output=True)
    monkeypatch.setenv("PATH", f"{bin_}:{os.environ['PATH']}")
    monkeypatch.setattr(proxy, "GIT_TIMEOUT", 0.5)
    with pytest.raises(ProxyError, match="cannot tell whether .* shares a repo"):
        proxy.parse(roots.table({"private_root": str(clone), "roots": [str(clone)]}), "the test", roots.list_table())


def test_private_root_config_refused_against_other_members_git_roots(roots):
    """An ordinary root of another member that is a clone, or a linked worktree, of the private repo is refused."""
    clone, worktree = roots.base / "clone", roots.base / "worktree"
    subprocess.run(["git", "clone", "-q", str(roots.base / "private.git"), str(clone)], check=True, capture_output=True)
    git(roots.private_repo, "worktree", "add", "-q", str(worktree))
    for other in (clone, worktree):
        with pytest.raises(ProxyError, match="same git repo as the root .* of Member B"):
            proxy.parse(roots.table(b={"roots": [str(roots.list_repo), str(other)]}), "the test", roots.list_table())


def test_a_nul_in_private_root_is_a_config_error(roots):
    with pytest.raises(ProxyError, match="NUL"):
        proxy.parse(roots.table({"private_root": "/some\0where"}), "the test", roots.list_table())


def test_relations_compare_real_paths_with_case_folded(tmp_path):
    assert proxy._relation(str(tmp_path / "Priv" / "sub"), str(tmp_path / "priv")) == "inside"
    assert proxy._relation(str(tmp_path / "PRIV"), str(tmp_path / "priv")) == "the same as"


def test_git_is_asked_without_the_callers_git_variables(roots, monkeypatch):
    other = roots.base / "elsewhere"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    assert proxy.git_top(str(roots.private_repo)) == str(roots.private_repo.resolve())


def registered_paths(hub) -> set:
    return {r.path for r in hub.roots.all()}


def test_private_root_refused_writes_no_registry_entry(roots):
    cfg = roots.config()
    (roots.private_repo / ".git").rename(roots.private_repo.with_name("gone-git"))
    hub = roots.hub(cfg)
    assert roots.private_repo.resolve() not in registered_paths(hub)
    registry = paths.state_dir() / "roots.json"
    assert not registry.exists() or str(roots.private_repo.resolve()) not in registry.read_text(encoding="utf-8")


def test_private_root_that_lost_its_git_dir_is_refused_again(roots):
    cfg = roots.config()
    assert roots.hub(cfg).private_roots                         # registered, with git true, at this start
    (roots.private_repo / ".git").rename(roots.private_repo.with_name("gone-git"))
    assert roots.hub(cfg).private_roots == {}
    assert [r["member"] for r in hub_rows("private-root-refused")] == [A]


def test_private_mark_survives_forget_and_register(roots):
    hub = roots.hub()
    first = hub.roots.lookup(roots.private_repo / "x.md")
    assert hub.forget_root(first.name) is not None
    assert hub.private_roots == {}                              # nothing registered, nothing marked
    again = hub.roots.for_document(roots.private_repo / "x.md")
    assert again.id != first.id and hub.private_roots == {again.id: A}


def test_proxy_set_after_construction_registers_no_private_root(roots):
    table = roots.table()
    del table["members"][A]["private_root"]
    hub = roots.hub(proxy.parse(table, "the test", roots.list_table()))
    hub.proxy = roots.config()
    assert hub.private_roots == {}


def test_a_table_the_hub_refuses_still_names_its_members_to_token_add(roots):
    from sheafmd import cli
    me = roots.table()["proxy_user"]
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(textwrap.dedent(f'''
        [proxy]
        origin = "https://front.example.com"
        socket = "/run/sheaf-proxy/hub.sock"
        proxy_user = "{me}"
        [proxy.members."{A}"]
        name = "Member A"
        roots = ["{roots.base / "plain"}"]
        private_root = "{roots.base / "plain"}"
        [list]
        root = "{roots.list_repo}"
        repo = "o/r"
        project = 1
        '''), encoding="utf-8")
    with pytest.raises(ProxyError):
        proxy.load()
    assert cli._member_named("member a") == "Member A"


def test_a_remote_naming_the_private_repo_itself_is_refused_for_another_member(roots):
    """A member's ordinary root whose origin is the private repo's own folder pulls and pushes into it."""
    mine = roots.base / "bobs"
    subprocess.run(["git", "init", "-q", str(mine)], check=True)
    git(mine, "commit", "-q", "--allow-empty", "-m", "bob")
    git(mine, "remote", "add", "origin", str(roots.private_repo / ".git"))
    with pytest.raises(ProxyError, match="same git repo as the root .* of Member B"):
        proxy.parse(roots.table(b={"roots": [str(roots.list_repo), str(mine)]}), "the test", roots.list_table())


def test_git_config_variables_of_the_hub_reach_the_check(roots, monkeypatch):
    """The check runs git as the hub's own git does, so a config variable of the unit is judged too."""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "url.file:///nowhere/.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(roots.list_repo))
    got = proxy._git(str(roots.private_repo), "config", "--get", "url.file:///nowhere/.insteadOf")
    assert got is not None and got[1] == str(roots.list_repo)


def test_private_root_config_refused_when_its_remote_is_the_lists_issue_repo(roots):
    """`[list] repo` names where the list lives on the host; a private root that pushes there shares the list's repo,
    whether or not the list's own folder is a repo."""
    plain = roots.base / "plain-list"
    plain.mkdir()
    for lists in ({**roots.list_table(), "repo": "acme/record"}, {"root": str(plain), "repo": "acme/record"}):
        for spelling in ("git@github.com:acme/record.git", "https://github.com/Acme/record/"):
            own = independent_repo(roots.base, f"issues-{len(spelling)}-{len(lists['root'])}", {"origin": spelling})
            with pytest.raises(ProxyError, match="list's repo acme/record|same git repo as the list's root"):
                proxy.parse(roots.table({"private_root": own, "roots": [own]}), "the test", lists)


def test_a_relative_remote_is_read_from_the_top_of_the_work_tree(roots):
    """Another member's root in a subfolder of a repo whose `origin = ../private` pushes into the private repo."""
    team = roots.base / "team"
    subprocess.run(["git", "init", "-q", str(team)], check=True)
    git(team, "commit", "-q", "--allow-empty", "-m", "team")
    (team / "docs").mkdir()
    git(team, "remote", "add", "origin", "../" + roots.private_repo.name)
    with pytest.raises(ProxyError, match="same git repo as the root .* of Member B"):
        proxy.parse(roots.table(b={"roots": [str(roots.list_repo), str(team / "docs")]}), "the test", roots.list_table())
