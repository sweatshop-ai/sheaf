"""A sheaf of a private root can be opened and written (SPEC 9.11): the hub finds its file in the private root, commits
and pushes it in the private repo under the sheaf's name lock, and an open document stays bound to the root its file
was found in, so a file that appears under the same name in the list's root is never written to."""
import threading

import pytest
from helpers import hub_rows
from two_roots import TwoRoots, git, two_roots

from sheafmd.blocks import split_md_blocks
from sheafmd.hub import place, roots as roots_mod
from sheafmd.source import md_hash

NAME = "acme/blog/post.md"
OTHER = "acme/blog/open.md"
PRIVATE_TEXT = "---\nowner: member-a-id\nsources: [library:doc-1]\n---\n# post\n\nSecret words.\n"
OPEN = "# post\n\nShared words.\n"


@pytest.fixture
def two(tmp_path) -> TwoRoots:
    return two_roots(tmp_path)


def hub_of(two: TwoRoots):
    hub = two.hub()
    hub.the_list.root()
    (two.list_repo / "acme/blog").mkdir(parents=True)
    (two.private_repo / "acme/blog").mkdir(parents=True)
    return hub


def address(hub, name=NAME):
    return f"{hub.the_list.root().name}/{name}"


def save(hub, name=NAME, words="Edited."):
    """A page's save of the first paragraph, through the entry, then the commit the handler makes after it."""
    a = address(hub, name)
    with place.held(hub, a):
        e = hub.entry(a)
        text = e.path.read_text(encoding="utf-8")
        i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith(("Secret", "Shared")))
        e.live.save(md_hash(text), [{"i": i, "html": f"<p>{words}</p>"}])
        hub.committed(a, by="Member A")


def remote_files(two, repo):
    git(two.base / f"{repo}.git", "rev-parse", "main")
    return git(two.base / f"{repo}.git", "log", "--name-only", "--format=").split()


def test_member_opens_and_saves_private_sheaf(two):
    hub = hub_of(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    save(hub, words="Changed secret.")
    assert "Changed secret." in (two.private_repo / NAME).read_text(encoding="utf-8")
    assert not (two.list_repo / NAME).exists()
    assert hub.commits.settle()
    assert NAME in remote_files(two, "private")


def test_two_roots_commit_and_push_independently(two):
    hub = hub_of(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    (two.list_repo / OTHER).write_text(OPEN, encoding="utf-8")
    before = {r: git(two.base / r, "rev-list", "--count", "HEAD").strip() for r in ("list", "private")}
    save(hub, NAME)
    assert hub.commits.settle()
    assert git(two.base / "list", "rev-list", "--count", "HEAD").strip() == before["list"]      # no commit in the other
    assert git(two.base / "private", "rev-list", "--count", "HEAD").strip() != before["private"]
    save(hub, OTHER)
    assert hub.commits.settle()
    assert OTHER in remote_files(two, "list") and OTHER not in remote_files(two, "private")
    assert NAME in remote_files(two, "private") and NAME not in remote_files(two, "list")


def test_private_pull_holds_name_lock(two):
    hub = hub_of(two)
    private = next(r for r in hub.roots.all() if r.id in hub.private_roots)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    got = threading.Event()

    def writer():
        with place.held(hub, address(hub)):
            got.set()

    with hub._writers_out(private, [str(two.private_repo / NAME)]):
        t = threading.Thread(target=writer)
        t.start()
        assert not got.wait(0.5)                    # a save of the name waits while the pull changes its file
    assert got.wait(5)
    t.join()


def untouched(two):
    return (git(two.list_repo, "status", "--porcelain", "--untracked-files=all"), git(two.list_repo, "ls-files"),
            git(two.list_repo, "log", "origin/main..", "--oneline"))


def test_private_file_gone_same_name_list_file_no_write(two):
    hub = hub_of(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    a = address(hub)
    e = hub.entry(a)
    assert e.file_root in hub.private_roots
    (two.private_repo / NAME).unlink()
    (two.list_repo / NAME).write_text(OPEN, encoding="utf-8")                  # arrives by a pull
    git(two.list_repo, "add", "-A")
    git(two.list_repo, "commit", "-q", "-m", "arrives")
    git(two.list_repo, "push", "-q", "origin", "HEAD:main")
    seen = untouched(two)
    with pytest.raises(roots_mod.NotFound):
        save(hub)
    with pytest.raises(roots_mod.NotFound):
        hub.entry(a)                                                           # render
    with pytest.raises(roots_mod.NotFound):
        e.live.comment("add", {"anchor": "x", "body": "hi"}, md_hash(OPEN))    # comment
    with place.held(hub, a):
        hub.committed(a, by="Member A")                                        # nothing to commit there
    assert hub.commits.settle()
    assert untouched(two) == seen
    assert (two.list_repo / NAME).read_text(encoding="utf-8") == OPEN
    assert [r["doc"] for r in hub_rows("commit-refused")] == [a]


def test_private_file_back_where_it_was_opens_again(two):
    hub = hub_of(two)
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    a = address(hub)
    hub.entry(a)
    (two.private_repo / NAME).rename(two.private_repo / "away.txt")
    with pytest.raises(roots_mod.NotFound):
        hub.entry(a)
    (two.private_repo / "away.txt").rename(two.private_repo / NAME)
    assert hub.entry(a).path == (two.private_repo / NAME).resolve()            # the entry was kept, not rebound


def test_list_entry_is_dropped_when_its_name_moves_to_a_private_root(two):
    hub = hub_of(two)
    (two.list_repo / NAME).write_text(OPEN, encoding="utf-8")
    a = address(hub)
    e = hub.entry(a)
    assert e.file_root == hub.the_list.root().id
    (two.list_repo / NAME).unlink()
    (two.private_repo / NAME).write_text(PRIVATE_TEXT, encoding="utf-8")
    git(two.list_repo, "add", "-A")
    git(two.list_repo, "commit", "-q", "-m", "gone")
    before, tree = untouched(two), sorted(p for p in two.list_repo.rglob("*") if ".git" not in p.parts)
    save(hub, words="Private edit.")
    assert hub.entry(a) is not e and hub.entry(a).file_root in hub.private_roots
    assert hub.commits.settle()
    assert "Private edit." in (two.private_repo / NAME).read_text(encoding="utf-8")
    assert untouched(two)[0] == before[0]                                       # the list repo's tree is untouched
    assert sorted(p for p in two.list_repo.rglob("*") if ".git" not in p.parts) == tree      # no versions store either
