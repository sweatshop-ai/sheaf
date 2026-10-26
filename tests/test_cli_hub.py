"""`sheaf open`, `start`, `stop`, `status` and `hub`, against a real hub process (SPEC 8.4, 9.4, 13).

The routes are tested in memory elsewhere; these run the whole path: the command finds no hub and
starts one, asks it who it is before it sends the key anywhere, signs the browser in, and prints
only the clean URL."""
import http.client
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from agent_fakes import PID, FakeClaude, write_record
from helpers import PLAN, Impostor, Silent, gone, http_get, hub_alive, hub_rows, key, silent_message
from sheafmd import diagnostics, paths
from sheafmd.hub import client as hubclient
from sheafmd.hub import server

TIP = "tip: sheaf service install keeps the hub running across reboots"
NONCE_URL = re.compile(r"http://127\.0\.0\.1:PORT/_/open\?nonce=[A-Za-z0-9_-]{43}&next=/work/plan\.md")


@pytest.fixture
def doc(work):
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    return f


# ── sheaf open ───────────────────────────────────────────────────────────────

def test_open_starts_a_hub_signs_the_browser_in_and_prints_only_the_clean_url(sheaf, opened_browser, doc, port):
    r = sheaf("open", doc)
    assert r.code == 0, r.err
    url = f"http://127.0.0.1:{port}/work/plan.md"
    lines = r.out.splitlines()
    assert lines[0] == f"  {TIP}" and lines[-1] == f"  ~ {url}"
    assert all(line.startswith("  +") for line in lines[1:-1])          # the render log, as always
    assert key() not in r.out + r.err and "key=" not in r.out + r.err
    assert [u.split("?")[0] for u in opened_browser.opened] == [f"http://127.0.0.1:{port}/_/open"]
    sign_in = opened_browser.opened[0]
    assert NONCE_URL.fullmatch(sign_in.replace(str(port), "PORT", 1)), sign_in
    assert key() not in sign_in and "key=" not in sign_in           # the launcher's argv never holds the key (9.3)
    path = sign_in.split(str(port), 1)[1]
    resp, _ = http_get(port, path)
    assert resp.status == 303 and resp.getheader("Location") == "/work/plan.md"
    jar = resp.getheader("Set-Cookie").split(";")[0]
    resp, body = http_get(port, "/work/plan.md", {"Cookie": jar})
    assert resp.status == 200 and b"about apples" in body and key().encode() not in body
    again, _ = http_get(port, path)                                  # one use: the link is spent
    assert again.status == 401 and again.getheader("Set-Cookie") is None


def test_the_hub_keeps_running_after_the_command_ends(sheaf, opened_browser, doc, port):
    sheaf("open", doc)
    info = server.read_pid_file()
    assert info["port"] == port and info["service"] is False
    os.kill(info["pid"], 0)
    assert hub_alive(port)


def test_a_bare_file_is_opened(sheaf, opened_browser, doc, port):
    r = sheaf(doc)
    assert r.code == 0 and f"  ~ http://127.0.0.1:{port}/work/plan.md" in r.out
    assert len(opened_browser.opened) == 1


def test_the_tip_comes_once_and_a_second_open_uses_the_same_hub(sheaf, opened_browser, doc, port):
    sheaf("open", doc)
    boot = server.read_pid_file()["boot"]
    assert (paths.state_dir() / "service-hint-shown").exists()
    r = sheaf("open", doc)
    assert r.code == 0 and TIP not in r.out
    assert server.read_pid_file()["boot"] == boot and len(opened_browser.opened) == 2


def test_a_document_already_open_in_a_tab_is_not_opened_again(sheaf, opened_browser, doc, port):
    sheaf("open", doc)
    resp, _ = http_get(port, opened_browser.opened[0].split(str(port), 1)[1])
    jar = resp.getheader("Set-Cookie").split(";")[0]
    tab = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    tab.request("GET", "/_/live?doc=work/plan.md", headers={"Cookie": jar})
    stream = tab.getresponse()
    stream.fp.readline()
    r = sheaf("open", doc)
    assert r.out.splitlines()[-2:] == ["  (already open in 1 tab)",
                                       f"  ~ http://127.0.0.1:{port}/work/plan.md"]
    assert len(opened_browser.opened) == 1
    stream.close()
    tab.close()


