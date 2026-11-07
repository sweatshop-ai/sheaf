"""The list over two roots (SPEC 9.10, 9.11): a sheaf of a member's private root is a row of that member alone, and a tick
on it commits in the private repo and never in the list's. Each refusal has the member's own call as its positive control,
on the same route."""
import subprocess

import pytest
from helpers import Front, browser_on, hub_rows
from test_hub_list import TOKEN, FakeGitHub, ago, read, row_press
from two_roots import A, B, TwoRoots, git, repo_with_remote, two_roots

from sheafmd.hub import proxy, the_list
from sheafmd.source import md_hash

NAME = "acme/blog/post.md"
TEXT = """---
issue: acme/record#1
owner: a
sources: [library:doc-1]
---
# Post

- [ ] Approve

Secret words.
"""
ROW = "acme/blog"


@pytest.fixture
def two(tmp_path) -> TwoRoots:
    return two_roots(tmp_path)


class World:
    def __init__(self, two: TwoRoots, assignees=("login-a",)):
        self.two = two
        self.github = FakeGitHub()
        self.github.issues = {1: {"status": "Waiting on member", "assignees": list(assignees), "updated": ago(3600)}}
        (two.base / "token").write_text(TOKEN + "\n", encoding="utf-8")
        self.hub = two.hub(two.config(a={"github": "login-a"}, b={"github": "login-b"}))
        self.hub.the_list = the_list.TheList(self.hub, the_list.parse(
            {"root": str(two.list_repo), "repo": "acme/record", "project": 1, "token_file": str(two.base / "token"),
             "api": self.github.url}, "the test"))
        self.root = self.hub.the_list.root()
        for repo in (two.list_repo, two.private_repo):
            (repo / "acme/blog").mkdir(parents=True, exist_ok=True)
        (two.list_repo / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["a", "b"]\nstatus = "live"\n',
                                                     encoding="utf-8")
        self.front = Front(self.hub, browser_on(self.hub).handler)
        self.address = f"{self.root.name}/{NAME}"

    def put(self, text, repo=None):
        (repo or self.two.private_repo).joinpath(NAME).write_text(text, encoding="utf-8")

    def rows(self, member) -> list:
        self.hub.the_list.poll()
        page = read(self.front.get(f"/{self.root.name}?show=all", member=member))
        return [r for sections in page.values() for rows in sections.values() for r in rows]

    def tick(self, member):
        """The tick the row's button posts, as `member` posts it with the hash of the file as it is now."""
        body = {"doc": self.address, "action": 0, "word": "Approve", "hash": md_hash(TEXT)}
        return self.front.request("POST", "/_/tick", member=member, body=body)

    def heads(self) -> tuple:
        return tuple(git(r, "rev-parse", "HEAD").strip() for r in (self.two.list_repo, self.two.private_repo))


@pytest.fixture
def world(two):
    w = World(two)
    yield w
    w.github.close()


def test_list_private_row_only_for_member(world):
    w = world
    w.put(TEXT)
    assert len(w.rows(A)) == 1 and "Post" in w.rows(A)[0][0]
    assert w.rows(B) == []                              # B is no member of that root and no assignee


def test_list_tick_private_repo(world):
    w = world
    w.put(TEXT)
    git(w.two.private_repo, "add", "-A"), git(w.two.private_repo, "commit", "-q", "-m", "post")
    before = w.heads()
    assert w.rows(A)
    page = w.front.get(f"/{w.root.name}", member=A)
    press = row_press(page, w.address)
    assert w.front.request("POST", "/_/tick", member=A, body=press).status == 200
    assert "- [x] Approve" in (w.two.private_repo / NAME).read_text(encoding="utf-8")
    after = w.heads()
    assert after[0] == before[0] and after[1] != before[1]      # a commit in the private repo, none in the list's
    assert "tick" in git(w.two.private_repo, "log", "-1", "--format=%s")
    assert not (w.two.list_repo / NAME).exists()
    assert git(w.two.private_repo, "status", "--porcelain") == ""
    assert read(w.front.get(f"/{w.root.name}?show=all", member=A))["Waiting on you 0"] == {}     # the row moved


def test_assignee_no_row_no_tick_private_sheaf(two):
    w = World(two, ["login-a", "login-b"])              # the issue is assigned to B too
    try:
        w.put(TEXT)
        assert w.rows(B) == []
        before = w.heads()
        gone = w.tick(B)
        assert gone.status == 404, (gone.status, gone.body[:200])
        assert (w.two.private_repo / NAME).read_text(encoding="utf-8") == TEXT and w.heads() == before
        assert len(w.rows(A)) == 1 and w.tick(A).status == 200          # the member's own tick, the same route
    finally:
        w.github.close()


