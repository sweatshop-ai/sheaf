"""The sign-in link is redeemed only by the user who runs the hub (SPEC 9.1, 9.3).

The hub reads the row of the connection in /proc/net/tcp and /proc/net/tcp6 and compares its uid
with its own. These tests redirect `peer.PROC_NET` to files of their own, so a uid that is not the
hub's, a row that is missing and a file that cannot be read are all made on purpose; the last
section runs the real thing, over a real socket, with the suite's own uid."""
import http.client
import ipaddress
import os
import sys

import pytest

from helpers import PLAN, hub_rows
from sheafmd import diagnostics, paths
from sheafmd.hub import peer, server
from sheafmd.hub.core import Hub
from sheafmd.hub.handler import Handler

ME = os.geteuid()
THEM = ME + 1
CLIENT = ("127.0.0.1", 50000)
HUB = ("127.0.0.1", 27419)
ACCEPT = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode"
LITTLE_ENDIAN = pytest.mark.skipif(sys.byteorder != "little", reason="the literals are what a little-endian kernel prints")


def hex_addr(ip, port):
    """How the kernel prints an address: each 32-bit word of it in the machine's byte order."""
    packed = ipaddress.ip_address(ip).packed
    words = (int.from_bytes(packed[i:i + 4], sys.byteorder) for i in range(0, len(packed), 4))
    return "".join(f"{w:08X}" for w in words) + f":{port:04X}"


def row(local, remote, uid, state="01"):
    return (f"   0: {hex_addr(*local)} {hex_addr(*remote)} {state} 00000000:00000000 00:00000000 "
            f"00000000 {uid:5d}        0 12345 1 0000000000000000 20 4 30 10 -1")


class FakeProcNet:
    def __init__(self, folder):
        self.folder = folder

    def write(self, v4=(), v6=()):
        (self.folder / "tcp").write_text("\n".join([HEADER, *v4]) + "\n")
        (self.folder / "tcp6").write_text("\n".join([HEADER, *v6]) + "\n")


@pytest.fixture
def proc(tmp_path, monkeypatch):
    """This machine looks like Linux, and /proc/net is a folder of the test's own."""
    folder = tmp_path / "proc-net"
    folder.mkdir()
    monkeypatch.setattr(peer, "PROC_NET", folder)
    monkeypatch.setattr(peer, "PLATFORM", "linux")
    fake = FakeProcNet(folder)
    fake.write()
    return fake


@pytest.fixture
def handler(hub):
    """The handler as the server builds it: the real check of the connection."""
    return Handler(hub)


def conn(client=CLIENT, at_hub=HUB):
    return peer.Conn(client, at_hub)


def follow(handler, hub, connection, accept=ACCEPT, nxt="/work/plan.md", nonce=None):
    """What the browser sends when it follows the link of `sheaf open`: (the answer, the nonce).
    A link made by the hub unless a nonce is given, to follow one a second time."""
    nonce = nonce or hub.auth.mint_signin()
    headers = {"Host": f"127.0.0.1:{hub.port}"}
    if accept:
        headers["Accept"] = accept
    return handler.handle("GET", f"/_/open?nonce={nonce}&next={nxt}", headers, conn=connection), nonce


def refused(r):
    return r.status == 401 and "Set-Cookie" not in r.headers and "Location" not in r.headers


def the_row(uid, client=CLIENT, at_hub=HUB):
    """The row the client's own socket has: its address is the local one."""
    return row(client, at_hub, uid)


def mapped(address):
    """An IPv4 address as an IPv6 socket holds it."""
    return "::ffff:" + address[0], address[1]


def the_row_in(table, uid):
    """The row of the connection in `tcp` (as an IPv4 socket has it) or in `tcp6` (as an IPv6 socket does)."""
    return {"v4": [the_row(uid)]} if table == "tcp" else {"v6": [row(mapped(CLIENT), mapped(HUB), uid)]}


# ── the user of the connection is the hub's ──────────────────────────────────

def test_a_link_followed_by_the_hubs_own_user_signs_the_browser_in(handler, hub, proc):
    proc.write(v4=[the_row(ME)])
    r, _ = follow(handler, hub, conn())
    assert r.status == 303 and r.headers["Location"] == "/work/plan.md" and "Set-Cookie" in r.headers


def test_a_link_followed_by_another_user_signs_no_one_in(handler, hub, proc):
    proc.write(v4=[the_row(THEM)])
    r, nonce = follow(handler, hub, conn())
    assert refused(r)
    assert r.headers["Content-Type"].startswith("text/html") and not r.text.lstrip().startswith("{")
    assert "another user" in r.text and "sheaf open" in r.text
    assert nonce not in r.text and hub.auth.key not in r.text


