"""The fix round of the fifth review of ticket 21 part 2b, against the real stores: no fake."""
import os
import subprocess
import threading

import pytest
from test_repo_pages import REPO, FakeApp, origin  # noqa: F401  (fixtures and helpers)

from sheafmd.hub import state as hub_state
from sheafmd.hub.repos import Repos
from sheafmd.hub.writelog import WriteLog


@pytest.fixture
def repos(tmp_path, origin):  # noqa: F811
    r = Repos(tmp_path / "clones", FakeApp(), remote_url=lambda repo: str(origin))
    r.FETCH_EVERY = 0.0
    return r


def test_the_root_toml_is_read_from_git_at_a_commit(repos):
    dest = repos.clone_dir(REPO)
    dest.mkdir(parents=True)
    run = lambda *a: subprocess.run(["git", "-C", str(dest), *a], check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    run("init", "-q", "-b", "dev")
    (dest / ".sheaf.toml").write_text('tiroir = "https://here.example"\n')
    run("add", ".sheaf.toml")
    run("-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-qm", "t")
    assert repos.root_toml(REPO, run("rev-parse", "HEAD")) == 'tiroir = "https://here.example"\n'
    assert repos.root_toml(REPO, "0" * 40) is None


def test_the_owned_pages_of_a_root_are_all_queued_past_the_cap_of_a_laptops_reports(repos):
    repos._queues[REPO.lower()] = []        # a thread is busy with the repo
    owned = [("bea", f"p{n}.md") for n in range(repos_cap() + 40)]
    assert repos.report_rest(REPO, "c0ffee1", owned) == {}
    assert len(repos._queues[REPO.lower()]) == len(owned)


def repos_cap():
    from sheafmd.hub.repos import MAX_QUEUED
    return MAX_QUEUED


def test_an_owner_whose_private_root_it_is_gets_that_answer_and_the_others_still_queue(repos, monkeypatch):
    monkeypatch.setattr(repos, "_is_private_root", lambda repo, root: True)
    repos._queues[REPO.lower()] = []
    got = repos.report_rest(REPO, "c0ffee1", [("bea", "a.md"), ("dan", "b.md")], [("bea", "/x")])
    assert got == {"a.md": "private-root", "b.md": "not-cloned"}
    assert repos._queues[REPO.lower()] == []
    monkeypatch.setattr(repos, "_is_private_root", lambda repo, root: False)
    assert repos.report_rest(REPO, "c0ffee1", [("dan", "b.md")], [("bea", "/x")]) == {}
    assert [item[1] for item in repos._queues[REPO.lower()]] == ["b.md"]


def test_settle_for_a_repo_joins_only_that_repos_thread(repos):
    stop = threading.Event()
    other = threading.Thread(target=stop.wait, name="repos-other/x", daemon=True)
    other.start()
    repos._threads.add(other)
    try:
        assert repos.settle(0.5, repo=REPO) is True
        assert repos.settle(0.2) is False
    finally:
        stop.set()


def test_a_page_whose_row_is_at_the_commit_already_is_not_queued_again(repos):
    repos._write({"o/r": {"a.md": {"owner": "al", "commit": "c" * 40}}})
    repos._enqueue = lambda repo, *items, cap=True: setattr(repos, "queued", items)
    repos.report_rest("o/r", "c" * 40, [("al", "a.md"), ("al", "b.md")])
    assert [i[1] for i in repos.queued] == ["b.md"]
def test_take_back_gives_the_versions_their_order_and_their_age(tmp_path):
    store = hub_state.Versions()
    address = "o--r/a.md"
    prior = [f"# prior {n}\n" for n in range(hub_state.VERSIONS_KEPT)]
    for n, text in enumerate(prior):
        store.put(address, text)
        f = store._folder(address) / f"{hub_state.md_hash(text)}.md"
        os.utime(f, ns=(1_000_000_000_000 + n * 10**9,) * 2)
    before, stamps = store.texts(address), store.stamps(address)
    made = [f"# incoming {n}\n" for n in range(3)]
    for text in made:
        store.put(address, text)
    store.take_back(address, before, made, stamps)
    assert store.texts(address) == before
    assert store.stamps(address) == stamps


def test_take_back_leaves_the_age_of_a_version_the_landing_touched_as_it_was(tmp_path):
    store = hub_state.Versions()
    address = "o--r/a.md"
    store.put(address, "# same\n")
    f = store._folder(address) / f"{hub_state.md_hash('# same' + chr(10))}.md"
    os.utime(f, ns=(1_000_000_000_000,) * 2)
    before, stamps = store.texts(address), store.stamps(address)
    store.put(address, "# same\n")      # an incoming version identical to a prior one counts as written now
    store.take_back(address, before, ["# same\n"], stamps)
    assert store.stamps(address) == stamps


def test_a_path_that_is_not_a_markdown_path_is_refused_alone_and_the_other_pages_still_queue(repos):
    repos._queues[REPO.lower()] = []
    got = repos.report_rest(REPO, "c0ffee1", [("al", "a.md"), ("al", ".sheaf.toml"), ("al", "b.md")])
    assert got == {".sheaf.toml": "refused"}
    assert [item[1] for item in repos._queues[REPO.lower()]] == ["a.md", "b.md"]
