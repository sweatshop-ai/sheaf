"""The old tiroir's side of a moved root: pages sent, a Forward each, the clone asleep. A fake hub and receiver, a real clone."""
import subprocess
from types import SimpleNamespace

import pytest

from sheafmd.hub import proxy, root_moves, root_sender
from sheafmd.hub.writelog import Line

HERE, THERE = "https://here.example", "https://there.example"
ADDR = "o--r/"
H = {"a.md": "a" * 16, "b.md": "b" * 16}


def git(at, *args):
    return subprocess.run(["git", "-C", str(at), *args], check=True, capture_output=True, text=True).stdout.strip()


class Store:
    def __init__(self, texts):
        self._texts = texts

    def texts(self, address):
        return self._texts.get(address, [])

    def addresses(self, prefix):
        return [a for a in self._texts if a.startswith(prefix)]


class Repos:
    def __init__(self, dest, records):
        self.dest, self._records, self.slept, self.moved = dest, records, [], None

    def records(self, repo):
        return self._records

    def owner_of(self, repo, path):
        return self._records.get(path, {}).get("owner")

    def saves_on(self, repo):
        return "dev", ""

    def clone_dir(self, repo):
        return self.dest

    def moved_to(self, repo):
        return self.moved

    def sleep_moved(self, repo, to):
        self.slept.append((repo, to))
        self.moved = to
        return True

    def settle(self, *a, **k):
        return True

    def clones(self):
        return ["o/r"]


class Tells:
    def __init__(self):
        self.ended = []

    def end_page(self, address, why):
        self.ended.append((address, why))


class Forwards:
    def __init__(self):
        self.added = []

    def add_remote(self, old, origin, to, by, hash_, was=""):
        self.added.append((old, origin, to, by, hash_))


@pytest.fixture
def clone(tmp_path):
    bare = tmp_path / "o.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "dev", str(bare)], check=True)
    c = tmp_path / "c"
    subprocess.run(["git", "clone", "-q", str(bare), str(c)], check=True, capture_output=True)
    git(c, "checkout", "-q", "-b", "dev")
    for name in ("a.md", "b.md"):
        (c / name).write_text(f"# {name}\n")
    (c / ".sheaf.toml").write_text(f'tiroir = "{THERE}"\n')
    git(c, "add", ".")
    git(c, "-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-qm", "a")
    git(c, "push", "-q", "-u", "origin", "dev")
    return c


@pytest.fixture
def hub(clone, monkeypatch, tmp_path):
    monkeypatch.setattr(root_moves, "paired", lambda to, store=None: True)
    alice = proxy.Member(id="alice", name="Alice", roots=(), email="alice@example.com")
    records = {"a.md": {"owner": "alice", "session": "s1"}, "b.md": {"owner": "alice"}}
    line = Line(address=ADDR + "a.md", time="2026-11-25 10:00", writer="alice", place="laptop", via="render")
    return SimpleNamespace(
        proxy=SimpleNamespace(origin=HERE, members={"alice": alice}), repos=Repos(clone, records), forwards=Forwards(),
        versions=Store({ADDR + "a.md": ["# a v1\n", "# a v2\n"]}), roots=None, private_roots=set(),
        writes=SimpleNamespace(addresses=lambda prefix: [ADDR + "a.md"], lines=lambda address: [line]),
        session_tells=Tells(), waiting_tells=Tells(), record_exception=lambda *a, **k: None)


class Receiver:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, to, verb, body):
        self.calls.append((to, verb, body))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def ok(*paths):
    return 200, {"pages": {p: {"ok": True, "hash": H[p]} for p in paths}}


def run(hub, tmp_path, post):
    return root_sender.run(hub, "o/r", THERE, post=post, moves=root_moves.Moves(tmp_path / "state"))


def test_an_unpaired_target_sends_nothing(hub, tmp_path, monkeypatch):
    monkeypatch.setattr(root_moves, "paired", lambda to, store=None: False)
    post = Receiver()
    assert run(hub, tmp_path, post) == "unpaired"
    assert post.calls == [] and hub.forwards.added == []


def test_every_page_confirmed_is_forwarded_and_the_clone_sleeps(hub, tmp_path):
    post = Receiver(ok("a.md", "b.md"))
    assert run(hub, tmp_path, post) == "moved"
    (to, verb, body), = post.calls
    assert (to, verb, body["repo"], body["branch"], body["from"]["origin"]) == (THERE, "root", "o/r", "dev", HERE)
    a = next(p for p in body["pages"] if p["path"] == "a.md")
    assert a["owner_email"] == "alice@example.com" and a["record"] == {"session": "s1"}
    assert [v["text"] for v in a["versions"]] == ["# a v1\n", "# a v2\n"] and a["writes"][0]["writer"] == "alice"
    assert a["blob"] == git(hub.repos.dest, "rev-parse", "origin/dev:a.md")
    assert sorted((f[0], f[1], f[2], f[4]) for f in hub.forwards.added) == [
        (ADDR + "a.md", THERE, ADDR + "a.md", H["a.md"]), (ADDR + "b.md", THERE, ADDR + "b.md", H["b.md"])]
    assert hub.repos.slept == [("o/r", THERE)]
    assert sorted(a for a, _ in hub.session_tells.ended) == [ADDR + "a.md", ADDR + "b.md"]


