"""The jump to a session's terminal (SPEC 4.3 `[jump]`, 8.5 `/_/jump`, 10.5).

The command is the test's own script, which writes down how it was called; the session is a
record in the test's own config folder. Nothing here moves a window."""
import json
import os
import sys

import pytest

from agent_fakes import PID, FakeClaude, write_record
from helpers import page_meta
from sheafmd import config, paths
from sheafmd.agents.claude_code import proc_start

DOC = "work/plan.md"
URL = "/work/plan.md"
ODD = "O'Neil \"the\" ; rm -rf ~ $HOME `id`"

PROBE = '''\
import json, os, sys
out, rest = sys.argv[1], sys.argv[2:]
env = {k: v for k, v in os.environ.items() if k.startswith("SHEAF_JUMP_")}
tmp = out + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump({"argv": rest, "env": env}, f)
os.replace(tmp, out)
if os.environ.get("PROBE_EXIT"):
    sys.stderr.write(os.environ.get("PROBE_ERR", "no window found") + "\\nsecond line\\n")
    sys.exit(int(os.environ["PROBE_EXIT"]))
'''


def toml_list(items):
    return "[" + ", ".join(json.dumps(i) for i in items) + "]"


def write_config(text):
    path = paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


@pytest.fixture
def probe(tmp_path):
    script = tmp_path / "probe.py"
    script.write_text(PROBE, encoding="utf-8")
    return script, tmp_path / "called.json"


def set_jump(probe, *args):
    script, out = probe
    write_config(f"[jump]\ncommand = {toml_list([sys.executable, str(script), str(out), *args])}\n")


@pytest.fixture
def cfg(tmp_path):
    d = tmp_path / "claude-config"
    (d / "sessions").mkdir(parents=True)
    return d


@pytest.fixture
def session(cfg, tmp_path, work):
    write_record(cfg, name=ODD, sessionId="s-1", procStart=proc_start(PID))
    claude = FakeClaude(tmp_path / "fake")
    return {"agent": "claude-code", "session": "s-1", "pid": PID, "socket": "", "name": ODD,
            "cwd": str(work), "bin": str(claude.bin), "config_dir": str(cfg),
            "proc_start": proc_start(PID)}


def attach(browser, plan, target):
    r = browser.post("/_/render", {"path": str(plan), "settings": {}, "target": target},
                     key=True, cookie=False)
    assert r.status == 200, r.text


def jump(browser, **body):
    return browser.post("/_/jump", {"doc": DOC, **body})


def called(probe):
    return json.loads(probe[1].read_text(encoding="utf-8"))


# ── the [jump] table of config.toml ──────────────────────────────────────────

def test_no_jump_table_is_no_jump():
    write_config('name = "Ada"\n')
    assert config.jump_command() is None


def test_a_jump_command_is_a_list_of_text():
    write_config('[jump]\ncommand = ["curl", "-s", "http://127.0.0.1:8765/jump"]\n')
    assert config.jump_command() == ["curl", "-s", "http://127.0.0.1:8765/jump"]


@pytest.mark.parametrize("command", ['"curl -s http://x"', "[]", '["curl", 3]', '[""]', "3"])
def test_a_jump_command_that_is_not_a_list_of_text_stops_the_command(command):
    write_config(f"[jump]\ncommand = {command}\n")
    with pytest.raises(config.ConfigError) as e:
        config.jump_command()
    assert str(paths.config_file()) in str(e.value) and "command" in str(e.value)


def test_a_jump_table_without_a_command_stops_the_command():
    write_config("[jump]\n")
    with pytest.raises(config.ConfigError, match="command"):
        config.jump_command()


def test_an_unknown_key_in_the_jump_table_warns_and_the_command_stands():
    write_config('[jump]\ncommand = ["true"]\nshell = true\n')
    warned = []
    assert config.jump_command(warn=warned.append) == ["true"]
    assert len(warned) == 1 and "shell" in warned[0] and str(paths.config_file()) in warned[0]


def test_jump_must_be_a_table():
    write_config('jump = "curl"\n')
    with pytest.raises(config.ConfigError, match="jump"):
        config.jump_command()


# ── what the page is told ────────────────────────────────────────────────────

def test_the_page_is_told_it_can_jump_only_with_a_jump_table_and_a_target(browser, plan, session, probe):
    attach(browser, plan, session)
    assert "jump" not in page_meta(browser.get(URL).text)["agent"]
    set_jump(probe, "{session}")
    assert page_meta(browser.get(URL).text)["agent"]["jump"] is True
    assert browser.get(f"/_/doc?doc={DOC}").json()["target"]["jump"] is True


def test_a_page_with_no_session_is_told_nothing_of_a_jump(browser, plan, probe):
    set_jump(probe, "{session}")
    assert page_meta(browser.get(URL).text)["agent"] is None


# ── the route ────────────────────────────────────────────────────────────────

