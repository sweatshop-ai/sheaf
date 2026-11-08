"""Proxy mode as a process (SPEC 9.9 "Switching it on", "Two listeners"; 8.1): a real `python -m
sheafmd hub` whose config.toml holds a `[proxy]` table. What stops the start (exit 1 and a
`proxy-config` row, never a hub that runs with part of the mode), the proxy socket it makes, the
stale one it replaces and the one it removes at a clean stop, and the uid it reads off each
connection. The proxy's account is the test's own, so nobody needs root."""
import json
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
from sheafmd.hub.state import Tokens

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


@pytest.mark.parametrize("member, shown", [("Béa", "Bea"), ("Ｂｅａ", "Bea"), ("Bea", "Béa"), ("Bea", "Ｂｅａ")])
def test_a_member_and_a_token_that_differ_by_accent_or_width_stop_the_start(port, folder, sheaf, member, shown):
    assert sheaf("token", "add", "codex", "--as", shown).code == 0          # no proxy table yet: add takes it
    configure(folder / "hub.sock", {BEA: (member, ["/srv"])})
    assert_refused(port, "MCP token")


def test_a_token_that_signs_the_hubs_persons_name_stops_the_start_and_names_both(port, folder, sheaf):
    assert sheaf("token", "add", "helper", "--as", "ada").code == 0         # loopback: add takes it
    configure(folder / "hub.sock")
    row = assert_refused(port, "'ada'")
    assert "the hub's person" in row["reason"] and "Ada" in row["reason"]


def test_a_hub_with_two_old_tokens_that_share_a_display_starts(port, folder, sheaf):
    assert sheaf("token", "add", "one", "--as", "Codex").code == 0
    assert sheaf("token", "add", "two", "--as", "codex").code == 0
    sock = folder / "hub.sock"
    configure(sock)
    p = run_hub()
    try:
        wait_up(port, sock)
    finally:
        assert stop(p) == 0
    assert hub_rows("proxy-config", "token-names") == []


def test_a_role_word_in_an_agents_built_name_stops_the_start(port, folder, sheaf):
    configure(folder / "hub.sock", {BEA: ("action", ["/srv"])}, extra="")   # a member may be named `action`
    paths.config_file().write_text(paths.config_file().read_text(encoding="utf-8").replace(
        'roots = ["/srv"]', 'roots = ["/srv"]\ntokens = ["bea-chatgpt"]'), encoding="utf-8")
    Tokens().add("bea-chatgpt", client="ChatGPT")                         # made before the member was renamed
    code, err, rows = refused_start()
    assert code == 1 and [r["kind"] for r in rows] == ["token-names"], rows
    assert "ChatGPT (action)" in err and "role" in err


def test_an_agent_clash_is_logged_as_the_tokens_and_does_not_offer_another_member_in_loopback(port):
    Tokens().add("old", "ChatGPT (Ada)")                                      # a typed display, then an agent signs it
    Tokens().add("new", client="ChatGPT")
    code, err, rows = refused_start()
    assert code == 1 and [r["kind"] for r in rows] == ["token-names"], rows
    assert "another client" in err and "member" not in err.replace("(sheaf token list)", "")
    assert wait_until_refused(port, 1)


def test_an_agent_clash_in_proxy_mode_offers_another_member(port, folder):
    Tokens().add("old", "ChatGPT (Ada)")
    Tokens().add("new", client="ChatGPT")
    configure(folder / "hub.sock")
    code, err, rows = refused_start()
    assert code == 1 and [r["kind"] for r in rows] == ["token-names"], rows
    assert "another client or member" in err


