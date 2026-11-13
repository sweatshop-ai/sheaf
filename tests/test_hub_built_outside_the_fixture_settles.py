"""A hub built anywhere in a test, not only by the `hub` fixture, has its pusher settled when the test ends (#35):
a push left due is the test's own, never a row in the state of the test that runs next (#32)."""
import os
import time

import pytest

from helpers import BEA, CAL, FRONT, Front, browser_on
from test_hub_commits import edit, remote, rows, sheaves     # noqa: F401  (the fixtures and helpers of the hub's commit tests)

# The second test reads what the first left: a slice of the suite in CI keeps the file whole (SHEAF_TEST_SLICE,
# tests/conftest.py).
IN_ORDER = True


@pytest.fixture
def own_box(sheaves):
    """The box of test_hub_commits, with a hub this fixture builds itself: no `hub` fixture, no settle of its own."""
    import pwd
    from sheafmd import paths
    from sheafmd.hub import proxy
    from sheafmd.hub.core import Hub
    h = Hub(port=int(os.environ["SHEAF_PORT"]), key=paths.ensure_key(), started_by="test")
    h.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                           "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                           "members": {BEA: {"name": "Bea", "email": "bea@example.com", "short": "bea",
                                             "roots": [str(sheaves)]},
                                       CAL: {"name": "Cal", "short": "cal", "roots": [str(sheaves)]}}}, "the test")
    h.roots.for_document(sheaves / "acme" / "blog" / "2026-10-28-plan.md")
    return Front(h, browser_on(h).handler)


def test_a_hub_built_outside_the_fixture_ends_with_a_push_due(own_box, sheaves, remote, tmp_path, monkeypatch):
    """First of a pair (the next test reads the log): a failing push still running when the test ends."""
    from sheafmd.hub import commits
    real = commits._git

    def slow_fetch(folder, *args, **kw):
        if args[:1] == ("fetch",):
            time.sleep(0.8)
        return real(folder, *args, **kw)

    monkeypatch.setattr(commits, "_git", slow_fetch)
    remote.rename(tmp_path / "away.git")            # the push will fail
    edit(own_box, sheaves)                          # no settle: the pusher is in its fetch as the test returns


def test_a_push_of_a_hub_a_test_before_built_itself_writes_no_row_into_this_one(own_box):
    """Second of the pair, #35: the hub of the test before is settled at its teardown, so its `push-failed` row is
    in that test's state, not here. The wait outlasts the first test's 0.8 s fetch; run apart from it, this
    passes and proves nothing."""
    time.sleep(1.5)
    assert rows("push-failed") == []