def test_a_jump_runs_the_command_with_the_sessions_values(browser, plan, session, probe):
    set_jump(probe, "{session}", "{pid}", "{name}", "{agent}", "n={name};")
    attach(browser, plan, session)
    r = jump(browser)
    assert r.status == 200, r.text
    got = called(probe)
    clean = " ".join(ODD.split())
    assert got["argv"] == ["s-1", str(PID), clean, "claude-code", f"n={clean};"]
    assert got["env"] == {"SHEAF_JUMP_SESSION": "s-1", "SHEAF_JUMP_PID": str(PID),
                          "SHEAF_JUMP_NAME": clean, "SHEAF_JUMP_AGENT": "claude-code"}


def test_a_value_never_splits_an_argument_and_no_shell_reads_it(browser, plan, session, probe):
    set_jump(probe, "{name}")
    attach(browser, plan, session)
    assert jump(browser).status == 200
    assert len(called(probe)["argv"]) == 1


def test_the_body_names_a_document_and_nothing_else_runs(browser, plan, session, probe):
    set_jump(probe, "{session}", "{pid}")
    attach(browser, plan, session)
    r = jump(browser, session="other", pid=1, command=["touch", "/tmp/never"], argv=["x"], name="Eve")
    assert r.status == 200
    assert called(probe)["argv"] == ["s-1", str(PID)]


def test_without_a_jump_table_the_answer_says_so(browser, plan, session):
    attach(browser, plan, session)
    r = jump(browser)
    assert r.status == 409 and "[jump]" in r.json()["error"]


def test_a_page_with_no_session_cannot_jump(browser, plan, probe):
    set_jump(probe, "{session}")
    r = jump(browser)
    assert r.status == 409 and r.json()["error"] == "Render this page from an agent session to Ask and Tell it."
    assert not probe[1].exists()


def test_a_session_that_ended_is_not_jumped_to(browser, plan, session, probe, cfg):
    set_jump(probe, "{session}")
    attach(browser, plan, session)
    os.unlink(cfg / "sessions" / f"{PID}.json")
    r = jump(browser)
    assert r.status == 409 and "has ended" in r.json()["error"]
    assert not probe[1].exists()


def test_a_record_left_for_a_pid_another_process_took_is_not_jumped_to(browser, plan, session, probe, cfg):
    set_jump(probe, "{session}")
    attach(browser, plan, session)
    write_record(cfg, name=ODD, sessionId="s-1", procStart="1")      # not this process's start
    r = jump(browser)
    assert r.status == 409 and "has ended" in r.json()["error"]
    assert not probe[1].exists()


def another_account_pid():
    """A pid whose process another account runs, or 0 (a container may run every process as one user)."""
    try:
        names = os.listdir("/proc")
    except OSError:
        return 0
    for n in sorted((n for n in names if n.isdigit()), key=int):
        try:
            if os.stat(f"/proc/{n}").st_uid != os.getuid() and proc_start(int(n)):
                return int(n)
        except OSError:
            continue
    return 0


def test_a_session_run_by_another_account_is_not_jumped_to(browser, plan, session, probe, cfg):
    other = another_account_pid()
    if not other:
        pytest.skip("needs a process of another account")
    set_jump(probe, "{session}")
    write_record(cfg, pid=other, name="Init", sessionId="s-9", procStart=proc_start(other))
    attach(browser, plan, {**session, "pid": other, "session": "s-9", "proc_start": proc_start(other)})
    r = jump(browser)
    assert r.status == 409 and "not run by this account" in r.json()["error"]
    assert not probe[1].exists()


def test_a_command_that_fails_says_why_in_one_line(browser, plan, session, probe, monkeypatch):
    set_jump(probe, "{session}")
    attach(browser, plan, session)
    monkeypatch.setenv("PROBE_EXIT", "3")
    r = jump(browser)
    assert r.status == 409
    assert r.json()["error"] == "The jump command failed (exit 3): no window found"


def test_a_command_that_is_not_there_says_so(browser, plan, session):
    write_config('[jump]\ncommand = ["/nonexistent/sheaf-jump"]\n')
    attach(browser, plan, session)
    r = jump(browser)
    assert r.status == 409 and r.json()["error"] == "The jump command was not found."


def test_a_command_that_hangs_is_stopped_after_its_time(browser, plan, session, monkeypatch):
    from sheafmd.hub import asktell
    monkeypatch.setattr(asktell, "JUMP_TIMEOUT", 0.3)
    write_config(f'[jump]\ncommand = {toml_list([sys.executable, "-c", "import time; time.sleep(30)"])}\n')
    attach(browser, plan, session)
    r = jump(browser)
    assert r.status == 409 and r.json()["error"] == "The jump command did not finish within 0.3 seconds."


def test_a_jump_needs_the_cookie_and_an_origin_like_any_post(browser, plan, session, probe):
    set_jump(probe, "{session}")
    attach(browser, plan, session)
    assert browser.post("/_/jump", {"doc": DOC}, cookie=False).status == 401
    assert browser.post("/_/jump", {"doc": DOC}, origin="http://evil.example").status == 403
    assert not probe[1].exists()


