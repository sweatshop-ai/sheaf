"""Proxy mode as a process (SPEC 9.9 "Switching it on", "Two listeners"; 8.1): a real `python -m
sheafmd hub` whose config.toml holds a `[proxy]` table. What stops the start (exit 1 and a
`proxy-config` row, never a hub that runs with part of the mode), the proxy socket it makes, the
stale one it replaces and the one it removes at a clean stop, and the uid it reads off each
connection. The proxy's account is the test's own, so nobody needs root."""
import os
import pwd
import signal
import socket
import stat
import subprocess
import sys
import time

import pytest
from helpers import UnixHTTP, hub_rows, proxy_table, wait_until_refused

from sheafmd import paths
from sheafmd.hub import server

ME = pwd.getpwuid(os.getuid()).pw_name
BEA = "0f8fad5b-d9cb-469f-a165-70867728950e"
HOST = "chat.example.com"


@pytest.fixture
def folder(proxy_folder):
    return proxy_folder


def configure(sock, members=None, extra=""):
    p = paths.config_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(extra + proxy_table(sock, members or {BEA: ("Bea", ["/srv/pages"])}), encoding="utf-8")


def run_hub():
    return subprocess.Popen([sys.executable, "-m", "sheafmd", "hub", "--started-by", "cli"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def refused_start():
    """A hub that must not start: its exit code, what it said and the rows it wrote."""
    p = run_hub()
    _, err = p.communicate(timeout=60)
    return p.returncode, err, hub_rows()


def wait_up(port, sock):
    for _ in range(400):
        info = server.read_pid_file()
        if info and hub_rows("hub-start") and os.path.exists(sock):
            return
        time.sleep(0.05)
    pytest.fail("the hub did not start")


def ask(sock, path="/_/doc?doc=x", headers=None):
    c = UnixHTTP(sock)
    try:
        c.request("GET", path, headers={"Host": HOST, **(headers or {})})
        r = c.getresponse()
        return r.status, r.read()
    finally:
        c.close()


def stop(p):
    p.send_signal(signal.SIGTERM)
    return p.wait(timeout=30)


# ── what stops the start ─────────────────────────────────────────────────────

def assert_refused(port, words):
    code, err, rows = refused_start()
    assert code == 1
    assert [r["kind"] for r in rows] == ["proxy-config"], rows
    assert words in rows[0]["reason"] and words in err
    assert wait_until_refused(port, 1)               # the port is let go, or was never held
    return rows[0]


def test_a_table_with_a_missing_key_stops_the_start(port, folder):
    p = paths.config_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f'[proxy]\norigin = "https://{HOST}"\nproxy_user = "{ME}"\n'
                 f'[proxy.members."{BEA}"]\nname = "Bea"\nroots = ["/srv"]\n', encoding="utf-8")
    assert_refused(port, "'socket' is missing")


def test_a_socket_folder_that_is_not_there_stops_the_start(port, folder):
    configure(folder / "no" / "hub.sock")
    assert_refused(port, "does not exist")


@pytest.mark.parametrize("mode", [0o750, 0o2770, 0o2755, 0o2751])
def test_a_socket_folder_of_another_mode_than_2750_stops_the_start(port, folder, mode):
    os.chmod(folder, mode)
    configure(folder / "hub.sock")
    assert_refused(port, "2750")


def test_a_socket_folder_that_is_a_link_stops_the_start(port, folder):
    link = folder.parent / "l"
    link.symlink_to(folder)
    configure(link / "hub.sock")
    assert_refused(port, "not a folder")


def test_a_member_named_as_the_hubs_person_stops_the_start(port, folder):
    configure(folder / "hub.sock", {BEA: ("ada", ["/srv"])})           # SHEAF_NAME is Ada
    assert_refused(port, "the hub's person's")


def test_a_member_named_as_a_token_stops_the_start(port, folder, sheaf):
    assert sheaf("token", "add", "codex", "--as", "Quill").code == 0
    configure(folder / "hub.sock", {BEA: ("Quill", ["/srv"])})
    assert_refused(port, "MCP token")


def test_a_proxy_socket_something_listens_on_stops_the_start(port, folder):
    configure(folder / "hub.sock")
    other = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    other.bind(str(folder / "hub.sock"))
    other.listen(1)
    try:
        assert_refused(port, "something listens")
        assert stat.S_ISSOCK(os.lstat(folder / "hub.sock").st_mode)      # the other one's, left alone
        assert not server.read_pid_file()
    finally:
        other.close()


def test_a_file_that_is_no_socket_where_the_socket_goes_stops_the_start_and_stays(port, folder):
    configure(folder / "hub.sock")
    (folder / "hub.sock").write_text("mine")
    assert_refused(port, "not a socket")
    assert (folder / "hub.sock").read_text() == "mine"


# ── the socket of a hub that starts ──────────────────────────────────────────

def test_the_proxy_socket_is_made_0660_in_its_folder_and_removed_at_a_clean_stop(port, folder):
    sock = folder / "hub.sock"
    configure(sock)
    p = run_hub()
    try:
        wait_up(port, sock)
        st = os.lstat(sock)
        assert stat.S_ISSOCK(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o660
        assert st.st_uid == os.getuid() and st.st_gid == pwd.getpwuid(os.getuid()).pw_gid
        assert ask(sock, "/_/health", {"X-Sheaf-Member": BEA})[0] == 404     # it answers, by 9.9
    finally:
        assert stop(p) == 0
    assert not sock.exists()


def test_a_socket_file_nothing_listens_on_is_replaced(port, folder):
    sock = folder / "hub.sock"
    configure(sock)
    dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    dead.bind(str(sock))
    dead.close()                                         # the file stays, as after kill -9
    p = run_hub()
    try:
        wait_up(port, sock)
        assert ask(sock, "/_/health", {"X-Sheaf-Member": BEA})[0] == 404
    finally:
        assert stop(p) == 0
    assert hub_rows("proxy-config") == []


def test_the_uid_of_each_connection_is_read_off_the_connection(port, folder, work):
    """The test runs as `proxy_user`, so its connection is the proxy's: it is served (a 401 for
    want of a member header, not the 403 of another account)."""
    sock = folder / "hub.sock"
    configure(sock)
    p = run_hub()
    try:
        wait_up(port, sock)
        assert ask(sock, "/")[0] == 401
        assert hub_rows("proxy-peer") == []
    finally:
        stop(p)


def test_without_the_table_the_hub_makes_no_proxy_socket(port, folder):
    p = run_hub()
    try:
        for _ in range(400):
            if hub_rows("hub-start"):
                break
            time.sleep(0.05)
        assert list(folder.iterdir()) == []
    finally:
        assert stop(p) == 0


def test_a_socket_folder_of_another_group_or_owner_is_refused(folder):
    """Another group or owner needs root to set up, so these two are checked on the function."""
    import dataclasses
    from sheafmd.hub import proxy
    cfg = proxy.parse({"origin": f"https://{HOST}", "socket": str(folder / "hub.sock"), "proxy_user": ME,
                       "members": {BEA: {"name": "Bea", "roots": ["/srv"]}}}, "the test")
    proxy.check_folder(cfg)                                              # as the deployment makes it
    with pytest.raises(proxy.ProxyError, match="has group"):
        proxy.check_folder(dataclasses.replace(cfg, gid=cfg.gid + 1))
    real = os.getuid
    try:
        os.getuid = lambda: real() + 1
        with pytest.raises(proxy.ProxyError, match="belongs to uid"):
            proxy.check_folder(cfg)
    finally:
        os.getuid = real