def test_a_link_another_user_followed_is_spent_for_the_person_too(handler, hub, proc):
    proc.write(v4=[the_row(THEM)])
    r, nonce = follow(handler, hub, conn())
    assert refused(r)
    proc.write(v4=[the_row(ME)])
    again, _ = follow(handler, hub, conn(), accept=None, nonce=nonce)
    assert refused(again)


def test_a_caller_that_asked_for_json_gets_the_json_refusal_of_a_link_another_user_followed(handler, hub, proc):
    proc.write(v4=[the_row(THEM)])
    r, _ = follow(handler, hub, conn(), accept="application/json")
    assert refused(r) and r.json()["ok"] is False and "another user" in r.json()["error"]
    assert "uid" not in r.json()["error"] and not any(c.isdigit() for c in r.json()["error"])
    assert f"uid {THEM}" in hub_rows("open-401")[-1]["error"]          # the row holds what the answer does not


def test_a_refusal_that_could_not_tell_the_user_keeps_the_why_for_the_row_and_out_of_the_answer(handler, hub, proc):
    proc.write()
    r, _ = follow(handler, hub, conn(), accept="application/json")
    assert refused(r) and "/proc" not in r.json()["error"] and "tcp" not in r.json()["error"]
    assert "/proc/net/tcp" in hub_rows("open-401")[-1]["error"]


def test_the_row_of_the_clients_end_decides_not_the_row_of_the_hubs_end(handler, hub, proc):
    # The hub's accepted socket is the same connection seen from the other side: its local
    # address is the hub's port and its owner is the hub. Reading that row would pass every caller.
    proc.write(v4=[row(HUB, CLIENT, ME), the_row(THEM)])
    r, _ = follow(handler, hub, conn())
    assert refused(r)


def test_only_the_row_of_the_hubs_end_is_no_row_of_the_client(handler, hub, proc):
    proc.write(v4=[row(HUB, CLIENT, ME)])
    r, _ = follow(handler, hub, conn())
    assert refused(r) and "could not tell which user" in r.text


def test_another_connection_of_the_same_user_does_not_count(handler, hub, proc):
    proc.write(v4=[the_row(ME, client=("127.0.0.1", 50001)), the_row(ME, at_hub=("127.0.0.1", 9))])
    r, _ = follow(handler, hub, conn())
    assert refused(r)


@pytest.mark.parametrize("first,second", [(ME, THEM), (THEM, ME)])
def test_two_rows_for_one_connection_that_name_two_users_refuse_whichever_comes_first(handler, hub, proc, first, second):
    proc.write(v4=[the_row(first), the_row(second)])
    r, _ = follow(handler, hub, conn())
    assert refused(r)


def test_two_rows_for_one_connection_that_name_one_user_are_that_user(handler, hub, proc):
    proc.write(v4=[the_row(ME), the_row(ME)])
    r, _ = follow(handler, hub, conn())
    assert r.status == 303


# ── IPv4 and IPv6 ────────────────────────────────────────────────────────────

def test_a_browser_on_an_ipv6_socket_to_the_ipv4_address_is_found_in_tcp6(handler, hub, proc):
    proc.write(v6=[row(mapped(CLIENT), mapped(HUB), ME)])
    assert follow(handler, hub, conn())[0].status == 303
    proc.write(v6=[row(mapped(CLIENT), mapped(HUB), THEM)])
    assert refused(follow(handler, hub, conn())[0])


def test_a_connection_over_the_ipv6_loopback_is_found_in_tcp6(handler, hub, proc):
    c6, s6 = ("::1", 50000), ("::1", 27419)
    proc.write(v6=[row(c6, s6, ME)])
    assert follow(handler, hub, conn(c6, s6))[0].status == 303
    proc.write(v6=[row(c6, s6, THEM)])
    assert refused(follow(handler, hub, conn(c6, s6))[0])


def test_a_machine_with_ipv6_off_has_no_tcp6_and_the_ipv4_row_still_counts(handler, hub, proc):
    proc.write(v4=[the_row(ME)])
    (proc.folder / "tcp6").unlink()
    assert follow(handler, hub, conn())[0].status == 303


@LITTLE_ENDIAN
def test_a_line_as_a_linux_kernel_prints_it_is_read(handler, hub, proc):
    # 127.0.0.1:50000 to 127.0.0.1:27419, owner uid 7001, copied from the shape of a real /proc/net/tcp
    line = ("   3: 0100007F:C350 0100007F:6B1B 01 00000000:00000000 00:00000000 00000000  7001"
            "        0 55555 1 0000000000000000 20 4 30 10 -1")
    proc.write(v4=[line])
    r, _ = follow(handler, hub, conn())
    assert refused(r)
    said = hub_rows("open-401")[-1]["error"]
    assert "7001" in said and str(ME) in said