@pytest.mark.parametrize("how", ["flag", "env", "config"])
def test_a_browser_that_is_off_is_not_opened_and_the_url_is_still_printed(sheaf, opened_browser, doc, port,
                                                                          monkeypatch, how):
    args = ["--no-browser"] if how == "flag" else []
    if how == "env":
        monkeypatch.setenv("SHEAF_NO_BROWSER", "1")
    if how == "config":
        f = paths.config_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("browser = false\n")
    r = sheaf("open", doc, *args)
    assert r.code == 0 and opened_browser.opened == []
    assert f"  ~ http://127.0.0.1:{port}/work/plan.md" in r.out


def test_a_browser_that_cannot_be_started_says_so_and_still_exits_0(sheaf, opened_browser, doc, port):
    opened_browser.result = False
    r = sheaf("open", doc)
    assert r.code == 0 and "no browser could be opened" in r.err
    assert key() not in r.out + r.err


def test_the_render_options_reach_the_page(sheaf, opened_browser, doc, port):
    r = sheaf("open", doc, "--title", "My plan", "--toc", "never", "--by", "Grace",
              "--max-image-width", "800")
    assert r.code == 0
    resp, _ = http_get(port, opened_browser.opened[0].split(str(port), 1)[1])
    jar = resp.getheader("Set-Cookie").split(";")[0]
    _, body = http_get(port, "/work/plan.md", {"Cookie": jar})
    assert b"<title>My plan</title>" in body
    saved = json.loads((paths.state_dir() / "docs.json").read_text())["work/plan.md"]
    assert (saved["title"], saved["toc"], saved["by"], saved["max_image_width"]) == \
        ("My plan", "never", "Grace", 800)


def test_the_for_option_reaches_the_page_and_the_saved_settings(sheaf, opened_browser, work, doc, port):
    (work / ".sheaf.toml").write_text('for = "Acme"\n', encoding="utf-8")
    r = sheaf("open", doc, "--by", "Grace", "--for", "Globex")
    assert r.code == 0, r.err
    resp, _ = http_get(port, opened_browser.opened[0].split(str(port), 1)[1])
    jar = resp.getheader("Set-Cookie").split(";")[0]
    _, body = http_get(port, "/work/plan.md", {"Cookie": jar})
    assert b"Document prepared by Grace for Globex</p>" in body and b"Acme" not in body
    saved = json.loads((paths.state_dir() / "docs.json").read_text())["work/plan.md"]
    assert saved["for"] == "Globex"


def test_the_link_rule_warning_comes_once_when_the_document_is_first_rendered(sheaf, opened_browser, work, port):
    f = work / "links.md"
    f.write_text("# T\n\nSee example.com for more.\n", encoding="utf-8")
    first = sheaf("open", f)
    assert first.code == 0 and "example.com" in first.err
    assert "example.com" not in sheaf("open", f).err


def test_a_page_url_signs_the_browser_in_again_without_rendering(sheaf, opened_browser, doc, port):
    sheaf("open", doc)
    opened_browser.opened.clear()
    r = sheaf("open", f"http://127.0.0.1:{port}/work/plan.md")
    assert r.code == 0 and key() not in r.out + r.err
    assert len(opened_browser.opened) == 1 and key() not in opened_browser.opened[0]
    assert NONCE_URL.fullmatch(opened_browser.opened[0].replace(str(port), "PORT", 1)), opened_browser.opened


def test_a_url_of_another_host_is_refused(sheaf, opened_browser, doc, port):
    r = sheaf("open", "http://evil.example/work/plan.md")
    assert r.code == 2 and opened_browser.opened == []


def test_a_file_that_does_not_exist_starts_no_hub(sheaf, opened_browser, work, port):
    r = sheaf("open", work / "nope.md")
    assert r.code == 1 and "no such file" in r.err
    assert not hub_alive(port) and opened_browser.opened == []


def test_a_file_that_is_not_markdown_starts_no_hub(sheaf, opened_browser, work, port):
    f = work / "notes.txt"
    f.write_text("x")
    r = sheaf("open", f)
    assert r.code == 1 and ".md" in r.err and not hub_alive(port)


