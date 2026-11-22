"""Who owns a connection: the kernel's socket diagnostics first, /proc/net/tcp* when it cannot answer.

`peer.owners` asks the kernel over AF_NETLINK (sock_diag) for the one socket whose local end is the
client's and whose remote end is the hub's. These tests run it over real loopback sockets, and make the
two ways of failing on purpose: the netlink socket that cannot be had, and a machine that tells the
hub's own uid nothing."""
import os
import socket
import struct
import sys
import time

import pytest

from sheafmd.hub import peer

ME = os.geteuid()
linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="sock_diag and /proc/net are Linux")


def pair(host="127.0.0.1", family=socket.AF_INET):
    """A connected loopback pair; the client's end first. Closed by the test through `ends`."""
    srv = socket.socket(family, socket.SOCK_STREAM)
    srv.bind((host, 0))
    srv.listen(1)
    cli = socket.socket(family, socket.SOCK_STREAM)
    cli.connect(srv.getsockname())
    acc, _ = srv.accept()
    srv.close()
    return cli, acc


@pytest.fixture
def ends():
    held = []
    yield held
    for s in held:
        s.close()


def conn_of(cli):
    return peer.Conn(cli.getsockname()[:2], cli.getpeername()[:2])


@linux
def test_the_kernel_names_the_owner_of_the_clients_end_of_an_ipv4_connection(ends):
    cli, acc = pair()
    ends += [cli, acc]
    assert peer.owners(conn_of(cli)) == [ME]


@linux
def test_the_kernel_names_the_owner_of_an_ipv6_connection(ends):
    try:
        cli, acc = pair("::1", socket.AF_INET6)
    except OSError:
        pytest.skip("no IPv6 loopback here")
    ends += [cli, acc]
    assert peer.owners(conn_of(cli)) == [ME]


@linux
def test_a_connection_that_is_not_there_has_no_owner(ends):
    cli, acc = pair()
    ends += [cli, acc]
    c = conn_of(cli)
    gone = peer.Conn(("127.0.0.1", c.client[1] ^ 1), c.hub)
    assert peer.owners(gone) == []


@linux
def test_the_netlink_answer_and_the_proc_answer_are_the_same(ends, monkeypatch):
    cli, acc = pair()
    ends += [cli, acc]
    c = conn_of(cli)
    by_netlink = peer.owners(c)
    monkeypatch.setattr(peer, "NETLINK", False)
    assert peer.owners(c) == by_netlink == [ME]


@linux
def test_a_kernel_that_will_not_answer_over_netlink_is_asked_in_proc(ends, monkeypatch):
    cli, acc = pair()
    ends += [cli, acc]

    def refuse(*a, **k):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(peer, "_netlink_owners", refuse)
    assert peer.owners(conn_of(cli)) == [ME]


@linux
def test_a_netlink_answer_that_is_cut_short_is_asked_in_proc(ends, monkeypatch):
    cli, acc = pair()
    ends += [cli, acc]

    def cut(*a, **k):
        raise struct.error("unpack requires a buffer of 4 bytes")
    monkeypatch.setattr(peer, "_netlink_owners", cut)
    assert peer.owners(conn_of(cli)) == [ME]


@linux
def test_a_kernel_that_finds_nothing_over_netlink_is_asked_again_in_proc(ends, monkeypatch):
    """The kernel's "no such socket" is also what a host with no tcp_diag handler answers."""
    cli, acc = pair()
    ends += [cli, acc]
    monkeypatch.setattr(peer, "_netlink_owners", lambda local, remote: [])
    assert peer.owners(conn_of(cli)) == [ME]


def wait_closed(acc):
    for _ in range(200):
        if peer.closed(acc):
            return
        time.sleep(0.01)


@linux
@pytest.mark.parametrize("netlink", [True, False])
def test_a_caller_that_closed_its_socket_is_held_by_no_one_and_is_not_let_through(ends, monkeypatch, netlink):
    monkeypatch.setattr(peer, "NETLINK", netlink)
    cli, acc = pair()
    ends.append(acc)
    c = conn_of(cli)
    cli.close()
    wait_closed(acc)
    found = peer.sockets(c)
    assert found and all(inode == 0 for _, inode in found)
    no = peer.check(c)
    assert no is not None and no.kind == peer.UNKNOWN


@linux
def test_a_caller_that_only_half_closed_is_still_its_owners(ends):
    cli, acc = pair()
    ends += [cli, acc]
    cli.shutdown(socket.SHUT_WR)
    wait_closed(acc)
    assert [uid for uid, inode in peer.sockets(conn_of(cli)) if inode] == [ME]
    assert peer.check(conn_of(cli)) is None


@pytest.mark.skipif(ME == 0, reason="root is the hub's own user here")
def test_root_is_not_the_hubs_own_user(monkeypatch):
    monkeypatch.setattr(peer, "PLATFORM", "linux")
    monkeypatch.setattr(peer, "sockets", lambda conn: [peer.Socket(0, 4242)])
    no = peer.check(peer.Conn(("127.0.0.1", 50000), ("127.0.0.1", 27419)))
    assert no is not None and no.kind == peer.OTHER_USER


def test_the_self_test_passes_where_the_hub_can_read_its_own_connection():
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux only")
    assert peer.selftest() is None


@pytest.mark.parametrize("answer", [[], [ME + 1], [ME, ME + 1]])
def test_the_self_test_says_why_when_the_owner_read_is_not_the_hubs_own(answer, monkeypatch):
    monkeypatch.setattr(peer, "PLATFORM", "linux")
    monkeypatch.setattr(peer, "owners", lambda conn: answer)
    why = peer.selftest()
    assert why and "owner" in why


def test_the_self_test_says_why_when_the_lookup_raises(monkeypatch):
    monkeypatch.setattr(peer, "PLATFORM", "linux")

    def broken(conn):
        raise OSError(13, "Permission denied")
    monkeypatch.setattr(peer, "owners", broken)
    assert "Permission denied" in peer.selftest()


def test_the_self_test_has_nothing_to_say_where_the_platform_is_not_checked(monkeypatch):
    monkeypatch.setattr(peer, "PLATFORM", "darwin")
    assert peer.selftest() is None
