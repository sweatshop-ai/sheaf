"""Rule B (SPEC 9.11): the file of a sheaf is never looked up in the list's root alone once a private root could hold
its name. A name with a holder in a private root and any other holder, a private root that cannot be looked at, a
bound document whose root is gone: each raises and writes nowhere. A sheaf of a private root is not shared or
unshared by a write."""
import os

import pytest
from helpers import browser_on, call, hub_rows
from two_roots import TwoRoots, git, two_roots

from sheafmd.hub import place, proxy, roots as roots_mod
from sheafmd.hub.state import Tokens
from sheafmd.source import md_hash

NAME = "acme/blog/post.md"
OTHER = "acme/blog/other.md"
PRIVATE_TEXT = "---\nowner: a\nsources: [library:doc-1]\n---\n# post\n\nSecret words.\n"
OPEN = "# post\n\nShared words.\n"
SHARED = PRIVATE_TEXT.replace("owner: a\n", "visibility: project\n")


@pytest.fixture
def two(tmp_path) -> TwoRoots:
    return two_roots(tmp_path)


def hub_of(two: TwoRoots, **over):
    hub = two.hub(two.config(**over))
    hub.the_list.root()
    (two.list_repo / "acme/blog").mkdir(parents=True)
    (two.private_repo / "acme/blog").mkdir(parents=True)
    return hub


def address(hub, name=NAME):
    return f"{hub.the_list.root().name}/{name}"


def untouched(two):
    return (git(two.list_repo, "status", "--porcelain", "--untracked-files=all"), git(two.list_repo, "ls-files"),
            git(two.list_repo, "log", "origin/main..", "--oneline"))


def comment(hub, a, text):
    """A comment on the open page, as the handler writes it, then the commit it makes."""
    with place.held(hub, a):
        e = hub.entry(a)
        e.live.comment("add", {"block": 0, "start": 0, "end": 3, "quote": "pos", "body": "hi"}, None)
        hub.committed(a, by="Member A")


