"""The helpers the hub tests share about a port: when a listener has gone away, and the port a
test is given as its own."""
import fcntl
import os
import socket

import pytest

import helpers
from helpers import wait_until_refused
from sheafmd import config


class Connects:
    """A stand-in for `socket.create_connection` that answers from a script: an exception class
    is raised, anything else is handed back as a socket that records that it was closed."""

    def __init__(self, *script):
        self.script, self.calls, self.closed = list(script), 0, 0

    def __call__(self, address, timeout=None):
        self.calls += 1
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, type) and issubclass(step, BaseException):
            raise step
        return self

    def close(self):
        self.closed += 1


def test_a_refusal_ends_the_wait():
    connect = Connects(ConnectionRefusedError)
    assert wait_until_refused(1, 2, connect=connect) is True
    assert connect.calls == 1


@pytest.mark.parametrize("not_yet", [ConnectionResetError, TimeoutError])
def test_a_reset_or_a_timeout_is_not_a_refusal_so_the_wait_asks_again(not_yet):
    """A connect that lands while a listener closes can be reset, or wait in a full backlog: the
    port is going away, not gone. Only the refusal that follows says it is gone."""
    connect = Connects(not_yet, not_yet, ConnectionRefusedError)
    assert wait_until_refused(1, 2, connect=connect) is True
    assert connect.calls == 3


def test_a_wait_of_no_time_still_asks_once():
    """A process that stalls for the whole of `seconds` before its first connect has not seen a
    listener that stayed: it has not looked."""
    assert wait_until_refused(1, 0, connect=Connects(ConnectionRefusedError)) is True


def test_a_listener_that_never_goes_is_reported_when_the_time_is_up_and_its_connections_are_closed():
    connect = Connects("answered")
    assert wait_until_refused(1, 0.3, connect=connect) is False
    assert connect.calls >= 2 and connect.closed == connect.calls


def test_a_real_listener_is_not_refused_until_it_closes(port):
    """On the test's own port, which no one else is handed: held, it is never refused; closed, it is."""
    s = socket.socket()
    s.bind(("127.0.0.1", port))
    s.listen(1)
    assert wait_until_refused(port, 0.3) is False
    s.close()
    assert wait_until_refused(port, 2) is True


def kernel_hands_out_ports_from(how_many=40) -> int:
    """The lowest port the kernel gives to `how_many` callers of `bind(0)` that all hold theirs:
    asked, not read from a file, so it holds on any platform."""
    held = []
    try:
        for _ in range(how_many):
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            held.append(s)
        return min(s.getsockname()[1] for s in held)
    finally:
        for s in held:
            s.close()


def spare_ports(n: int) -> list[int]:
    """`n` ports of the kind a claim returns, claimed and let go again: below the kernel's pool, so
    nothing is handed them by chance, for a test that needs a port to be taken or free."""
    claims = [helpers.claim_port() for _ in range(n)]
    for _, release in claims:
        release()
    return [port for port, _ in claims]


def test_the_port_of_a_test_is_below_the_ports_the_kernel_hands_out_to_anyone_who_asks(port):
    """A port taken from the kernel's own pool can be given to another process's `bind(0)` in the
    gap between the fixture and the hub that binds it (the hub then answers as a
    stranger, `something else holds 127.0.0.1:<port>`). Below the pool, only a process that asks
    for that very number gets it."""
    assert port < kernel_hands_out_ports_from()
    assert port != config.DEFAULT_PORT, "that is the port of the hub of whoever runs the suite"
    assert os.environ["SHEAF_PORT"] == str(port)


def test_a_claimed_port_is_held_until_it_is_released_and_taken_by_no_other_claim():
    first, release_first = helpers.claim_port()
    (spare,) = spare_ports(1)
    try:
        second, release_second = helpers.claim_port(candidates=[first, first, spare])
        try:
            assert second == spare
        finally:
            release_second()
    finally:
        release_first()
    again, release_again = helpers.claim_port(candidates=[first])
    release_again()
    assert again == first


def test_a_port_that_another_suite_has_claimed_is_passed_over():
    """Another suite's fixture holds a lock on the port's file for as long as its test runs (a lock
    that its process's death releases): this claim takes the next candidate."""
    taken, spare = spare_ports(2)
    taken_by_another = os.open(helpers.port_locks_folder() / str(taken), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(taken_by_another, fcntl.LOCK_EX)
    try:
        got, release = helpers.claim_port(candidates=[taken, spare])
        release()
        assert got == spare
    finally:
        os.close(taken_by_another)


def test_a_port_that_something_listens_on_is_passed_over():
    busy, spare = spare_ports(2)
    holder = socket.socket()
    holder.bind(("127.0.0.1", busy))
    holder.listen(1)
    try:
        got, release = helpers.claim_port(candidates=[busy, spare])
        release()
        assert got == spare
    finally:
        holder.close()


def test_a_claim_with_no_free_candidate_says_so():
    held, release = helpers.claim_port()
    try:
        with pytest.raises(RuntimeError, match="no free port"):
            helpers.claim_port(candidates=[held])
    finally:
        release()


class Draws:
    """A stand-in for `random.SystemRandom` whose `randrange` hands back the numbers given, in
    order, and then the last of them for ever."""

    def __init__(self, *numbers):
        self.numbers = list(numbers)

    def randrange(self, start, stop):
        return self.numbers.pop(0) if len(self.numbers) > 1 else self.numbers[0]


@pytest.mark.parametrize("how", ["named", "drawn"])
def test_a_port_the_browser_refuses_to_open_is_never_handed_out(how, monkeypatch):
    """Chromium will not load a page from 10080 (`net::ERR_UNSAFE_PORT`), so a page test whose
    hub was given it failed whatever the change. It is the only port of Chromium's list in the
    claim's range."""
    (spare,) = spare_ports(1)
    if how == "named":
        got, release = helpers.claim_port(candidates=[10080, spare])
    else:
        monkeypatch.setattr(helpers.random, "SystemRandom", lambda: Draws(10080, spare))
        got, release = helpers.claim_port()
    release()
    assert got == spare


def test_the_ports_beside_the_one_the_browser_refuses_are_still_handed_out():
    """The control: only the refused port is passed over, not its neighbours. Either may be held
    by another claim or have a listener at that moment, but not both."""
    handed = []
    for port in (10079, 10081):
        try:
            got, release = helpers.claim_port(candidates=[port])
        except RuntimeError:                    # held by another claim, or something listens
            continue
        release()
        handed.append(got)
    assert handed and set(handed) <= {10079, 10081}
