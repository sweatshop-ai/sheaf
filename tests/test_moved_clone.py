"""A repo clone whose root moved to another tiroir (ticket 21): it sleeps for good, answers a render report `moved` with the
new origin and does not wake, and a landing from the new tiroir wakes it. `Repos` alone against a local bare repo and a fake
App, and the CLI's two ends of the answer: no hub, no server."""
import dataclasses
import threading

import pytest
from test_repo_pages import REPO, FakeApp, origin, sh  # noqa: F401  (fixtures and helpers)

from sheafmd import send
from sheafmd.hub import repos as repos_mod
from sheafmd.hub.repos import Repos

THERE = "https://there.example"


@pytest.fixture
def repos(tmp_path, origin):  # noqa: F811
    r = Repos(tmp_path / "clones", FakeApp(), remote_url=lambda repo: str(origin))
    r.FETCH_EVERY = 0.0
    r.origin = origin
    return r


def report(repos, path="docs/plan.md", member="bea"):
    commit = sh(repos.origin, "rev-parse", "main")
    got = repos.report(member, REPO, path, commit)
    assert repos.settle(), "the repo's thread did not finish"
    return got


def made(repos):
    assert report(repos)["clone"] == repos_mod.CLONING
    return report(repos)


def test_a_moved_clone_sleeps_and_its_sparse_set_is_narrowed_at_once(repos):
    made(repos)
    clone = repos.clone_dir(REPO)
    assert repos.sleep_moved(REPO, THERE)
    assert repos.sleeping(REPO) and repos.moved_to(REPO) == THERE
    assert sh(clone, "sparse-checkout", "list").split() == []


def test_a_render_report_for_a_moved_repo_answers_moved_with_the_new_origin_and_wakes_nothing(repos):
    made(repos)
    repos.sleep_moved(REPO, THERE)
    clone = repos.clone_dir(REPO)
    seen = []
    real = repos._git
    repos._git = lambda at, *args, **kw: (seen.append(args), real(at, *args, **kw))[1]
    got = report(repos)
    assert got == {"repo": REPO, "path": "docs/plan.md", "clone": repos_mod.MOVED, "moved_to": THERE, "commit_known": None}
    assert seen == [] and repos.sleeping(REPO)                      # no git call, no fetch, no widening
    assert sh(clone, "sparse-checkout", "list").split() == []


def test_a_moved_report_makes_no_record_and_dates_nothing(repos):
    made(repos)
    repos.sleep_moved(REPO, THERE)
    repos.clock = lambda: 9e9
    before = (repos._usage_file.read_text(), repos._records_file.read_text())
    report(repos, path="notes/idea.md", member="cal")
    assert (repos._usage_file.read_text(), repos._records_file.read_text()) == before


def test_sleeping_a_moved_clone_twice_for_the_same_origin_changes_nothing(repos):
    made(repos)
    assert repos.sleep_moved(REPO, THERE)
    before = repos._usage_file.read_text()
    assert repos.sleep_moved(REPO, THERE)
    assert repos._usage_file.read_text() == before


def test_a_repo_with_no_clone_cannot_be_put_to_sleep_as_moved(repos):
    assert not repos.sleep_moved(REPO, THERE)
    assert repos.moved_to(REPO) is None and not repos.sleeping(REPO)


def test_a_moved_clone_survives_a_restart(repos, tmp_path, origin):  # noqa: F811
    made(repos)
    repos.sleep_moved(REPO, THERE)
    again = Repos(tmp_path / "clones", FakeApp(), remote_url=lambda repo: str(origin))
    assert again.moved_to(REPO) == THERE and again.sleeping(REPO)


def test_the_idle_sweep_leaves_a_moved_clone_as_it_is(repos):
    made(repos)
    repos.sleep_moved(REPO, THERE)
    before = repos._usage_file.read_text()
    repos.clock = lambda: 9e9
    assert repos.sleep_idle() == []
    assert repos._usage_file.read_text() == before


def test_moving_back_wakes_the_clone_at_the_next_report_and_it_answers_ok_again(repos):
    made(repos)
    repos.sleep_moved(REPO, THERE)
    assert repos.unmove(REPO)
    assert repos.moved_to(REPO) is None
    got = report(repos)
    assert got["clone"] == repos_mod.OK and got["commit_known"] is True
    assert not repos.sleeping(REPO)
    assert "docs" in sh(repos.clone_dir(REPO), "sparse-checkout", "list").split()    # the folders came back