def test_same_name_pull_open_page_writes_nothing_to_list(two):
    hub = hub_of(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    a = address(hub)
    hub.entry(a)
    (two.list_repo / NAME).write_text(OPEN, encoding="utf-8")                  # arrives by a pull
    git(two.list_repo, "add", "-A")
    git(two.list_repo, "commit", "-q", "-m", "arrives")
    git(two.list_repo, "push", "-q", "origin", "HEAD:main")
    seen = untouched(two)
    with pytest.raises(roots_mod.NotFound):
        comment(hub, a, PRIVATE_TEXT)
    with pytest.raises(roots_mod.NotFound):
        hub.file(a)                                                            # an unbound read does not fall back either
    with place.held(hub, a):
        hub.committed(a, by="Member A")                                        # the commit goes nowhere
    assert untouched(two) == seen
    assert (two.list_repo / NAME).read_text(encoding="utf-8") == OPEN
    assert "hi" not in (two.private_repo / NAME).read_text(encoding="utf-8")


def test_a_forgotten_private_root_leaves_a_bound_entry_no_list_file(two):
    hub = hub_of(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    a = address(hub)
    e = hub.entry(a)
    private = e.file_root
    assert private in hub.private_roots
    (two.private_repo / NAME).unlink()
    (two.list_repo / NAME).write_text(OPEN, encoding="utf-8")
    hub.forget_root(next(r.name for r in hub.roots.all() if r.id == private))
    assert not hub.private_roots                                               # no private root is registered now
    seen = untouched(two)
    with pytest.raises(roots_mod.NotFound):
        hub.file(a, bound=private)
    with place.held(hub, a):
        hub.committed(a, by="Member A")                                        # judged by the root it was opened for
    assert untouched(two) == seen


def test_a_bound_entry_whose_file_is_held_by_no_root_finds_no_list_path(two):
    hub = hub_of(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    a = address(hub)
    private = hub.entry(a).file_root
    (two.private_repo / NAME).unlink()                                         # held by nobody now
    with pytest.raises(roots_mod.NotFound):
        hub.file(a, bound=private)
    with place.held(hub, a):
        hub.committed(a, by="Member A")
    assert hub_rows("commit-refused")
    assert hub.file(a) == two.list_repo / NAME                                 # control: an unbound read of a free name


@pytest.mark.parametrize("how", ["unreadable", "missing", "no-git", "link"])
def test_unreadable_private_root_fails_closed(two, how, tmp_path):
    hub = hub_of(two)
    (two.list_repo / NAME).write_text(OPEN, encoding="utf-8")
    a = address(hub)
    assert hub.file(a).name == "post.md"                                       # control: decided, the list file is found
    with place.held(hub, a):
        hub.entry(a)
    seen = untouched(two)
    gone = tmp_path / "away"
    if how == "unreadable":
        os.chmod(two.private_repo, 0)
    elif how == "missing":
        two.private_repo.rename(gone)
    elif how == "no-git":
        (two.private_repo / ".git").rename(tmp_path / "git-away")
    else:
        (two.private_repo / NAME).symlink_to(two.list_repo / NAME)
    try:
        with pytest.raises(roots_mod.NotFound):
            hub.file(a)
        with pytest.raises(roots_mod.NotFound):
            comment(hub, a, OPEN)
        assert untouched(two) == seen
        assert "hi" not in (two.list_repo / NAME).read_text(encoding="utf-8")
    finally:
        if how == "unreadable":
            os.chmod(two.private_repo, 0o755)
        elif how == "missing":
            gone.rename(two.private_repo)
        elif how == "no-git":
            (tmp_path / "git-away").rename(two.private_repo / ".git")
        else:
            (two.private_repo / NAME).unlink()
    comment(hub, a, OPEN)                                                      # control: looked at again, it writes
    assert "hi" in (two.list_repo / NAME).read_text(encoding="utf-8")


def test_ahead_refuses_while_a_private_root_cannot_be_looked_at(two):
    hub = hub_of(two)
    (two.list_repo / NAME).write_text(OPEN, encoding="utf-8")
    a = address(hub)
    with place.held(hub, a):
        assert place.ahead(hub, a, OPEN, OPEN + "more\n") is None              # control: decided, nothing to move
        os.chmod(two.private_repo, 0)
        try:
            with pytest.raises(place.Refused):
                place.ahead(hub, a, OPEN, OPEN + "more\n")
        finally:
            os.chmod(two.private_repo, 0o755)


def test_a_private_root_refused_at_start_is_undecided_not_absent(two):
    cfg = two.config()
    (two.private_repo / ".git").rename(two.base / "git-away")                  # a restart after the clone lost its .git
    hub = two.hub(cfg)
    hub.the_list.root()
    (two.list_repo / "acme/blog").mkdir(parents=True)
    (two.list_repo / NAME).write_text(OPEN, encoding="utf-8")
    assert not hub.private_roots
    with pytest.raises(roots_mod.NotFound):
        hub.file(address(hub))


def test_duplicate_name_does_not_break_visible(two):
    hub = hub_of(two)
    (two.list_repo / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["a", "b"]\nstatus = "live"\n',
                                                 encoding="utf-8")
    for repo in (two.list_repo, two.private_repo):
        (repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    (two.list_repo / OTHER).write_text(OPEN.replace("post", "other"), encoding="utf-8")
    a, b = (hub.proxy.members[k] for k in ("member-a-id", "member-b-id"))
    for member in (a, b):
        assert hub.visible(member, address(hub)) is False                      # answers, raises nothing
    assert hub.visible(b, address(hub, OTHER)) is True                         # another member's other sheaf is shown
    assert hub.visible(a, address(hub, OTHER)) is True


def test_share_refused_private_root(two):
    hub = hub_of(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    a = address(hub)
    seen = untouched(two)
    before = (two.private_repo / NAME).read_text(encoding="utf-8")
    with place.held(hub, a):
        with pytest.raises(place.Refused, match="a sheaf of a private root cannot be shared yet"):
            place.ahead(hub, a, PRIVATE_TEXT, SHARED)                          # Share
        assert place.ahead(hub, a, PRIVATE_TEXT, PRIVATE_TEXT + "more\n") is None      # control: no move, no raise
    assert (two.private_repo / NAME).read_text(encoding="utf-8") == before
    assert not (two.list_repo / NAME).exists() and untouched(two) == seen
    with place.held(hub, a):
        with pytest.raises(place.Refused, match="cannot be shared yet"):
            place.ahead(hub, a, PRIVATE_TEXT, PRIVATE_TEXT.replace("owner: a", "owner: b"))     # Unshare to another's root
        assert place.ahead(hub, a, SHARED, SHARED + "more\n") is None           # a file not at its home is written as before


def test_poll_leaves_a_list_file_whose_home_is_a_private_root(two):
    hub = hub_of(two)
    (two.list_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    a = address(hub)
    assert place.place(hub, a) is None
    assert (two.list_repo / NAME).is_file()                                    # left where it is, not quarantined
    assert not list((two.list_repo / "acme/blog").glob("private/**/*"))
    rows = hub_rows("place-refused")
    assert [r["doc"] for r in rows] == [a] and "private root" in rows[0]["why"] and not rows[0].get("quarantined")


def test_name_in_both_roots_refused(two):
    token = Tokens().add("james-a", write=True)
    hub = hub_of(two, a={"tokens": ["james-a"]})
    (two.list_repo / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["a"]\nstatus = "live"\n',
                                                 encoding="utf-8")
    for repo in (two.list_repo, two.private_repo):
        (repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    door = browser_on(hub)
    a = address(hub)
    with pytest.raises(roots_mod.NotFound):
        hub.roots.resolve(a)                                                   # lookup
    assert call(door, "create", token=token, doc=a, text=OPEN)[0]              # create is an error, not a 500
    assert (two.private_repo / NAME).read_text(encoding="utf-8") == PRIVATE_TEXT
    assert (two.list_repo / NAME).read_text(encoding="utf-8") == PRIVATE_TEXT
    (two.list_repo / NAME).unlink()
    assert hub.roots.resolve(a) == (two.private_repo / NAME).resolve()         # control: one holder, found


def test_a_hub_without_a_private_root_still_finds_a_list_file_wherever_it_is(tmp_path):
    two = two_roots(tmp_path)
    table = two.table()
    del table["members"]["member-a-id"]["private_root"]
    hub = two.hub(proxy.parse(table, "the test", two.list_table()))
    hub.the_list.root()
    (two.list_repo / "acme/blog").mkdir(parents=True)
    (two.list_repo / NAME).write_text(OPEN, encoding="utf-8")
    a = address(hub)
    assert hub.file(a) == two.list_repo / NAME
    assert place.file_rel(hub, hub.the_list.root(), NAME) == NAME
    assert place.file_rel(hub, hub.the_list.root(), OTHER) == OTHER            # a name no file holds: itself


def test_unbound_lookup_after_a_private_root_is_forgotten_raises(two):
    hub = hub_of(two)
    (two.list_repo / NAME).write_text(OPEN, encoding="utf-8")
    a = address(hub)
    hub.forget_root(next(r.name for r in hub.roots.all() if r.id in hub.private_roots))
    with pytest.raises(roots_mod.NotFound):
        hub.file(a)                                                            # configured, not registered: undecided


def test_a_folder_below_the_private_root_that_cannot_be_read_is_undecided(two):
    hub = hub_of(two)
    for repo in (two.list_repo, two.private_repo):
        (repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    a = address(hub)
    seen = untouched(two)
    os.chmod(two.private_repo / "acme", 0)
    try:
        with pytest.raises(roots_mod.NotFound):
            hub.file(a)
        with pytest.raises(roots_mod.NotFound):
            comment(hub, a, PRIVATE_TEXT)
        assert untouched(two) == seen
    finally:
        os.chmod(two.private_repo / "acme", 0o755)


def test_ahead_refuses_a_name_two_roots_hold(two):
    hub = hub_of(two)
    for repo in (two.list_repo, two.private_repo):
        (repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    a = address(hub)
    with place.held(hub, a):
        with pytest.raises(place.Refused):
            place.ahead(hub, a, PRIVATE_TEXT, PRIVATE_TEXT + "more\n")
    (two.list_repo / NAME).unlink()
    with place.held(hub, a):
        assert place.ahead(hub, a, PRIVATE_TEXT, PRIVATE_TEXT + "more\n") is None      # control


def test_create_of_a_name_two_roots_hold_is_refused_not_a_hub_failure(two):
    token = Tokens().add("james-a", write=True)
    hub = hub_of(two, a={"tokens": ["james-a"]})
    (two.list_repo / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["a"]\nstatus = "live"\n',
                                                 encoding="utf-8")
    for repo in (two.list_repo, two.private_repo):
        (repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    door = browser_on(hub)
    is_error, got = call(door, "create", token=token, doc=address(hub), text=OPEN)
    assert is_error and "failed on this call" not in got, got
    assert not hub_rows("mcp-failed")


def test_poll_of_an_owner_only_list_file_while_a_private_root_is_undecided_is_a_refusal_row(two):
    hub = hub_of(two)
    (two.list_repo / NAME).write_text(PRIVATE_TEXT.replace("owner: a", "owner: b"), encoding="utf-8")
    a = address(hub)
    (two.private_repo / ".git").rename(two.base / "git-away")
    assert place.place(hub, a) is None
    assert (two.list_repo / NAME).is_file() and not list((two.list_repo / "acme/blog").glob("private/**/*"))
    assert [r["doc"] for r in hub_rows("place-refused")] == [a] and not hub_rows("place-failed")
