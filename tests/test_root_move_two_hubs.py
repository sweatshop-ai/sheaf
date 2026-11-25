"""A root moves from one tiroir to another, end to end: two in-memory hubs, a local bare repo, a real clone on each side.

The old tiroir holds a page of the repo with its versions and Write log lines. The repo's `.sheaf.toml` is changed to name the other
tiroir and the old clone takes the change; the old tiroir's sweep sends the root over the channel (a POST of `/_/tiroir/root` on
the other hub's handler, with a peer token), writes a Forward for the page and puts its clone to sleep. After it:
every old address forwards, the versions and Write log lines are on the new tiroir, and the old clone sleeps."""
import subprocess

import pytest
from test_repo_pages import REPO, FakeApp, origin, sh  # noqa: F401  (fixtures and helpers)
from two_hubs import Link, Site

from sheafmd.hub import repos as repos_mod
from sheafmd.hub import root_moves, root_sender
from sheafmd.hub.repos import Repos

OLD, NEW = "https://old.example", "https://new.example"
ALICE = "a1000000-0000-4000-8000-000000000001"
PAGE = "docs/plan.md"
ADDRESS = f"{repos_mod.root_name(REPO)}/{PAGE}"
V1, V2 = "# Plan\n\nA plan.\n", "# Plan\n\nA plan, edited.\n"


@pytest.fixture
def tiroirs(tmp_path, origin, monkeypatch):  # noqa: F811
    monkeypatch.setattr(root_moves, "paired", lambda to, store=None: True)
    old = Site(tmp_path, "old", 27431, OLD, {ALICE: ("Alice", "alice@example.com", False)})
    new = Site(tmp_path, "new", 27432, NEW, {ALICE: ("Alice", "alice@example.com", False)})
    for site in (old, new):
        with site.inside():
            site.hub.repos = Repos(tmp_path / f"{site.name}-clones", FakeApp(), remote_url=lambda repo: str(origin))
            site.hub.repos.FETCH_EVERY = 0.0
    old.link = Link(new, new.peer_token(OLD, ["transfer"], name="from-old"))
    yield old, new
    for site in (old, new):
        assert site.hub.repos.settle(), "the tiroir's thread did not finish"


def report(site, origin_repo, path=PAGE):
    """Alice's render report of `path` at the repo's tip, waited for; the answer once the clone is there."""
    commit = sh(origin_repo, "rev-parse", "main")
    got = site.hub.repos.report("alice", REPO, path, commit)
    assert site.hub.repos.settle()
    if got["clone"] == repos_mod.CLONING:
        got = site.hub.repos.report("alice", REPO, path, commit)
        assert site.hub.repos.settle()
    return got


def toml(origin_repo, tmp_path, text, why):
    """The repo's `.sheaf.toml` on its default branch is `text`, pushed as a person would."""
    seed = tmp_path / "toml-seed"
    if not seed.exists():
        subprocess.run(["git", "clone", "-q", str(origin_repo), str(seed)], check=True, capture_output=True)
        sh(seed, "config", "user.name", "Dee Dev")
        sh(seed, "config", "user.email", "dee@example.com")
    sh(seed, "pull", "-q", "origin", "main")
    (seed / ".sheaf.toml").write_text(text, encoding="utf-8")
    sh(seed, "add", ".sheaf.toml")
    sh(seed, "commit", "-q", "-m", why)
    sh(seed, "push", "-q", "origin", "HEAD:main")


def saves_on_main(origin_repo, tmp_path):
    toml(origin_repo, tmp_path, 'branch = "main"\n', "pages are saved on main")


def name_the_other_tiroir(origin_repo, tmp_path):
    toml(origin_repo, tmp_path, f'tiroir = "{NEW}"\nbranch = "main"\n', "this repo's pages are kept on the other tiroir")


def pull(site, origin_repo):
    """The hub's own pull of its clone: what the commits loop does once the change is on the remote."""
    clone = site.hub.repos.clone_dir(REPO)
    sh(clone, "fetch", "-q", "origin", "main")
    sh(clone, "merge", "-q", "--ff-only", "origin/main")


def seed_state(old):
    """What the old tiroir keeps of the page that git does not: two versions and two Write log lines."""
    with old.inside():
        old.hub.versions.put(ADDRESS, V1, "alice")
        old.hub.versions.put(ADDRESS, V2, "alice")
        old.hub.writes.add(ADDRESS, "alice", "laptop", "render", session="s-1")
        old.hub.writes.add(ADDRESS, "alice", "laptop", "save", session="s-1")


def sweep(old, tmp_path):
    with old.inside():
        return root_sender.sweep(old.hub, post=old.link, moves=root_moves.Moves(tmp_path / "moves"))


def test_the_old_tiroir_sends_the_root_forwards_every_page_and_sleeps(tiroirs, origin, tmp_path):  # noqa: F811
    old, new = tiroirs
    saves_on_main(origin, tmp_path)
    report(old, origin)
    seed_state(old)
    name_the_other_tiroir(origin, tmp_path)
    pull(old, origin)

    first = sweep(old, tmp_path)                            # the new tiroir has no clone yet: it answers cloning, nothing is lost
    assert first == {REPO: "held"} and old.hub.repos.moved_to(REPO) is None
    assert new.hub.repos.settle()                           # the clone it began on the first call
    assert sweep(old, tmp_path) == {REPO: "moved"}

    entry = old.hub.forwards.remote(ADDRESS)
    assert entry is not None and entry["origin"] == NEW
    assert old.hub.repos.moved_to(REPO) == NEW and old.hub.repos.sleeping(REPO)
    with new.inside():
        assert sorted(texts := new.hub.versions.texts(ADDRESS)) == sorted([V1, V2]), texts
        lines = [(w.writer, w.via) for w in new.hub.writes.lines(ADDRESS)]
        assert lines[:2] == [("alice", "render"), ("alice", "save")], lines     # then the landing's own line
        assert new.hub.repos.owner_of(REPO, PAGE) == "alice"
    assert [c[1] for c in old.link.asked] == ["root", "root"]


def test_a_second_sweep_after_the_move_sends_nothing(tiroirs, origin, tmp_path):  # noqa: F811
    old, new = tiroirs
    saves_on_main(origin, tmp_path)
    report(old, origin)
    seed_state(old)
    name_the_other_tiroir(origin, tmp_path)
    pull(old, origin)
    sweep(old, tmp_path)
    assert new.hub.repos.settle()
    assert sweep(old, tmp_path) == {REPO: "moved"}
    asked = len(old.link.asked)
    assert sweep(old, tmp_path) == {REPO: "moved"}
    assert len(old.link.asked) == asked
