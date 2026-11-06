"""A member's `private_root` (SPEC 9.9): a git root of theirs alone, beside the list's. Its configuration is checked at
the start, a hub without one reads none of the new code, and one with one registers it as a root marked private."""
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