@LITTLE_ENDIAN
def test_the_loopback_of_ipv6_and_an_ipv4_in_it_are_read_as_the_kernel_prints_them(handler, hub, proc):
    mapped = "0000000000000000FFFF00000100007F"
    loopback6 = "00000000000000000000000001000000"
    tail = "01 00000000:00000000 00:00000000 00000000  {uid}        0 1 1 0000000000000000 20 4 30 10 -1"
    proc.write(v6=[f"   0: {mapped}:C350 {mapped}:6B1B " + tail.format(uid=ME)])
    assert follow(handler, hub, conn())[0].status == 303
    proc.write(v6=[f"   0: {loopback6}:C350 {loopback6}:6B1B " + tail.format(uid=ME)])
    assert follow(handler, hub, conn(("::1", 50000), ("::1", 27419)))[0].status == 303


# ── fail closed ──────────────────────────────────────────────────────────────

def test_a_row_that_is_not_there_refuses_with_the_page_that_says_to_run_sheaf_open_again(handler, hub, proc):
    proc.write()
    r, nonce = follow(handler, hub, conn())
    assert refused(r) and r.headers["Content-Type"].startswith("text/html")
    assert "could not tell which user" in r.text and "sheaf open" in r.text
    assert not r.text.lstrip().startswith("{") and nonce not in r.text


def test_a_row_that_is_not_there_spends_the_link(handler, hub, proc):
    proc.write()
    r, nonce = follow(handler, hub, conn())
    assert refused(r)
    proc.write(v4=[the_row(ME)])
    again, _ = follow(handler, hub, conn(), accept=None, nonce=nonce)
    assert refused(again)