def test_the_hub_does_not_inherit_an_agents_session(sheaf, opened_browser, doc, port, monkeypatch):
    for var in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CURSOR_AGENT", "GEMINI_CLI",
                "OPENCODE", "CLAUDECODE"):
        monkeypatch.setenv(var, "x")
    spawned, real_popen = [], subprocess.Popen

    def spy(args, *a, **k):                               # `sheaf` runs main() here: the spawn is in this process
        spawned.append((args, k.get("env")))
        return real_popen(args, *a, **k)
    monkeypatch.setattr("sheafmd.hub.client.subprocess.Popen", spy)
    sheaf("open", doc)
    envs = [env for args, env in spawned if "hub" in args]
    assert len(envs) == 1 and envs[0] is not None
    agent = ("CLAUDE", "CODEX_", "CURSOR_", "GEMINI_", "OPENCODE")
    assert not [n for n in envs[0] if n.startswith(agent)]
    assert "SHEAF_HOME" in envs[0]                        # and the rest of the environment is kept
    proc_env = Path(f"/proc/{server.read_pid_file()['pid']}/environ")
    if proc_env.exists():                                 # where there is a /proc (Linux), the child itself as well
        names = {e.split(b"=", 1)[0].decode() for e in proc_env.read_bytes().split(b"\0") if e}
        assert not [n for n in names if n.startswith(agent)] and "SHEAF_HOME" in names


# ── the agent a render records (SPEC 8.3, 11.5) ──────────────────────────────

def saved_target(address="work/plan.md"):
    return json.loads((paths.state_dir() / "docs.json").read_text())[address]["target"]


@pytest.fixture
def claude_session(tmp_path, monkeypatch):
    """The environment of a Claude Code session whose record lives in the test's own config
    folder; no real session or socket is involved."""
    cfg = tmp_path / "claude-config"
    write_record(cfg, pid=PID, sessionId="s-cli", name="Cosima", cwd="/work/here")
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", str(FakeClaude(tmp_path / "fake-claude").bin))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-cli")
    monkeypatch.setenv("CLAUDE_PID", str(PID))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    return cfg


def test_open_from_a_claude_code_session_records_the_target(sheaf, opened_browser, doc, port, claude_session):
    assert sheaf("open", doc).code == 0
    t = saved_target()
    assert (t["agent"], t["session"], t["pid"], t["name"]) == ("claude-code", "s-cli", PID, "Cosima")
    assert t["config_dir"] == str(claude_session) and t["cwd"] == "/work/here"


def test_the_session_the_tests_make_runs_the_tests_command_never_the_real_claude(
        sheaf, opened_browser, doc, port, claude_session, tmp_path):
    """With nothing named in the environment, `detect` would take the first `claude` on the real
    PATH, and the test hub would enable Ask with the person's own binary."""
    assert sheaf("open", doc).code == 0
    assert saved_target()["bin"].startswith(str(tmp_path) + os.sep)


def test_open_with_no_agent_in_the_environment_records_none_and_keeps_an_earlier_target(
        sheaf, opened_browser, doc, port, claude_session, monkeypatch):
    sheaf("open", doc)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    assert sheaf("open", doc).code == 0
    assert saved_target()["session"] == "s-cli"


def test_agent_none_forgets_the_target_even_from_a_session(sheaf, opened_browser, doc, port, claude_session):
    sheaf("open", doc)
    assert sheaf("open", doc, "--agent", "none").code == 0
    assert saved_target() is None


def test_session_names_another_session_than_the_one_that_runs_the_command(
        sheaf, opened_browser, doc, port, claude_session):
    other = subprocess.Popen(["sleep", "60"])             # a record is believed only while its process lives
    try:
        write_record(claude_session, pid=other.pid, sessionId="s-other", name="Orla")
        assert sheaf("open", doc, "--session", "s-other").code == 0
        t = saved_target()
        assert (t["session"], t["name"], t["pid"]) == ("s-other", "Orla", other.pid)
    finally:
        other.terminate()
        other.wait()


def test_agent_names_an_agent_that_is_not_in_the_environment(sheaf, opened_browser, doc, port):
    assert sheaf("open", doc, "--agent", "codex", "--session", "c-1").code == 0
    t = saved_target()
    assert (t["agent"], t["session"]) == ("codex", "c-1")


# ── the impostor check (9.4) ─────────────────────────────────────────────────

def json_answer(obj):
    body = json.dumps(obj).encode()
    return (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)


@pytest.mark.parametrize("answer", [
    json_answer({"ok": True, "app": "sheaf", "version": "1.0.0", "boot": "x", "service": False,
                 "proof": "0" * 64}),                                  # says it is a hub, cannot prove it
    json_answer({"ok": True, "app": "sheaf", "version": "1.0.0", "boot": "x", "service": False}),
    json_answer({"ok": True, "app": "something-else"}),
    b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello",
    b"HTTP/1.1 500 Oops\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
    b"garbage that is not http"])
