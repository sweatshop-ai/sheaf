"""A member's `private_root` (a git root of theirs alone, beside the list's): its configuration is checked at the
start, a hub without one reads none of the new code, and one with one registers it as a root marked private."""
import pytest
from two_roots import A, TwoRoots, two_roots

from sheafmd import paths
from sheafmd.hub import proxy
from sheafmd.hub.core import Hub
from sheafmd.hub.proxy import ProxyError


@pytest.fixture
def roots(tmp_path) -> TwoRoots:
    return two_roots(tmp_path)


def test_a_private_root_that_is_checked_gives_the_member_its_folder(roots):
    assert roots.config().members[A].private_root == str(roots.private_repo)


def test_member_without_private_root_unchanged(roots):
    table = roots.table()
    del table["members"][A]["private_root"]
    got = proxy.parse(table, "the test", roots.list_table())
    assert got.members[A] == proxy.Member(A, "Member A", (str(roots.list_repo), str(roots.private_repo)),
                                          short="a")
    assert got.members[A].private_root == ""


@pytest.mark.parametrize("how, words", [
    ("relative", "must be an absolute path"),
    ("not in roots", "must also be one of the member's 'roots'"),
    ("in another member's roots", "is also one of the roots of Member B"),
    ("the list's root", "is the same as the list's root"),
    ("inside the list's root", "is inside the list's root"),
    ("around the list's root", "is around the list's root"),
    ("inside another private root", "is (inside|around) the private root of Member"),
    ("around another private root", "is (inside|around) the private root of Member"),
    ("the list's git dir", "is in the same git repo as the list's root"),
    ("two", "at most one 'private_root'"),
    ("no list", "needs a \\[list\\] table"),
])
def test_private_root_config_refused(roots, how, words):
    """Each way a `private_root` can be wrong is a ProxyError that says which."""
    own, lists = roots.private_repo, roots.list_table()
    a, b = {}, {}
    if how == "relative":
        a = {"private_root": "private"}
    elif how == "not in roots":
        a = {"roots": [str(roots.list_repo)]}
    elif how == "in another member's roots":
        b = {"roots": [str(roots.list_repo), str(own)]}
    elif how == "the list's root":
        a = {"private_root": str(roots.list_repo)}
    elif how == "inside the list's root":
        inner = roots.list_repo / "inner"
        a = {"private_root": str(inner), "roots": [str(inner)]}
    elif how == "around the list's root":
        a = {"private_root": str(roots.base), "roots": [str(roots.base)]}
    elif how in ("inside another private root", "around another private root"):
        inner = own / "inner"
        b = {"private_root": str(inner), "roots": [str(roots.list_repo), str(inner)]}
        if how == "around another private root":
            a, b = ({"private_root": str(inner), "roots": [str(inner)]},
                    {"private_root": str(own), "roots": [str(roots.list_repo), str(own)]})
    elif how == "the list's git dir":
        (own.parent / "second").mkdir()
        (own.parent / "second" / ".git").write_text(f"gitdir: {roots.list_repo / '.git'}\n", encoding="utf-8")
        a = {"private_root": str(own.parent / "second"), "roots": [str(own.parent / "second")]}
    elif how == "two":
        a = {"private_root": [str(own), str(roots.base / "other")]}
    elif how == "no list":
        lists = None
    table = roots.table(a, b)
    with pytest.raises(ProxyError, match=words):
        proxy.parse(table, "the test", lists)


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


def test_a_private_root_that_is_no_repo_of_its_own_is_not_marked(roots, tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    cfg = roots.config(a={"private_root": str(folder), "roots": [str(roots.list_repo), str(folder)]})
    assert roots.hub(cfg).private_roots == {}