# The row is in one file and the other cannot be read: code that skipped an unreadable file would find
# the row and sign the browser in, so these refuse for the right reason only.
@pytest.mark.parametrize("holds,unreadable", [("tcp", "tcp6"), ("tcp6", "tcp")])
def test_a_file_that_cannot_be_read_refuses_though_the_other_one_holds_the_row(handler, hub, proc, holds, unreadable):
    proc.write(**the_row_in(holds, ME))
    (proc.folder / unreadable).unlink()
    (proc.folder / unreadable).mkdir()                 # reading a folder is an OSError, as a denied file is
    r, _ = follow(handler, hub, conn())
    assert refused(r) and "could not tell which user" in r.text
    assert "could not be read" in hub_rows("open-401")[-1]["error"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
@pytest.mark.parametrize("holds,unreadable", [("tcp", "tcp6"), ("tcp6", "tcp")])
def test_a_file_with_no_read_permission_refuses_though_the_other_one_holds_the_row(handler, hub, proc, holds, unreadable):
    proc.write(**the_row_in(holds, ME))
    (proc.folder / unreadable).chmod(0)                # the PermissionError a denied /proc file raises
    r, _ = follow(handler, hub, conn())
    assert refused(r) and "Permission denied" in hub_rows("open-401")[-1]["error"]


def test_no_tcp_file_on_linux_refuses(handler, hub, proc):
    (proc.folder / "tcp").unlink()
    (proc.folder / "tcp6").unlink()
    assert refused(follow(handler, hub, conn())[0])


def test_a_line_that_is_not_a_row_refuses_and_does_not_crash(handler, hub, proc):
    proc.write(v4=["this is not a row", "   1: ZZZZ:ZZ 0100007F:6B1B 01", the_row(ME)[:30]])
    assert refused(follow(handler, hub, conn())[0])


def test_a_request_with_no_connection_to_look_up_refuses(handler, hub, proc):
    proc.write(v4=[the_row(ME)])
    r, _ = follow(handler, hub, None)
    assert refused(r)


def test_the_row_of_a_link_that_was_refused_for_its_peer_says_who_and_holds_no_nonce(handler, hub, proc):
    proc.write(v4=[the_row(THEM)])
    r, nonce = follow(handler, hub, conn())
    assert refused(r)
    rows = hub_rows("open-401")
    assert rows and f"uid {THEM}" in rows[-1]["error"] and f"uid {ME}" in rows[-1]["error"]
    assert nonce not in str(diagnostics.read())
    proc.write()
    follow(handler, hub, conn())
    assert "could not be found" in hub_rows("open-401")[-1]["error"]


# ── what the check leaves alone ──────────────────────────────────────────────

def test_a_bad_nonce_from_the_hubs_own_user_is_still_the_link_that_does_not_work(handler, hub, proc):
    proc.write(v4=[the_row(ME)])
    r, _ = follow(handler, hub, conn(), nonce="x" * 43)
    assert refused(r) and "used already" in r.text and "another user" not in r.text


def test_the_key_link_of_signin_url_is_not_a_connection_check(handler, hub, proc):
    # `sheaf signin-url` is opened by hand, on any machine; the key is what proves the person (9.3).
    r = handler.handle("GET", f"/_/open?key={hub.auth.key}&next=/work/plan.md",
                       {"Host": f"127.0.0.1:{hub.port}"}, conn=conn())
    assert r.status == 303 and "Set-Cookie" in r.headers
    r = handler.handle("GET", f"/_/open?key={hub.auth.key}&next=/work/plan.md",
                       {"Host": f"127.0.0.1:{hub.port}"}, conn=None)
    assert r.status == 303


def test_a_cookie_route_does_not_look_up_the_connection_yet(handler, hub, proc, work):
    # The same check on every cookie and key request is not made yet.
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    hub.roots.for_document(f)
    other_user = [the_row(THEM)]
    proc.write(v4=other_user)
    cookie = f"{hub.auth.cookie_name}={hub.auth.cookie_value()}"
    r = handler.handle("GET", "/work/plan.md", {"Host": f"127.0.0.1:{hub.port}", "Cookie": cookie}, conn=conn())
    assert r.status == 200


# ── a platform with no /proc/net ─────────────────────────────────────────────

@pytest.fixture
def mac(tmp_path, monkeypatch):
    monkeypatch.setattr(peer, "PLATFORM", "darwin")
    monkeypatch.setattr(peer, "PROC_NET", tmp_path / "no-such-folder")


def test_where_there_is_no_proc_net_the_link_signs_in_as_it_did_before(handler, hub, mac):
    r, _ = follow(handler, hub, conn())
    assert r.status == 303 and "Set-Cookie" in r.headers
    assert follow(handler, hub, None)[0].status == 303


def test_where_there_is_no_proc_net_a_link_that_does_not_work_says_the_hub_cannot_check_the_user(handler, hub, mac):
    r, nonce = follow(handler, hub, conn())
    assert r.status == 303
    again, _ = follow(handler, hub, conn(), nonce=nonce)
    assert refused(again)
    assert "cannot check which user" in again.text and "sheaf rotate" in again.text


def test_on_linux_the_page_of_a_link_that_does_not_work_does_not_say_the_hub_cannot_check(handler, hub, proc):
    proc.write(v4=[the_row(ME)])
    r, nonce = follow(handler, hub, conn())
    assert r.status == 303
    again, _ = follow(handler, hub, conn(), nonce=nonce)
    assert refused(again) and "cannot check which user" not in again.text


# ── over a real socket ───────────────────────────────────────────────────────

@pytest.fixture
def live(work):
    """A running hub on a free port of its own, and a way to connect to it."""
    sock = server.bind(0)
    port = sock.getsockname()[1]
    hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    hub.roots.for_document(f)
    conns = []

    def connect():
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.connect()
        conns.append(c)
        return c
    yield hub, port, connect
    for c in conns:
        c.close()
    srv.close()


def sign_in_over(c, hub):
    nonce = hub.auth.mint_signin()
    c.request("GET", f"/_/open?nonce={nonce}&next=/work/plan.md", headers={"Accept": ACCEPT})
    r = c.getresponse()
    return r, r.read()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="v1 reads /proc/net, which is Linux")
def test_the_user_that_runs_the_hub_signs_in_over_a_real_socket_by_the_real_proc_net(live):
    hub, port, connect = live
    r, _ = sign_in_over(connect(), hub)
    assert r.status == 303 and r.getheader("Location") == "/work/plan.md"
    assert r.getheader("Set-Cookie").startswith(f"sheaf_{port}=")


def test_the_server_hands_the_handler_the_address_of_the_connection_it_came_in_on(live, proc):
    hub, port, connect = live
    c = connect()
    mine, theirs = c.sock.getsockname(), c.sock.getpeername()
    proc.write(v4=[row(mine[:2], theirs[:2], ME)])
    r, _ = sign_in_over(c, hub)
    assert r.status == 303


def test_over_a_real_socket_a_row_with_another_uid_refuses_and_a_row_of_the_hubs_end_does_not_help(live, proc):
    hub, port, connect = live
    c = connect()
    mine, theirs = c.sock.getsockname()[:2], c.sock.getpeername()[:2]
    proc.write(v4=[row(mine, theirs, THEM), row(theirs, mine, ME)])
    r, body = sign_in_over(c, hub)
    assert r.status == 401 and r.getheader("Content-Type").startswith("text/html")
    assert r.getheader("Set-Cookie") is None and b"another user" in body
