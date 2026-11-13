"""Every hub of a test settles its pusher when the test ends, the `hub` fixture's too (#32, #35): a push left due is
the test's own, never a row in the state of the test that runs next."""
import time

from test_hub_commits import box, edit, remote, rows, sheaves     # noqa: F401  (the fixtures and helpers of the hub's commit tests)

# The second test reads what the first left: a slice of the suite in CI keeps the file whole (SHEAF_TEST_SLICE,
# tests/conftest.py).
IN_ORDER = True


def test_a_test_that_ends_with_a_push_due_leaves_it_to_its_own_teardown(box, sheaves, remote, tmp_path, monkeypatch):
    """First of a pair (the next test reads the log): a failing push still running when the test ends."""
    from sheafmd.hub import commits
    real = commits._git

    def slow_fetch(folder, *args, **kw):
        if args[:1] == ("fetch",):
            time.sleep(0.8)
        return real(folder, *args, **kw)

    monkeypatch.setattr(commits, "_git", slow_fetch)
    remote.rename(tmp_path / "away.git")            # the push will fail
    edit(box, sheaves)                              # no settle: the pusher is in its fetch as the test returns


def test_a_push_a_test_before_left_due_writes_no_row_into_this_one(box):
    """Second of the pair, #32: the hub of the test before is settled at its teardown, so its `push-failed` row is
    in that test's state, not here (CI, PR 250: `(row,) = rows("push-failed")` met a row of an earlier test's hub).
    The wait outlasts the first test's 0.8 s fetch; run apart from it, this passes and proves nothing."""
    time.sleep(1.5)
    assert rows("push-failed") == []