def test_a_page_the_other_tiroir_refuses_stays_and_the_clone_stays_awake(hub, tmp_path):
    post = Receiver((200, {"pages": {"a.md": {"ok": True, "hash": H["a.md"]}, "b.md": {"ok": False, "why": "no_owner"}}}))
    assert run(hub, tmp_path, post) == "partial"
    assert [f[0] for f in hub.forwards.added] == [ADDR + "a.md"]
    assert hub.repos.slept == []
    assert root_moves.Moves(tmp_path / "state").get("o/r")["held"] == {"b.md": "no_owner"}


def test_unpushed_commits_hold_the_whole_move(hub, tmp_path):
    (hub.repos.dest / "a.md").write_text("# changed\n")
    git(hub.repos.dest, "-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-qam", "more")
    post = Receiver()
    assert run(hub, tmp_path, post) == "held"
    assert post.calls == [] and hub.forwards.added == [] and hub.repos.slept == []
    assert root_moves.Moves(tmp_path / "state").get("o/r")["held"] == {"a.md": "unpushed", "b.md": "unpushed"}


def test_a_page_with_no_owner_is_not_sent(hub, tmp_path):
    hub.repos._records["b.md"] = {}
    post = Receiver(ok("a.md"))
    assert run(hub, tmp_path, post) == "moved"
    assert [p["path"] for p in post.calls[0][2]["pages"]] == ["a.md"]


def test_an_answer_that_never_came_forwards_nothing_and_the_next_try_sends_again(hub, tmp_path):
    state = root_moves.Moves(tmp_path / "state")
    post = Receiver(OSError("down"), ok("a.md", "b.md"))
    assert root_sender.run(hub, "o/r", THERE, post=post, moves=state) == "held"
    assert hub.forwards.added == [] and hub.repos.slept == []
    assert root_sender.run(hub, "o/r", THERE, post=post, moves=state) == "moved"
    assert len(post.calls) == 2 and len(hub.forwards.added) == 2


def test_a_confirmed_page_is_not_sent_again_when_the_sleep_is_what_failed(hub, tmp_path):
    state = root_moves.Moves(tmp_path / "state")
    hub.repos.sleep_moved = lambda repo, to: False
    post = Receiver(ok("a.md", "b.md"))
    assert root_sender.run(hub, "o/r", THERE, post=post, moves=state) == "partial"
    hub.repos.sleep_moved = lambda repo, to: True
    assert root_sender.run(hub, "o/r", THERE, post=post, moves=state) == "moved"
    assert len(post.calls) == 1 and len(hub.forwards.added) == 2


def test_the_sweep_runs_only_a_clone_whose_toml_names_another_tiroir(hub, tmp_path):
    moves = root_moves.Moves(tmp_path / "state")
    post = Receiver(ok("a.md", "b.md"))
    assert root_sender.sweep(hub, post=post, moves=moves) == {"o/r": "moved"}
    (hub.repos.dest / ".sheaf.toml").write_text(f'tiroir = "{HERE}/"\n')
    hub.repos.moved = None
    assert root_sender.sweep(hub, post=post, moves=moves) == {}


def test_the_owner_is_matched_without_regard_to_case(hub, tmp_path):
    hub.repos._records["a.md"]["owner"] = "ALICE"
    post = Receiver(ok("a.md", "b.md"))
    assert run(hub, tmp_path, post) == "moved"
    assert "a.md" in [p["path"] for p in post.calls[0][2]["pages"]]


def test_a_move_that_confirmed_pages_before_ends_when_nothing_is_left_to_send(hub, tmp_path):
    state = root_moves.Moves(tmp_path / "state")
    hub.repos.sleep_moved = lambda repo, to: False
    assert root_sender.run(hub, "o/r", THERE, post=Receiver(ok("a.md", "b.md")), moves=state) == "partial"
    hub.repos._records.clear()
    hub.writes.addresses = lambda prefix: []
    hub.versions._texts.clear()
    hub.repos.sleep_moved = lambda repo, to: True
    assert root_sender.run(hub, "o/r", THERE, post=Receiver(), moves=state) == "moved"
    assert state.get("o/r") is None


def test_an_unpaired_target_is_written_to_the_diagnostics_once_across_sweeps(hub, tmp_path, monkeypatch):
    monkeypatch.setattr(root_moves, "paired", lambda to, store=None: False)
    monkeypatch.setattr(root_sender, "DIAG", root_moves.Diag())
    rows = []
    monkeypatch.setattr(root_moves.diagnostics, "record", lambda *a, **k: rows.append(a))
    for _ in range(3):
        root_sender.sweep(hub, post=Receiver(), moves=root_moves.Moves(tmp_path / "state"))
    assert len(rows) == 1