def test_an_unknown_key_in_the_config_warns_once_however_many_tokens_there_are(port, folder, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")                                       # the name is then read from the config
    for i in range(3):
        Tokens().add(f"agent-{i}", client=f"Client{i}")
    configure(folder / "hub.sock", {BEA: ("Ada", ["/srv"])}, extra='name = "Ada"\nfrobnicate = 1\n')
    code, err, _ = refused_start()                                         # the member is the person: a start that stops
    assert code == 1 and err.count("unknown key 'frobnicate'") == 1, err


def test_an_unknown_key_in_the_config_warns_once_on_a_hub_that_starts(port, folder, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")                                       # the name is then read from the config
    Tokens().add("agent-0", client="Client0")
    configure(folder / "hub.sock", extra='name = "Ada"\nfrobnicate = 1\n')   # the person is not a member: the hub starts
    p = run_hub()
    try:
        wait_up(port, folder / "hub.sock")
    finally:
        p.send_signal(signal.SIGTERM)
        _, err = p.communicate(timeout=30)
    assert p.returncode == 0 and err.count("unknown key 'frobnicate'") == 1, err


def test_the_messages_name_both_tokens_that_clash_and_the_token_that_signs_the_persons_name(port, folder):
    Tokens().add("old", "ChatGPT (Ada)")
    Tokens().add("new", client="ChatGPT")
    configure(folder / "hub.sock")
    _, err, _ = refused_start()
    assert "'old'" in err and "'new'" in err, err


def test_the_token_set_of_stage_sheaf_agents_hub_2026_11_07_passes_the_start_check(folder, sheaf, work):
    """The members and tokens that tt-tiroir's stage sheaf-agents-hub-2026-11-07 writes on tiroir-tt (files/params.toml,
    lib.sh AGENT_TOKENS): the person `Thierry`, four members, the six live old tokens, and the eight agents made by
    `sheaf token add NAME --client CLIENT --write` once the config is in place. A hub that refuses this is an outage."""
    ids = {"thierry": "503b2f77-83de-452c-817a-a357faf85929", "sven": "f9979e4c-b8f9-4767-b4ba-d094a4b089f3",
           "hans": "0ce2df60-3e1f-4a15-b5a1-41ca61579780", "marina": "8d1a62b6-cf44-45bf-a4c3-9b5eaf263f91"}
    thierry = ["james", "mistral", "tiroir-mail-list", "assistant-thierry", "sheaf-filter-thierry", "starter-thierry",
               "thierry-chatgpt", "thierry-claude", "thierry-tiroir", "thierry-ai"]
    hans = ["hans-chatgpt", "hans-claude", "hans-tiroir", "hans-ai"]
    block = lambda who, name, tokens: (f'\n[proxy.members."{ids[who]}"]\nname = "{name}"\nroots = ["{work}"]\n'
                                       f'short = "{who}"\nshell = false\n'
                                       + (f'tokens = {json.dumps(tokens)}\n' if tokens else ""))
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(
        'name = "Thierry"\n' + proxy_table(folder / "hub.sock", {}) + block("thierry", "Thierry De Marre", thierry)
        + block("sven", "Sven van den Broek", []) + block("hans", "Hans Hermans", hans)
        + block("marina", "Marina Scalafiotti", []), encoding="utf-8")
    for old in thierry[:6]:                                    # the box's rows: a display each, the name by default
        Tokens().add(old, old.capitalize() if old in ("james", "mistral") else None)
    for name, client in [("thierry-chatgpt", "ChatGPT"), ("thierry-claude", "Claude"), ("thierry-tiroir", "tiroir"),
                         ("thierry-ai", "AI"), ("hans-chatgpt", "ChatGPT"), ("hans-claude", "Claude"),
                         ("hans-tiroir", "tiroir"), ("hans-ai", "AI")]:
        assert sheaf("token", "add", name, "--client", client, "--write").code == 0, name
    from sheafmd.hub import proxy
    cfg = proxy.load()
    proxy.check_start_names(cfg, "Thierry", [t for t in Tokens().list() if not t.invalid])
    assert {t.signed("Thierry", cfg) for t in Tokens().list()} >= {"ChatGPT (Thierry De Marre)", "AI (Hans Hermans)"}


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


def test_on_macos_the_uid_is_read_with_local_peercred():
    """macOS has no SO_PEERCRED: the uid comes from LOCAL_PEERCRED, a struct xucred (version, uid, ...)."""
    import struct
    from sheafmd.hub import proxy

    class Conn:
        def getsockopt(self, level, name, size):
            assert (level, name, size) == (0, 1, 76)            # SOL_LOCAL, LOCAL_PEERCRED, sizeof(struct xucred)
            return struct.pack("@IIh16I", 0, 4242, 1, 20, *[0] * 15)
    with pytest.MonkeyPatch.context() as mp:
        mp.delattr(socket, "SO_PEERCRED", raising=False)
        mp.setattr(socket, "LOCAL_PEERCRED", 1, raising=False)
        assert proxy.peer(Conn()).uid == 4242


def test_on_macos_an_xucred_of_another_version_gives_no_uid():
    import struct
    from sheafmd.hub import proxy

    class Conn:
        def getsockopt(self, level, name, size):
            return struct.pack("@IIh16I", 1, 4242, 1, 20, *[0] * 15)
    with pytest.MonkeyPatch.context() as mp:
        mp.delattr(socket, "SO_PEERCRED", raising=False)
        mp.setattr(socket, "LOCAL_PEERCRED", 1, raising=False)
        with pytest.raises(OSError, match="version 1"):
            proxy.peer(Conn())


def test_the_uid_of_a_real_connection_is_this_users():
    from sheafmd.hub import proxy
    a, b = socket.socketpair(socket.AF_UNIX)
    with a, b:
        assert proxy.peer(a).uid == os.getuid()


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