def test_something_else_on_the_port_never_gets_the_key_and_nothing_is_opened(sheaf, opened_browser, doc, port, answer):
    paths.ensure_key()
    fake = Impostor(port, answer)
    try:
        r = sheaf("open", doc)
    finally:
        fake.close()
    assert r.code == 1
    assert f"! something else holds 127.0.0.1:{port}, not your sheaf hub" in r.err
    wire = b"".join(fake.seen)
    assert key().encode() not in wire and b"X-Sheaf-Key" not in wire and b"/_/open" not in wire
    assert b"POST" not in wire
    assert opened_browser.opened == [] and key() not in r.out + r.err


def test_the_same_check_guards_start_stop_and_status(sheaf, opened_browser, doc, port):
    paths.ensure_key()
    fake = Impostor(port, json_answer({"ok": True, "app": "sheaf", "proof": "0" * 64}))
    try:
        codes = [sheaf(c).code for c in ("start", "stop", "status")]
    finally:
        fake.close()
    assert codes == [1, 1, 1]
    wire = b"".join(fake.seen)
    assert key().encode() not in wire and b"POST" not in wire and b"X-Sheaf-Key" not in wire


# ── no answer is not an answer (9.4) ─────────────────────────────────────────

def test_a_hub_that_does_not_answer_in_time_is_not_called_a_stranger(port, monkeypatch):
    """A real hub that is alive but not running (SIGSTOP: a starved machine, a laptop that slept):
    it holds the port and the connection, and answers nothing. The challenge still fails closed, but
    says what happened, and the same hub answers again once it runs."""
    c = hubclient.ensure_hub("cli", lambda *a: None, lambda *a: None)[0]     # up, at the usual TIMEOUT
    usual = hubclient.TIMEOUT
    monkeypatch.setattr(hubclient, "TIMEOUT", 0.5)
    pid = server.read_pid_file()["pid"]
    os.kill(pid, signal.SIGSTOP)
    try:
        with pytest.raises(hubclient.HubSilent) as e:
            c.challenge()
        assert str(e.value) == silent_message(port, 0.5)
        assert "something else" not in str(e.value)
    finally:
        os.kill(pid, signal.SIGCONT)
        monkeypatch.setattr(hubclient, "TIMEOUT", usual)     # a hub that has just woken may be slow to answer
    assert c.challenge()["app"] == "sheaf"


@pytest.mark.parametrize("how", ["hold", "close", "reset"])
def test_a_port_that_takes_the_request_and_does_not_answer_gets_its_own_message_and_never_the_key(
        sheaf, opened_browser, doc, port, monkeypatch, how):
    if how == "hold":                  # only a connection that is held waits out the timeout
        monkeypatch.setattr(hubclient, "TIMEOUT", 0.5)
    paths.ensure_key()
    fake = Silent(port, how)
    try:
        r = sheaf("open", doc)
    finally:
        fake.close()
    assert r.code == 1
    said = silent_message(port, 0.5 if how == "hold" else None)
    assert f"! {said}" in r.err and "something else holds" not in r.err
    wire = b"".join(fake.seen)
    assert key().encode() not in wire and b"X-Sheaf-Key" not in wire and b"/_/open" not in wire
    assert b"POST" not in wire
    assert opened_browser.opened == [] and key() not in r.out + r.err


# ── start, stop, status ──────────────────────────────────────────────────────

def test_status_says_when_no_hub_runs(sheaf, port):
    r = sheaf("status")
    assert r.code == 1 and "no hub is running" in r.out


def test_start_starts_a_hub_and_a_second_start_finds_it(sheaf, port):
    r = sheaf("start")
    assert r.code == 0 and f"hub started on 127.0.0.1:{port}" in r.out and TIP in r.out
    pid = server.read_pid_file()["pid"]
    r = sheaf("start")
    assert r.code == 0 and f"hub running on 127.0.0.1:{port} (pid {pid})" in r.out and TIP not in r.out


def test_start_waits_for_a_hub_that_is_slow_to_come_up(sheaf, port, monkeypatch):
    """A hub's start is CPU: its imports take 0.8 s of a free core, so on a machine with sixteen
    times as much to do as cores it answers after twelve (measured: 3.4 s at the median and
    9 s at the worst of 16 starts at once on 2 cores). The command waits for it, and says it started."""
    real, late = hubclient.spawn_hub, []
    monkeypatch.setattr(hubclient, "spawn_hub", lambda by: late.append(threading.Timer(6, real, (by,))) or late[0].start())
    try:
        r = sheaf("start")
    finally:
        for timer in late:
            timer.cancel()                # a failed start must not leave a hub behind the test's reaper
    assert r.code == 0 and f"hub started on 127.0.0.1:{port}" in r.out, r.err


