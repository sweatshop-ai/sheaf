"""Rule F (SPEC 9.11): a door create makes an owner-only sheaf at its owner's private root, and only for a caller bound to
that root's member; a create or a move into a private root by anyone else is refused with the ordinary "cannot be made"
line and writes nothing. Each refusal has the member's own create as its positive control, on the same route."""
import shutil

import pytest
from helpers import browser_on, call
from two_roots import TwoRoots, git, two_roots

from sheafmd.hub import place
from sheafmd.hub.state import Tokens
from sheafmd.source import md_hash

NAME = "acme/blog/post.md"
OPEN = "# post\n"
OWNED_BY_A = "---\nowner: a\nsources: [library:doc-1]\n---\n# post\n"      # a private source makes it its owner's alone
NO_OWNER = "---\nsources: [library:doc-1]\n---\n# post\n"


@pytest.fixture
def two(tmp_path) -> TwoRoots:
    return two_roots(tmp_path)


class World:
    def __init__(self, two: TwoRoots, assignees=None):
        self.two = two
        self.tokens = {n: Tokens().add(n, write=True) for n in ("tok-a", "tok-b", "loose")}
        self.hub = two.hub(two.config(a={"github": "login-a", "tokens": ["tok-a"]},
                                      b={"github": "login-b", "tokens": ["tok-b"]}))
        self.root = self.hub.the_list.root()
        if assignees is not None:
            self.hub.assignees = lambda address, fm: assignees
        (two.list_repo / "acme/blog").mkdir(parents=True)
        (two.list_repo / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["a", "b"]\nstatus = "live"\n',
                                                     encoding="utf-8")
        self.door = browser_on(self.hub)
        self.address = f"{self.root.name}/{NAME}"

    def call(self, tool, who, **args):
        return call(self.door, tool, token=self.tokens[who], **args)

    def create(self, who, text):
        return self.call("create", who, doc=self.address, text=text)

    def commits(self, repo):
        return int(git(repo, "rev-list", "--count", "HEAD"))

    def nothing_written(self):
        two = self.two
        assert not any(p.name == "post.md" for p in two.list_repo.rglob("*.md"))
        assert not (two.private_repo / NAME).exists()
        assert self.commits(two.list_repo) == 1 and self.commits(two.private_repo) == 1


def refused(is_error, got):
    assert is_error and "cannot be made" in got and place.PRIVATE_ROOT in got, got


def test_create_lands_in_private_root(two):
    w = World(two)
    is_error, got = w.create("tok-a", OWNED_BY_A)
    assert not is_error, got
    assert (two.private_repo / NAME).is_file() and not list(two.list_repo.rglob("post.md"))
    assert w.commits(two.private_repo) == 2         # the create's commit is in the private repo
    assert w.commits(two.list_repo) == 1            # and the list repo has none
    assert "post.md" not in git(two.list_repo, "status", "--porcelain", "--untracked-files=all")


def test_create_into_private_root_refused_for_other_member(two):
    w = World(two)
    refused(*w.create("tok-b", OWNED_BY_A))
    w.nothing_written()
    assert not w.create("tok-a", OWNED_BY_A)[0]     # positive control: the member's own create, same route


def test_create_into_private_root_refused_for_unbound_token(two):
    w = World(two)
    refused(*w.create("loose", OWNED_BY_A))
    w.nothing_written()
    assert not w.create("tok-a", OWNED_BY_A)[0]


def test_owned_assignees_cannot_create_in_private_root(two):
    w = World(two, assignees=["login-a"])           # the issue is assigned to member A: `_owned` would give A the sheaf
    refused(*w.create("tok-b", NO_OWNER))           # B names no owner; the assignee A would become it
    w.nothing_written()
    is_error, got = w.create("tok-a", NO_OWNER)     # positive control: A, the assignee, is bound to that root
    assert not is_error, got
    assert (two.private_repo / NAME).is_file()


