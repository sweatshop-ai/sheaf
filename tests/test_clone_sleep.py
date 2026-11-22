"""A repo clone that nobody uses for thirty days sleeps (SPEC 13): no fetch, a sparse set shrunk to nothing, its pages
still read at their last text from the commit; a new report wakes it and widens the set again. Nothing in a repo is
archived, deleted or marked, and only the member deletes a clone. Against local bare repos and a fake App, as
tests/test_repo_pages.py does."""

import threading

import pytest
from test_hub_commits import box, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)
from test_repo_pages import REPO, app, clones, hub_repos, origin, report, report_once, sh, the_clone  # noqa: F401  (fixtures and helpers)
from test_send import keyring, local, no_real_keyring, run, scratch, tiroir  # noqa: F401  (fixtures)
from test_write_log import agents  # noqa: F401  (fixture)

from sheafmd import diagnostics
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


def test_settle_never_joins_a_thread_that_is_registered_and_not_yet_started(napping, monkeypatch):
    # CI run 43995955723: the fixture's settle() joined the repo's thread between its entry in `_threads` and its start() and
    # raised "cannot join thread before it is started". Here a settle() is called in exactly that gap, from another thread.
    repos, errors, helper = napping.hub.repos, [], []
    real = threading.Thread.start

    def start(self):
        if self.name == f"repos-{REPO}" and not helper:
            def look():
                try:
                    repos.settle(5.0)
                except BaseException as e:
                    errors.append(e)
            helper.append(threading.Thread(target=look))
            real(helper[0])
            helper[0].join(0.5)         # a settle that ran in the gap is over by now; one held back by the guard is not
        real(self)
    monkeypatch.setattr(threading.Thread, "start", start)
    napping.now[0] += 31 * DAY
    repos.sleep_idle()
    assert helper, "no thread of the repo was started"
    helper[0].join(10)
    assert errors == []


def test_the_hub_tick_puts_an_idle_clone_to_sleep(napping):
    napping.now[0] += 31 * DAY
    napping.hub.clock = lambda: napping.now[0]
    napping.hub.tick()
    napping.hub.archive.settle()
    assert napping.hub.repos.sleeping(REPO)


def test_a_clone_is_shrunk_on_the_repos_own_thread_and_not_on_the_callers(napping, monkeypatch):
    repos, threads = napping.hub.repos, []
    real = repos._git

    def watch(at, *args, **kw):
        if args[:1] == ("sparse-checkout",):
            threads.append(threading.current_thread().name)
        return real(at, *args, **kw)
    monkeypatch.setattr(repos, "_git", watch)
    napping.now[0] += 31 * DAY
    repos.sleep_idle()
    assert threads and all(name == f"repos-{REPO}" for name in threads)


def test_a_report_that_comes_while_a_clone_goes_to_sleep_leaves_it_awake_and_full(napping, monkeypatch):
    repos, woke, reported = napping.hub.repos, threading.Event(), []
    real_git, real_wake = repos._git, repos._wake

    def git_(at, *args, **kw):
        out = real_git(at, *args, **kw)
        if args == ("sparse-checkout", "set", "--cone") and not reported:       # the shrink has run: a report comes in
            reported.append(report_once(napping))
            woke.wait(0.5)      # a wake that runs beside the sleep would end here; one that waits its turn is not waited for
        return out

    def wake(*args, **kw):
        woke.set()
        return real_wake(*args, **kw)
    monkeypatch.setattr(repos, "_git", git_)
    monkeypatch.setattr(repos, "_wake", wake)
    napping.now[0] += 31 * DAY
    repos.sleep_idle()
    assert repos.settle()
    assert reported and not reported[0][0]
    assert not repos.sleeping(REPO)
    assert sh(the_clone(napping), "sparse-checkout", "list").split() == ["docs", "notes"]


def test_a_clone_that_does_not_finish_going_to_sleep_is_left_for_the_next_round_and_logged(napping, monkeypatch):
    repos, release, rows = napping.hub.repos, threading.Event(), []
    real = repos._git

    def slow(at, *args, **kw):
        if args[:1] == ("sparse-checkout",):
            release.wait(10)
        return real(at, *args, **kw)
    monkeypatch.setattr(repos, "_git", slow)
    monkeypatch.setattr(repos, "SLEEP_WAIT", 0.2)
    monkeypatch.setattr(diagnostics, "record", lambda source, kind, doc=None, **detail: rows.append((source, kind, detail)))
    napping.now[0] += 31 * DAY
    assert repos.sleep_idle() == []                         # it came back without waiting for the clone
    assert [(s, k) for s, k, _ in rows] == [("hub", "clone-sleep-slow")] and rows[0][2]["repo"] == REPO
    assert not repos.sleeping(REPO)
    release.set()
    assert repos.settle()
    assert repos.sleeping(REPO)                             # it finished behind the round, and the next one leaves it alone
    assert repos.sleep_idle() == []


def test_a_clone_put_to_sleep_twice_keeps_the_folders_it_is_to_get_back(napping):
    repos = napping.hub.repos
    napping.now[0] += 31 * DAY
    repos.sleep_idle()
    assert repos.sleeping(REPO)
    repos._sleep_one(REPO, the_clone(napping), [], None)        # a second round finds the set already shrunk
    assert not report(napping, path="docs/plan.md")[0]
    assert sh(the_clone(napping), "sparse-checkout", "list").split() == ["docs", "notes"]


def test_a_folder_widened_after_a_failed_wake_is_kept_by_the_next_sleep(napping):
    repos, clone = napping.hub.repos, the_clone(napping)
    napping.now[0] += 31 * DAY
    repos.sleep_idle()
    assert repos.sleeping(REPO)
    sh(clone, "sparse-checkout", "add", "--", "extra")          # what a report's widen adds while `restore` is still out
    repos._sleep_one(REPO, clone, [], None)
    assert sorted(repos._usage()[REPO]["restore"]) == ["docs", "extra", "notes"]


def test_a_write_widening_a_sleeping_clone_does_not_leave_it_asleep_meanwhile(napping, monkeypatch):
    # `sleep_moved` marks a clone that reads as asleep as moved at once, without its lock: a widen under way must not
    # read so, or the moved clone would keep its folders.
    repos = napping.hub.repos
    napping.now[0] += 31 * DAY
    repos.sleep_idle()
    assert repos.sleeping(REPO)
    real, seen = repos._restore, []

    def restore(*a, **kw):
        seen.append(repos.sleeping(REPO))
        return real(*a, **kw)
    monkeypatch.setattr(repos, "_restore", restore)
    assert repos.wake(REPO) is True
    assert seen == [False] and not repos.sleeping(REPO)