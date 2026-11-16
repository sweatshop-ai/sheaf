"""A repo clone that nobody uses for thirty days sleeps (SPEC 13): no fetch, a sparse set shrunk to nothing, its pages
still read at their last text from the commit; a new report wakes it and widens the set again. Nothing in a repo is
archived, deleted or marked, and only the member deletes a clone. Against local bare repos and a fake App, as
tests/test_repo_pages.py does."""

import pytest
from test_hub_commits import box, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)
from test_repo_pages import REPO, app, clones, hub_repos, origin, report, sh, the_clone  # noqa: F401  (fixtures and helpers)
from test_send import keyring, local, no_real_keyring, run, scratch, tiroir  # noqa: F401  (fixtures)
from test_write_log import agents  # noqa: F401  (fixture)

from sheafmd.hub import archive

DAY = 86400


@pytest.fixture
def napping(hub_repos):
    """A clone made by a report, and a clock under the test's control for the repos."""
    now = [1_000_000.0]
    hub_repos.hub.repos.clock = lambda: now[0]
    assert not report(hub_repos, path="docs/plan.md")[0]
    assert not report(hub_repos, path="notes/idea.md")[0]
    hub_repos.now = now
    return hub_repos


def fetches(repos, monkeypatch):
    seen = []
    real = repos._git

    def watch(at, *args, **kw):
        seen.append(args)
        return real(at, *args, **kw)
    monkeypatch.setattr(repos, "_git", watch)
    return seen


def test_a_clone_with_no_report_and_no_write_for_thirty_days_sleeps(napping):
    repos = napping.hub.repos
    napping.now[0] += 29 * DAY
    repos.sleep_idle()
    assert not repos.sleeping(REPO)
    napping.now[0] += 2 * DAY
    repos.sleep_idle()
    assert repos.sleeping(REPO)


def test_a_sleeping_clones_sparse_set_is_narrowed_and_its_pages_open_at_their_last_text(napping):
    repos = napping.hub.repos
    clone, commit = the_clone(napping), sh(napping.origin, "rev-parse", "main")
    napping.now[0] += 31 * DAY
    repos.sleep_idle()
    assert sh(clone, "sparse-checkout", "list").split() == []
    assert not (clone / "docs" / "plan.md").exists()                    # the work tree is shrunk
    assert repos.page_text(REPO, "docs/plan.md", commit) == "# Plan\n\nA plan.\n"      # the page opens from the commit


def test_a_sleeping_clone_runs_no_fetch_and_a_commit_it_lacks_is_not_known(napping, monkeypatch):
    repos = napping.hub.repos
    napping.now[0] += 31 * DAY
    repos.sleep_idle()
    seen = fetches(repos, monkeypatch)
    assert repos._knows(the_clone(napping), REPO, "0" * 40, "ghs_faketoken") is False
    assert [a for a in seen if a[:1] in (("fetch",), ("merge",))] == []


def test_a_sleeping_clone_runs_no_fetch_on_a_report_for_a_commit_it_has(napping, monkeypatch):
    repos = napping.hub.repos
    napping.now[0] += 31 * DAY
    repos.sleep_idle()
    seen = fetches(repos, monkeypatch)
    assert repos._knows(the_clone(napping), REPO, sh(napping.origin, "rev-parse", "main"), "ghs_faketoken") is True
    assert [a for a in seen if a[:1] in (("fetch",), ("merge",))] == []


def test_a_new_report_for_the_repo_wakes_the_clone_and_widens_the_set_again(napping):
    repos = napping.hub.repos
    napping.now[0] += 31 * DAY
    repos.sleep_idle()
    assert repos.sleeping(REPO)
    assert not report(napping, path="docs/plan.md")[0]
    assert not repos.sleeping(REPO)
    assert sh(the_clone(napping), "sparse-checkout", "list").split() == ["docs", "notes"]
    assert (the_clone(napping) / "notes" / "idea.md").is_file()


def test_a_report_keeps_a_clone_awake(napping):
    repos = napping.hub.repos
    napping.now[0] += 20 * DAY
    assert not report(napping, path="docs/plan.md")[0]
    napping.now[0] += 20 * DAY
    repos.sleep_idle()
    assert not repos.sleeping(REPO)


def test_nothing_in_a_repo_is_archived_deleted_or_marked(napping):
    clone = the_clone(napping)
    before = sh(clone, "status", "--porcelain")
    napping.now[0] += 400 * DAY
    napping.hub.clock = lambda: napping.now[0]
    archive.sweep(napping.hub)
    napping.hub.repos.sleep_idle()
    assert sh(clone, "status", "--porcelain") == before
    assert not (clone / ".sheaf").exists()
    for route in ("/_/archive", "/_/keep", "/_/delete"):
        assert napping.post(route, {"doc": f"{REPO}/docs/plan.md", "on": True}, member="0f8fad5b-d9cb-469f-a165-70867728950e").status == 404


def test_only_the_member_deletes_a_clone_nothing_in_the_sweep_removes_it(napping):
    napping.now[0] += 400 * DAY
    napping.hub.clock = lambda: napping.now[0]
    napping.hub.tick()
    napping.hub.repos.sleep_idle()
    napping.hub.repos.sleep_idle()
    assert (the_clone(napping) / ".git").exists()


def test_the_hub_tick_puts_an_idle_clone_to_sleep(napping):
    napping.now[0] += 31 * DAY
    napping.hub.clock = lambda: napping.now[0]
    napping.hub.tick()
    assert napping.hub.repos.sleeping(REPO)