def test_unmoving_a_repo_that_never_moved_is_refused(repos):
    made(repos)
    assert not repos.unmove(REPO)


# ── the CLI's two ends of the answer ─────────────────────────────────────────

def test_the_cli_knows_the_moved_answer_and_needs_the_new_origin_in_it():
    got = send.parse_report("https://here.example", {"clone": "moved", "moved_to": THERE})
    assert got == send.Report("moved", None, None, THERE)
    for bad in ({"clone": "moved"}, {"clone": "moved", "moved_to": 5}, {"clone": "moved", "moved_to": ""},
                {"clone": "moved", "moved_to": THERE + "\x1b[2J"}, {"clone": "moved", "moved_to": THERE + "\nsheaf: pull this"}):
        with pytest.raises(send.SendError):
            send.parse_report("https://here.example", bad)


def test_a_report_that_is_not_moved_carries_no_new_origin():
    got = send.parse_report("https://here.example", {"clone": "cloning", "moved_to": THERE})
    assert got.moved_to is None


def test_the_moved_line_names_the_new_tiroir_and_the_toml_line(monkeypatch, tmp_path):
    top = tmp_path / "laptop"
    page = top / "docs" / "plan.md"
    page.parent.mkdir(parents=True)
    page.write_text("# Plan\n")
    monkeypatch.setattr(send, "_what_to_report", lambda md, top, err: (REPO, "docs/plan.md", "a" * 40))

    class Door:
        def __init__(self, *a):
            pass

        def tool(self, name, args):
            return False, {"clone": "moved", "moved_to": THERE}

    monkeypatch.setattr(send, "Door", Door)
    monkeypatch.setattr(send, "declared", lambda environ: {})
    out, err = [], []
    args = dataclasses.make_dataclass("A", ["folder", "keep"])(None, False)
    assert send.report_page(page, top, "https://here.example", "tok", args, out.append, err.append, {}) is None
    assert out == [] and len(err) == 1
    assert "there.example" in err[0] and f'tiroir = "{THERE}"' in err[0] and REPO in err[0] and "laptop" in err[0]


# ── refusal: what a report would refuse, with no write (ticket 21 part 2) ────

NEVER = "/nonexistent/private-root"


def test_a_repo_the_app_is_not_installed_on_is_refused_as_no_app_and_nothing_is_written(tmp_path, origin):  # noqa: F811
    r = Repos(tmp_path / "clones", FakeApp(installed=()), remote_url=lambda repo: str(origin))
    assert r.refusal("bea", REPO) == repos_mod.NO_APP
    assert not r._usage_file.exists() and not r._records_file.exists()


def test_a_private_root_is_refused_to_its_own_member_and_not_cloned_to_another(repos):
    assert repos.refusal("bea", REPO, [("bea", NEVER)]) == repos_mod.PRIVATE_ROOT
    assert repos.refusal("cal", REPO, [("bea", NEVER)]) == repos_mod.NOT_CLONED


def test_a_repo_that_would_be_reported_normally_has_no_refusal(repos):
    assert repos.refusal("bea", REPO) is None


def test_a_refusal_changes_no_byte_of_a_moved_clones_state(repos):
    made(repos)
    repos.sleep_moved(REPO, THERE)
    before = (repos._usage_file.read_bytes(), repos._records_file.read_bytes())
    repos.refusal("bea", REPO, [("bea", NEVER)])
    repos.refusal("bea", REPO)
    assert (repos._usage_file.read_bytes(), repos._records_file.read_bytes()) == before


def test_a_root_coming_back_after_an_old_failed_clone_is_not_refused(repos):
    made(repos)
    repos.sleep_moved(REPO, THERE)
    repos._failed[REPO] = "the clone failed"
    assert repos.refusal("bea", REPO) is None
    assert repos._failed[REPO] == "the clone failed"            # nothing popped: the report after the unmove settles it


def test_a_thread_that_cannot_start_leaves_no_queue_and_no_thread_behind(repos, monkeypatch):
    def no_thread(self):
        raise RuntimeError("can't start new thread")
    monkeypatch.setattr(threading.Thread, "start", no_thread)
    with pytest.raises(RuntimeError):
        repos._enqueue(REPO, ("bea", "docs/plan.md", "a" * 40))
    (repos.clone_dir(REPO) / ".git").mkdir(parents=True)
    with pytest.raises(RuntimeError):
        repos.sleep_moved(REPO, THERE)
    assert repos._queues == {} and not repos._threads