def test_update_owner_flip_refused(two):
    w = World(two)
    assert not w.create("tok-b", OPEN)[0]           # an open sheaf of the list repo
    path = two.list_repo / NAME
    before = path.read_text(encoding="utf-8")
    count = w.commits(two.list_repo)
    is_error, got = w.call("update", "tok-a", doc=w.address, text=OWNED_BY_A, expected_hash=md_hash(before))
    assert is_error and "was not written" in got, got
    assert path.read_text(encoding="utf-8") == before and not (two.private_repo / NAME).exists()
    assert w.commits(two.list_repo) == count and w.commits(two.private_repo) == 1
    is_error, got = w.call("update", "tok-a", doc=w.address, text=OPEN + "\nmore\n", expected_hash=md_hash(before))
    assert not is_error, got                        # positive control: an update that stays in its root
    assert "more" in path.read_text(encoding="utf-8")


def test_create_refused_for_the_key_like_for_other_callers(two):
    w = World(two)
    other = w.create("tok-b", OWNED_BY_A)
    key = call(w.door, "create", doc=w.address, text=OWNED_BY_A)      # no token: the key
    refused(*key)
    assert key == other
    w.nothing_written()


def test_private_folder_swapped_for_a_link_after_the_checks_is_refused(two, monkeypatch):
    w = World(two)
    real = place.make_folders

    def swapped(top, rel, judge=None):
        # between the checks by path and the open: the member's folder becomes a link to the list repo
        moved = two.private_repo.with_name("moved")
        two.private_repo.rename(moved)
        two.private_repo.symlink_to(two.list_repo)
        return real(top, rel, judge)
    monkeypatch.setattr(place, "make_folders", swapped)
    is_error, got = w.create("tok-a", OWNED_BY_A)
    assert is_error, got
    assert not list(two.list_repo.rglob("post.md"))
    monkeypatch.setattr(place, "make_folders", real)
    two.private_repo.unlink()
    two.private_repo.with_name("moved").rename(two.private_repo)
    assert not w.create("tok-a", OWNED_BY_A)[0]            # positive control: the folder back, the same create is made


def test_private_folder_swap_after_a_read_recorded_it_is_refused(two, monkeypatch, tmp_path):
    w = World(two)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    other = w.address.replace("post", "other")
    assert not w.call("create", "tok-b", doc=other, text=OPEN)[0]
    moved = two.private_repo.with_name("moved")
    two.private_repo.rename(moved)
    two.private_repo.symlink_to(elsewhere)
    assert not w.call("read", "tok-b", doc=other)[0]       # a read records what is at the private path
    two.private_repo.unlink()
    moved.rename(two.private_repo)
    real = place.make_folders

    def swapped(top, rel, judge=None):
        two.private_repo.rename(moved)
        two.private_repo.symlink_to(elsewhere)
        return real(top, rel, judge)
    monkeypatch.setattr(place, "make_folders", swapped)
    is_error, got = w.create("tok-a", OWNED_BY_A)
    assert is_error, got
    assert not list(elsewhere.rglob("post.md"))
    monkeypatch.setattr(place, "make_folders", real)
    elsewhere.joinpath("acme").exists() and shutil.rmtree(elsewhere / "acme")
    two.private_repo.unlink()
    moved.rename(two.private_repo)
    assert not w.create("tok-a", OWNED_BY_A)[0]            # positive control: the folder back, the same create is made


def test_create_by_the_private_folders_path_says_to_use_the_list_name(two):
    w = World(two)
    path = str(two.private_repo / NAME)
    for who in ("tok-a", None):                    # the member, and the key
        is_error, got = call(w.door, "create", doc=path, text=OWNED_BY_A, **({"token": w.tokens[who]} if who else {}))
        assert is_error and "cannot be made" in got and place.PRIVATE_PATH in got, got
        assert "moved" not in got                   # nothing is moved: a create by this path is simply not how it is made
    w.nothing_written()
    assert not w.create("tok-a", OWNED_BY_A)[0]     # positive control: the list name, the same text, the same member