def test_status_says_what_runs(sheaf, port):
    sheaf("start")
    info = server.read_pid_file()
    r = sheaf("status")
    assert r.code == 0
    assert f"127.0.0.1:{port}" in r.out and str(info["pid"]) in r.out and info["version"] in r.out
    assert key() not in r.out


def test_stop_stops_the_hub_and_removes_its_pid_file(sheaf, port):
    sheaf("start")
    pid = server.read_pid_file()["pid"]
    r = sheaf("stop")
    assert r.code == 0 and "hub stopped" in r.out
    assert not hub_alive(port) and server.read_pid_file() is None
    assert gone(pid)
    assert [x["reason"] for x in diagnostics.read() if x["kind"] == "hub-exit"] == ["stop"]


def test_the_hub_process_listens_on_its_socket_and_a_stop_removes_it(sheaf, port):
    sheaf("start")
    sock = paths.hub_socket(port)
    assert sock.is_socket()
    assert sheaf("stop").code == 0
    assert not sock.exists()


def test_stop_with_no_hub_is_not_an_error(sheaf, port):
    r = sheaf("stop")
    assert r.code == 0 and "no hub is running" in r.out


def test_the_key_and_the_cookie_survive_a_restart(sheaf, opened_browser, doc, port):
    sheaf("open", doc)
    resp, _ = http_get(port, opened_browser.opened[0].split(str(port), 1)[1])
    jar = resp.getheader("Set-Cookie").split(";")[0]
    sheaf("stop")
    assert not hub_alive(port)
    sheaf("start")
    resp, body = http_get(port, "/work/plan.md", {"Cookie": jar})
    assert resp.status == 200 and b"about apples" in body


def test_version_names_the_hub_that_runs(sheaf, port):
    assert "hub" not in sheaf("version").out
    sheaf("start")
    out = sheaf("version").out.splitlines()
    assert out[0].startswith("sheaf ") and out[1].startswith("hub ")


# ── the hub as a process (8.4) ───────────────────────────────────────────────

def run_hub(*extra):
    return subprocess.Popen([sys.executable, "-m", "sheafmd", "hub", *extra],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def wait_alive(port):
    for _ in range(200):
        if hub_alive(port):
            return
        time.sleep(0.05)
    pytest.fail("the hub did not start")


def wait_started(pid):
    """The hub has written its start row: the port listens a little before that, and a test that
    asks for the row on the strength of the port alone races the hub's own start."""
    for _ in range(200):
        if hub_rows("hub-start") and (server.read_pid_file() or {}).get("pid") == pid:
            return
        time.sleep(0.05)
    pytest.fail("the hub did not write its start row and its pid file")


def test_a_second_hub_loses_the_race_exits_1_and_writes_only_port_taken(port):
    first = run_hub("--started-by", "cli")
    try:
        wait_alive(port)
        wait_started(first.pid)
        second = run_hub("--started-by", "cli")
        out, err = second.communicate(timeout=30)
        assert second.returncode == 1 and "already in use" in err
        kinds = [(x["kind"], x["source"]) for x in diagnostics.read()]
        assert kinds.count(("hub-start", "hub")) == 1 and ("port-taken", "hub") in kinds
        assert hub_alive(port)                                   # the first is untouched
        assert server.read_pid_file()["pid"] == first.pid
    finally:
        first.terminate()
        first.wait(timeout=30)


def test_sigterm_is_a_clean_stop(port):
    p = run_hub("--started-by", "cli")
    wait_alive(port)
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=30) == 0
    assert server.read_pid_file() is None
    rows = [x for x in diagnostics.read() if x["kind"] in ("hub-start", "hub-exit")]
    assert [(x["kind"], x.get("reason")) for x in rows] == [("hub-start", None), ("hub-exit", "signal")]
    assert rows[0]["started_by"] == "cli" and rows[0]["port"] == port


def test_open_gives_the_browser_no_link_when_the_hub_cannot_make_one_and_says_where_to_look(
        sheaf, opened_browser, doc, port, monkeypatch):
    from sheafmd.hub import client as hubclient
    sheaf("start")
    real = hubclient.HubClient.call

    def call(self, method, path, body=None):
        return (404, {"ok": False, "error": "no such route"}) if path == "/_/signin" else real(self, method, path, body)

    monkeypatch.setattr(hubclient.HubClient, "call", call)
    r = sheaf("open", doc)
    assert opened_browser.opened == [] and key() not in r.out + r.err
    assert "sheaf signin-url" in r.err and "no such route" in r.err
    assert r.out.splitlines()[-1] == f"  ~ http://127.0.0.1:{port}/work/plan.md"