def test_the_document_must_exist(browser, plan, session, probe):
    set_jump(probe, "{session}")
    attach(browser, plan, session)
    assert browser.post("/_/jump", {"doc": "work/nope.md"}).status == 404
    assert browser.post("/_/jump", {}).status == 400


def test_a_record_that_does_not_say_which_process_it_is_not_jumped_to(browser, plan, session, probe, cfg):
    set_jump(probe, "{session}")
    attach(browser, plan, session)
    write_record(cfg, name=ODD, sessionId="s-1")            # a live pid, but no start to tell it by
    r = jump(browser)
    assert r.status == 409 and "not run by this account" in r.json()["error"]
    assert not probe[1].exists()


@pytest.mark.parametrize("sid", ["--help", "-x", "two words", "", "x" * 65, "a\nb"])
def test_a_session_id_that_could_pass_for_an_option_or_split_is_not_given_to_the_command(
        browser, plan, session, probe, cfg, sid):
    set_jump(probe, "{session}")
    attach(browser, plan, session)
    write_record(cfg, name=ODD, sessionId=sid, procStart=proc_start(PID))
    r = jump(browser)
    assert r.status == 409
    assert not probe[1].exists()


def test_a_second_jump_while_one_runs_is_refused(browser, hub, plan, session, probe):
    set_jump(probe, "{session}")
    attach(browser, plan, session)
    with hub.asktell._jumping:
        r = jump(browser)
    assert r.status == 409 and r.json()["error"] == "A jump is already running."
    assert not probe[1].exists()
    assert jump(browser).status == 200


def test_a_member_of_the_proxy_socket_is_not_offered_the_jump_route():
    from sheafmd.hub.handler import COOKIE, Handler
    assert Handler._for_members(("seen", COOKIE, None)) is True
    assert Handler._for_members(("jump", COOKIE, None)) is False


def test_a_session_id_of_the_longest_shape_reaches_the_command_whole(browser, plan, session, probe, cfg):
    sid = "s" * 64
    set_jump(probe, "{session}")
    attach(browser, plan, session)
    write_record(cfg, name=ODD, sessionId=sid, procStart=proc_start(PID))
    assert jump(browser).status == 200
    got = called(probe)
    assert got["argv"] == [sid] and got["env"]["SHEAF_JUMP_SESSION"] == sid


def test_a_long_reason_from_the_command_is_kept_to_200_characters(browser, plan, session, probe, monkeypatch):
    set_jump(probe, "{session}")
    attach(browser, plan, session)
    monkeypatch.setenv("PROBE_EXIT", "3")
    monkeypatch.setenv("PROBE_ERR", "w" * 150 + " " + "x" * 100)
    err = jump(browser).json()["error"]
    assert err == "The jump command failed (exit 3): " + ("w" * 150 + " " + "x" * 49)


def test_an_unknown_key_in_the_jump_table_is_warned_about_when_a_jump_is_asked_for(
        browser, plan, session, probe, capsys):
    script, out = probe
    write_config(f"[jump]\ncommand = {toml_list([sys.executable, str(script), str(out), 'x'])}\nshell = true\n")
    attach(browser, plan, session)
    assert jump(browser).status == 200
    assert "unknown key 'shell' in [jump]" in capsys.readouterr().err


def test_a_command_that_leaves_a_helper_holding_its_output_still_counts_as_done(browser, plan, session, monkeypatch):
    from sheafmd.hub import asktell
    monkeypatch.setattr(asktell, "JUMP_TIMEOUT", 2.0)
    script = "import subprocess, sys; subprocess.Popen(['sleep', '6']); sys.exit(0)"
    write_config(f'[jump]\ncommand = {toml_list([sys.executable, "-c", script])}\n')
    attach(browser, plan, session)
    assert jump(browser).status == 200


def test_a_command_that_cannot_be_started_says_why_not_that_it_is_missing(browser, plan, session, tmp_path):
    notexec = tmp_path / "plain.txt"
    staged = tmp_path / "plain.txt.tmp"
    staged.write_text("x", encoding="utf-8")
    os.replace(staged, notexec)
    write_config(f"[jump]\ncommand = {toml_list([str(notexec)])}\n")
    attach(browser, plan, session)
    r = jump(browser)
    assert r.status == 409 and r.json()["error"].startswith("The jump command could not be started: ")


def test_a_failing_command_reports_the_first_line_of_its_stderr_not_a_piece_of_a_long_trace(browser, plan, session):
    script = "import sys; print('error: no pane 42', file=sys.stderr); print('x' * 100 + '\\n' * 1, file=sys.stderr, end=''); sys.stderr.write(('trace line\\n') * 800); sys.exit(1)"
    write_config(f'[jump]\ncommand = {toml_list([sys.executable, "-c", script])}\n')
    attach(browser, plan, session)
    r = jump(browser)
    assert r.status == 409 and "error: no pane 42" in r.json()["error"]