def test_tick_same_name_writes_nothing_to_list(world):
    w = world
    w.put(TEXT)
    assert w.rows(A)
    w.put(TEXT.replace("Secret", "Shared"), w.two.list_repo)       # the same name arrives in the list repo by a pull
    before = w.heads()
    assert w.tick(A).status != 200
    assert w.heads() == before
    assert "- [ ] Approve" in (w.two.list_repo / NAME).read_text(encoding="utf-8")
    assert "- [ ] Approve" in (w.two.private_repo / NAME).read_text(encoding="utf-8")
    assert (w.two.list_repo / NAME).read_text(encoding="utf-8") == TEXT.replace("Secret", "Shared")      # as it arrived


def test_list_name_in_both_roots_no_row(world):
    w = world
    w.put(TEXT)
    assert len(w.rows(A)) == 1
    w.put(TEXT, w.two.list_repo)
    assert w.rows(A) == [] and w.rows(B) == []
    (w.two.list_repo / NAME).unlink()
    assert len(w.rows(A)) == 1                                  # the control: one holder, and the row is back


def test_list_row_of_private_file_judged_on_the_file_read(two, monkeypatch):
    w = World(two, ["login-a", "login-b"])
    try:
        w.put(TEXT)
        w.hub.the_list.poll()
        w.put(TEXT.replace("Secret", "Changed"))                   # the file is not the one the poll read
        monkeypatch.setattr(w.hub, "visible", lambda *a, **k: True)     # a look that passed before the file moved in
        assert read(w.front.get(f"/{w.root.name}?show=all", member=B))["Waiting on you 0"] == {}
        assert len(read(w.front.get(f"/{w.root.name}?show=all", member=A))["Waiting on you 1"][ROW]) == 1
    finally:
        w.github.close()


def test_list_name_in_two_private_roots_no_row_no_tick(tmp_path):
    """One name in the private roots of A and of B: a row in neither, no title or tick of one reaches the other, and a
    tick commits nowhere. The control: with B's file gone, A's row is back and A's tick lands in A's repo only."""
    two = two_roots(tmp_path)
    other = repo_with_remote(tmp_path, "private-b")
    table = two.table(b={"short": "b", "roots": [str(two.list_repo), str(other)], "private_root": str(other)})
    github = FakeGitHub()
    github.issues = {1: {"status": "Waiting on member", "assignees": ["login-a", "login-b"], "updated": ago(3600)}}
    (tmp_path / "token").write_text(TOKEN + "\n", encoding="utf-8")
    table["members"][A]["github"], table["members"][B]["github"] = "login-a", "login-b"
    hub = two.hub(proxy.parse(table, "the test", two.list_table()))
    hub.the_list = the_list.TheList(hub, the_list.parse(
        {"root": str(two.list_repo), "repo": "acme/record", "project": 1, "token_file": str(tmp_path / "token"),
         "api": github.url}, "the test"))
    try:
        for repo in (two.list_repo, two.private_repo, other):
            (repo / "acme/blog").mkdir(parents=True, exist_ok=True)
        (two.list_repo / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["a", "b"]\nstatus = "live"\n',
                                                     encoding="utf-8")
        mine, theirs = TEXT, TEXT.replace("# Post", "# Theirs").replace("Secret", "Hidden")
        (two.private_repo / NAME).write_text(mine, encoding="utf-8")
        (other / NAME).write_text(theirs, encoding="utf-8")
        for repo in (two.private_repo, other):
            git(repo, "add", "-A"), git(repo, "commit", "-q", "-m", "post")
        front = Front(hub, browser_on(hub).handler)
        address = f"{hub.the_list.root().name}/{NAME}"

        def shown(member):
            hub.the_list.poll()
            return front.get(f"/{hub.the_list.root().name}?show=all", member=member)

        heads = lambda: tuple(git(r, "rev-parse", "HEAD").strip() for r in (two.list_repo, two.private_repo, other))
        for member in (A, B):
            page = shown(member)
            assert "Post" not in page.body.decode() and "Theirs" not in page.body.decode()
        refused = [r for r in hub_rows("place-refused") if r["doc"].endswith(NAME)]
        assert refused and "held by 2 files" in refused[0]["why"]
        before = heads()
        for member, text in ((A, mine), (B, theirs)):
            body = {"doc": address, "action": 0, "word": "Approve", "hash": md_hash(text)}
            assert front.request("POST", "/_/tick", member=member, body=body).status != 200
        assert heads() == before
        assert (two.private_repo / NAME).read_text(encoding="utf-8") == mine
        assert (other / NAME).read_text(encoding="utf-8") == theirs
        assert not (two.list_repo / NAME).exists()
        (other / NAME).unlink()
        shown(A)
        assert "Post" in shown(A).body.decode() and "Theirs" not in shown(A).body.decode()
        assert "Post" not in shown(B).body.decode()
        press = row_press(front.get(f"/{hub.the_list.root().name}", member=A), address)
        assert front.request("POST", "/_/tick", member=A, body=press).status == 200
        assert heads()[0] == before[0] and heads()[1] != before[1]
    finally:
        github.close()
