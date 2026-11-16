"""`sheaf init AGENT` (SPEC 14.5): the stdio door registered with each agent's own command, and
the skill for Claude Code.

Nothing here touches a real agent or a real config. The agents' commands are fakes in a folder of
this test's own, the only one on PATH; the home is this test's own (tests/conftest.py), and
CLAUDE_CONFIG_DIR, CODEX_HOME and GEMINI_CLI_HOME, which would send a write elsewhere, are
removed first. The fakes behave as the real commands were seen to behave: `claude mcp add`
refuses a name it has, `codex mcp add` and `gemini mcp add` replace it without a word, which is
why `init` has to look before it adds.
"""
import errno
import json
import os
import shlex
import stat
import sys
from pathlib import Path

import pytest

from helpers import brand_words_in
from sheafmd import agent_setup
from sheafmd.cli import main
from sheafmd.hub import service

SHEAF = "/opt/sheaf/bin/sheaf"
AGENTS = agent_setup.AGENTS
OLD = "/home/u/.local/bin/sheaf"         # where an earlier sheaf was, for an entry init wrote then
MARKER = "<!-- written by sheaf init; sheaf may replace it -->"

FAKE = r'''#!{python}
import json, os, sys

AGENT = {agent!r}
STATE = os.path.join(os.environ["FAKE_AGENT_STATE_DIR"], AGENT + "-state.json")
argv = sys.argv[1:]
try:
    state = json.load(open(STATE))
except OSError:
    state = {{"calls": [], "servers": {{}}}}
state["calls"].append(argv)


def save():
    json.dump(state, open(STATE, "w"))


def split_command(rest):
    cmd = rest[rest.index("--") + 1:]
    return {{"command": cmd[0], "args": cmd[1:]}}


if argv[:2] == ["mcp", "get"] and AGENT == "claude":
    save()
    # As the real one does (claude 2.1.295): the entry of the project it is run in wins over the user's.
    local = state.get("local", {{}}).get(argv[2])
    if local and os.getcwd() == local["cwd"]:
        print("%s:\n  Scope: Local config (private to you in this project)\n  Type: stdio\n"
              "  Command: %s\n  Args: %s\n  Environment:\n"
              % (argv[2], local["command"], " ".join(local["args"])))
        sys.exit(0)
    server = state["servers"].get(argv[2])
    if server is None:
        print('No MCP server named "%s". Run `claude mcp add` to add one.' % argv[2])
        sys.exit(1)
    env = "".join("    %s=%s\n" % kv for kv in server.get("env", {{}}).items())
    print("%s:\n  Scope: User config (available in all your projects)\n  Type: stdio\n  Command: %s\n  Args: %s\n  Environment:\n%s"
          % (argv[2], server["command"], " ".join(server["args"]), env))
    sys.exit(0)
if argv[:2] == ["mcp", "remove"] and AGENT == "claude":
    name = argv[2]
    if name not in state["servers"]:
        print('No MCP server named "%s" in user scope' % name)
        save()
        sys.exit(1)
    del state["servers"][name]
    save()
    print("Removed MCP server %s from user config" % name)
    sys.exit(0)
if argv[:2] == ["mcp", "get"] and AGENT == "codex":
    save()
    server = state["servers"].get(argv[2])
    if server is None:
        print("Error: No MCP server named '%s' found." % argv[2], file=sys.stderr)
        sys.exit(1)
    print(json.dumps({{"name": argv[2], "transport": {{"type": "stdio", **server}}}}))
    sys.exit(0)
if argv[:2] == ["mcp", "add"] and AGENT == "claude":
    name = argv[argv.index("--scope") + 2] if "--scope" in argv else argv[2]
    if name in state["servers"]:
        print("MCP server %s already exists in user config" % name)
        save()
        sys.exit(1)
    state["servers"][name] = split_command(argv)
    save()
    print("Added stdio MCP server %s" % name)
    sys.exit(0)
if argv[:2] == ["mcp", "add"] and AGENT == "codex":
    state["servers"][argv[2]] = split_command(argv)          # replaces an entry, as the real one does
    save()
    print("Added global MCP server '%s'." % argv[2])
    sys.exit(0)
if argv[:2] == ["mcp", "add"] and AGENT == "gemini":
    # gemini mcp add --scope user NAME COMMAND -- ARGS...: replaces the entry, as the real one does
    rest = argv[2:]
    scope = rest[rest.index("--scope") + 1]
    del rest[rest.index("--scope"):rest.index("--scope") + 2]
    name, command, tail = rest[0], rest[1], rest[rest.index("--") + 1:] if "--" in rest else rest[2:]
    path = os.path.join(os.path.expanduser("~"), ".gemini", "settings.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        settings = json.load(open(path))
    except OSError:
        settings = {{}}
    settings.setdefault("mcpServers", {{}})[name] = {{"command": command, "args": tail}}
    json.dump(settings, open(path, "w"))
    save()
    sys.exit(0)
save()
print("unexpected: " + " ".join(argv), file=sys.stderr)
sys.exit(3)
'''


class Agents:
    """The fake agent commands of one test: which are installed, and what each was asked."""

    def __init__(self, folder: Path, state_dir: Path):
        self.folder, self.state_dir = folder, state_dir

    def install(self, agent: str, servers: dict | None = None, local: dict | None = None):
        """`servers` are the user's; `local` (claude) is {"sheaf": {"cwd", "command", "args"}}: an
        entry of one project, which only `claude mcp get` run in that folder sees."""
        path = self.folder / agent
        path.write_text(FAKE.format(python=sys.executable, agent=agent))
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        self._file(agent).write_text(json.dumps({"calls": [], "servers": servers or {}, "local": local or {}}))

    def _file(self, agent) -> Path:
        return self.state_dir / f"{agent}-state.json"

    def _read(self, agent):
        return json.loads(self._file(agent).read_text())

    def calls(self, agent) -> list[list[str]]:
        return self._read(agent)["calls"]

    def adds(self, agent) -> list[list[str]]:
        return [c for c in self.calls(agent) if c[:2] == ["mcp", "add"]]

    def servers(self, agent) -> dict:
        return self._read(agent)["servers"]

    def put_server(self, agent, name: str, entry: dict):
        """Another command registers `entry` as `name`, keeping what the fake was asked so far."""
        state = self._read(agent)
        state["servers"][name] = entry
        self._file(agent).write_text(json.dumps(state))


@pytest.fixture
def agents(tmp_path, monkeypatch):
    folder, state = tmp_path / "fake-bin", tmp_path / "fake-state"
    folder.mkdir()
    state.mkdir()
    monkeypatch.setenv("PATH", str(folder))          # no real agent command can be found
    monkeypatch.setenv("FAKE_AGENT_STATE_DIR", str(state))
    for var in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "GEMINI_CLI_HOME", "CURSOR_CONFIG_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(service, "sheaf_command", lambda: [SHEAF])
    assert str(home()).startswith(str(tmp_path)), "the home of this test is its own"
    return Agents(folder, state)


def init(capsys, *argv):
    code = main(["init", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def home() -> Path:
    return Path(os.environ["HOME"])


def skill() -> Path:
    return home() / ".claude" / "skills" / "sheaf" / "SKILL.md"


def cursor_config() -> Path:
    return home() / ".cursor" / "mcp.json"


def our_claude():
    return {"command": SHEAF, "args": ["mcp", "--agent", "claude-code"]}


# ── the command line ─────────────────────────────────────────────────────────

def test_init_names_the_four_agents_and_needs_one(capsys):
    code, out, err = init(capsys)
    assert code == 2 and "claude" in err and "cursor" in err


def test_an_agent_that_is_not_one_of_the_four_is_a_usage_error(capsys):
    code, out, err = init(capsys, "emacs")
    assert code == 2 and "emacs" in err


def test_init_is_listed_in_the_help():
    from sheafmd.cli import top_help
    assert "init claude|codex|gemini|cursor" in top_help()


# ── sheaf run from uvx: a path that uv deletes ───────────────────────────────
#
# `uvx --from <source> sheaf init claude` runs the sheaf script of a temporary environment in uv's
# cache (seen with uv 0.10.7: <cache>/archive-v0/<hash>/bin/sheaf, and a new hash for every new
# revision). service.sheaf_command() answers with that path, and `uv cache clean` or `uv cache prune`
# deletes it, after which the agent's door cannot start. So init registers nothing from there.

UVX_SHEAF = "/home/u/.cache/uv/archive-v0/9YP2VgzG0HljE9FE5UbQP/bin/sheaf"
PINNED = "1234567890abcdef1234567890abcdef12345678"


def run_from_uvx(monkeypatch, direct_url=None, command=(UVX_SHEAF,)):
    monkeypatch.setattr(service, "sheaf_command", lambda: list(command))
    monkeypatch.setattr(agent_setup, "installed_from", lambda: direct_url)


@pytest.mark.parametrize("agent", AGENTS)
def test_sheaf_run_from_uvx_registers_nothing_and_prints_the_line_to_run_instead(
        agents, capsys, monkeypatch, agent):
    if agent != "cursor":
        agents.install(agent)
    run_from_uvx(monkeypatch)
    code, out, err = init(capsys, agent)
    assert code == 1, out
    assert UVX_SHEAF in err and "uv tool install sheafmd" in err and f"sheaf init {agent}" in err
    assert not (home() / ".claude").exists() and not cursor_config().exists()
    assert not gemini_settings().exists()
    if agent != "cursor":
        assert agents.adds(agent) == []


class _Unreadable:
    def read_text(self, name):
        raise OSError(5, "Input/output error")


def test_installed_from_that_cannot_read_the_record_says_none_not_a_traceback(monkeypatch):
    monkeypatch.setattr(agent_setup.metadata, "distribution", lambda name: _Unreadable())
    assert agent_setup.installed_from() is None


@pytest.mark.parametrize("agent", AGENTS)
def test_sheaf_run_from_uvx_with_an_unreadable_record_prints_the_fallback_line_and_exits_1(
        agents, capsys, monkeypatch, agent):
    if agent != "cursor":
        agents.install(agent)
    monkeypatch.setattr(service, "sheaf_command", lambda: [UVX_SHEAF])
    monkeypatch.setattr(agent_setup.metadata, "distribution", lambda name: _Unreadable())
    code, out, err = init(capsys, agent)
    assert code == 1, out
    assert "uv tool install sheafmd" in err and f"sheaf init {agent}" in err


def test_sheaf_run_from_uvx_with_no_agent_command_on_the_path_still_prints_this_line_not_the_add_command(
        agents, capsys, monkeypatch):
    run_from_uvx(monkeypatch)
    code, out, err = init(capsys, "claude")
    assert code == 1 and "uv tool install" in err and "mcp add" not in err


def test_sheaf_run_from_uvx_from_a_git_source_prints_the_line_that_installs_that_revision(
        agents, capsys, monkeypatch):
    run_from_uvx(monkeypatch, json.dumps({
        "url": "https://github.com/sweatshop-ai/sheaf",
        "vcs_info": {"vcs": "git", "commit_id": PINNED, "requested_revision": "main"}}))
    code, out, err = init(capsys, "cursor")
    assert code == 1
    assert ("uv tool install 'sheafmd @ git+https://github.com/sweatshop-ai/sheaf@" + PINNED + "'") in err


def test_the_line_to_run_instead_never_carries_a_password_of_the_source_url(agents, capsys, monkeypatch):
    run_from_uvx(monkeypatch, json.dumps({
        "url": "https://me:tok-77ac01d2@git.example.invalid/team/repo",
        "vcs_info": {"vcs": "git", "commit_id": PINNED}}))
    code, out, err = init(capsys, "cursor")
    assert code == 1 and "tok-77ac01d2" not in out + err and "git.example.invalid/team/repo@" in err


@pytest.mark.parametrize("url", [
    "https://ghp_77ac01d2e9@github.com/team/repo",          # a token as the user name, which is how GitHub takes one
    "https://me:tok-77ac01d2@git.example.invalid/team/repo",
    "https://tok-77ac01d2@git.example.invalid:8443/team/repo",
])
def test_the_line_to_run_instead_carries_no_credential_of_the_source_url(agents, capsys, monkeypatch, url):
    run_from_uvx(monkeypatch, json.dumps({"url": url, "vcs_info": {"vcs": "git", "commit_id": PINNED}}))
    code, out, err = init(capsys, "cursor")
    assert code == 1 and "77ac01d2" not in out + err and "@git" not in err.replace("@git+", "")
    assert f"/team/repo@{PINNED}" in err


def test_the_line_to_run_instead_keeps_the_git_user_of_an_ssh_source(agents, capsys, monkeypatch):
    run_from_uvx(monkeypatch, json.dumps({"url": "ssh://git@github.com/team/repo",
                                          "vcs_info": {"vcs": "git", "commit_id": PINNED}}))
    code, out, err = init(capsys, "cursor")
    assert f"git+ssh://git@github.com/team/repo@{PINNED}" in err


ARCHIVE = "https://files.example.invalid/dl/sheafmd-1.0.0.tar.gz"


@pytest.mark.parametrize("url", [
    ARCHIVE + "?token=tok-77ac01d2",
    ARCHIVE + "?X-Amz-Signature=77ac01d2&X-Amz-Expires=300",
    ARCHIVE + "#sha256=77ac01d2",
    ARCHIVE + "?token=tok-77ac01d2#sha256=77ac01d2",
])
def test_the_line_to_run_instead_drops_the_query_and_fragment_of_an_archive_url(agents, capsys, monkeypatch, url):
    run_from_uvx(monkeypatch, json.dumps({"url": url, "archive_info": {"hash": "sha256=77ac01d2"}}))
    code, out, err = init(capsys, "cursor")
    assert code == 1 and "77ac01d2" not in out + err
    assert f"uv tool install 'sheafmd @ {ARCHIVE}'" in err


def test_the_line_to_run_instead_says_when_it_left_out_a_query(agents, capsys, monkeypatch):
    run_from_uvx(monkeypatch, json.dumps({"url": ARCHIVE + "?token=tok-77ac01d2", "archive_info": {}}))
    code, out, err = init(capsys, "cursor")
    assert "the URL had a query or a fragment, which is left out" in err and "tok-77ac01d2" not in err


def test_the_line_to_run_instead_stays_quiet_about_a_query_when_the_url_had_none(agents, capsys, monkeypatch):
    run_from_uvx(monkeypatch, json.dumps({"url": ARCHIVE, "archive_info": {}}))
    code, out, err = init(capsys, "cursor")
    assert "left out" not in err


def test_the_line_to_run_instead_keeps_the_subdirectory_of_an_archive_url(agents, capsys, monkeypatch):
    run_from_uvx(monkeypatch, json.dumps({"url": ARCHIVE + "?token=tok-77ac01d2", "archive_info": {},
                                          "subdirectory": "packages/sheafmd"}))
    code, out, err = init(capsys, "cursor")
    assert f"sheafmd @ {ARCHIVE}#subdirectory=packages/sheafmd" in err and "tok-77ac01d2" not in err


def test_the_line_to_run_instead_keeps_the_subdirectory_of_a_git_source(agents, capsys, monkeypatch):
    run_from_uvx(monkeypatch, json.dumps({"url": "https://github.com/team/repo", "subdirectory": "pkg",
                                          "vcs_info": {"vcs": "git", "commit_id": PINNED}}))
    code, out, err = init(capsys, "cursor")
    assert f"git+https://github.com/team/repo@{PINNED}#subdirectory=pkg" in err


def test_a_checkout_in_a_folder_that_is_named_like_uvs_cache_is_not_taken_for_it(agents, capsys, monkeypatch):
    run_from_uvx(monkeypatch, command=("/home/u/archive-v2/work/.venv/bin/sheaf",))
    code, out, err = init(capsys, "cursor")
    assert code == 0, err


def test_sheaf_run_from_uvx_through_a_link_into_the_cache_is_the_same(agents, capsys, tmp_path, monkeypatch):
    real = tmp_path / "cache" / "environments-v2" / "abc123" / "bin" / "sheaf"
    real.parent.mkdir(parents=True)
    real.write_text("#!/bin/sh\n")
    link = tmp_path / "bin" / "sheaf"
    link.parent.mkdir()
    link.symlink_to(real)
    run_from_uvx(monkeypatch, command=(str(link),))
    code, out, err = init(capsys, "cursor")
    assert code == 1 and not cursor_config().exists()


def test_sheaf_run_from_pipx_run_registers_nothing_either(agents, capsys, monkeypatch, tmp_path):
    """`pipx run` keeps its venv in pipx's cache and deletes it once it is 14 days old (pipx 1.8)."""
    venv = tmp_path / "pipx" / ".cache" / "2207f8a391f550f"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "sheaf").write_text("#!/bin/sh\n")
    (venv / "pipx_metadata.json").write_text("{}\n")
    run_from_uvx(monkeypatch, command=(str(venv / "bin" / "sheaf"),))
    code, out, err = init(capsys, "cursor")
    assert code == 1 and not cursor_config().exists()
    assert f"pipx's cache ({venv / 'bin' / 'sheaf'})" in err and "uv tool install sheafmd" in err


def test_sheaf_run_from_uvx_as_python_dash_m_is_the_same(agents, capsys, monkeypatch):
    run_from_uvx(monkeypatch, command=("/home/u/.cache/uv/archive-v0/9YP2VgzG0HljE9FE5UbQP/bin/python",
                                       "-m", "sheafmd"))
    code, out, err = init(capsys, "cursor")
    assert code == 1 and not cursor_config().exists()


@pytest.mark.parametrize("path", [
    "/home/u/.local/share/uv/tools/sheafmd/bin/sheaf",      # uv tool install
    "/home/u/.local/bin/sheaf",                             # its link on PATH
    "/home/u/.local/pipx/venvs/sheafmd/bin/sheaf",          # pipx install
    "/home/u/work/sheaf/.venv/bin/sheaf",                   # a checkout
])
def test_a_sheaf_that_is_installed_is_registered_as_before(agents, capsys, monkeypatch, path):
    run_from_uvx(monkeypatch, command=(path,))
    code, out, err = init(capsys, "cursor")
    assert code == 0, err
    assert json.loads(cursor_config().read_text())["mcpServers"]["sheaf"]["command"] == path


# ── claude: the command of its own, then the skill ───────────────────────────

def test_claude_gets_the_door_by_its_own_command_and_then_the_skill(agents, capsys):
    agents.install("claude")
    code, out, err = init(capsys, "claude")
    assert code == 0, err
    assert agents.adds("claude") == [
        ["mcp", "add", "--scope", "user", "sheaf", "--", SHEAF, "mcp", "--agent", "claude-code"]]
    assert agents.servers("claude") == {"sheaf": our_claude()}
    text = skill().read_text(encoding="utf-8")
    assert MARKER in text.splitlines()
    assert "claude" in out and str(skill()) in out


def test_claude_skill_follows_claude_config_dir_as_the_agent_itself_does(agents, capsys, tmp_path, monkeypatch):
    agents.install("claude")
    elsewhere = tmp_path / "claude-config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(elsewhere))
    code, out, err = init(capsys, "claude")
    assert code == 0, err
    assert (elsewhere / "skills" / "sheaf" / "SKILL.md").is_file()
    assert not skill().exists()


def test_claude_not_on_the_path_prints_the_command_changes_nothing_and_exits_1(agents, capsys):
    code, out, err = init(capsys, "claude")
    assert code == 1
    assert "claude mcp add --scope user sheaf -- " + SHEAF + " mcp --agent claude-code" in err
    assert not skill().exists() and not (home() / ".claude").exists()


def test_claude_a_path_in_the_command_that_needs_quoting_is_quoted_in_the_printed_command(
        agents, capsys, monkeypatch):
    monkeypatch.setattr(service, "sheaf_command", lambda: ["/opt/my tools/sheaf"])
    code, out, err = init(capsys, "claude")
    assert code == 1
    assert shlex.join(["claude", "mcp", "add", "--scope", "user", "sheaf", "--", "/opt/my tools/sheaf",
                       "mcp", "--agent", "claude-code"]) in err


def test_claude_running_init_again_changes_nothing_and_says_so(agents, capsys):
    agents.install("claude")
    init(capsys, "claude")
    before = skill().read_bytes()
    code, out, err = init(capsys, "claude")
    assert code == 0, err
    assert len(agents.adds("claude")) == 1, "the door is registered once"
    assert skill().read_bytes() == before
    assert "already" in out and "up to date" in out


def test_claude_a_door_called_sheaf_that_is_not_ours_is_left_alone(agents, capsys):
    agents.install("claude", {"sheaf": {"command": "/somewhere/else", "args": ["serve"]}})
    code, out, err = init(capsys, "claude")
    assert code == 1
    assert agents.adds("claude") == [] and not skill().exists()
    assert "/somewhere/else" not in err and "claude mcp remove sheaf" in err


# `claude mcp add sheaf -- ...` with no scope writes the local one: it is the door of that project
# only, and `claude mcp get` run in that project shows it first.
LOCAL_OURS = {"command": SHEAF, "args": ["mcp", "--agent", "claude-code"]}
LOCAL_OTHER = {"command": "/somewhere/else", "args": ["serve"]}


@pytest.mark.parametrize("held", [LOCAL_OURS, LOCAL_OTHER], ids=["ours", "not ours"])
def test_claude_an_entry_of_this_project_only_is_not_the_door_of_the_others(
        agents, capsys, tmp_path, monkeypatch, held):
    project = tmp_path / "project"
    project.mkdir()
    home().mkdir(parents=True, exist_ok=True)
    agents.install("claude", local={"sheaf": {"cwd": str(project), **held}})
    monkeypatch.chdir(project)
    code, out, err = init(capsys, "claude")
    assert code == 0, err
    assert agents.adds("claude") == [
        ["mcp", "add", "--scope", "user", "sheaf", "--", SHEAF, "mcp", "--agent", "claude-code"]]
    assert agents.servers("claude") == {"sheaf": our_claude()}
    assert "already" not in out


def test_claude_that_has_the_door_for_every_project_and_one_of_this_project_is_already_set_up(
        agents, capsys, tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    home().mkdir(parents=True, exist_ok=True)
    agents.install("claude", {"sheaf": our_claude()}, {"sheaf": {"cwd": str(project), **LOCAL_OTHER}})
    monkeypatch.chdir(project)
    code, out, err = init(capsys, "claude")
    assert code == 0, err
    assert agents.adds("claude") == [] and "already" in out


def test_claude_that_answers_with_an_entry_of_one_project_where_it_was_asked_is_not_taken_for_the_users(
        agents, capsys):
    home().mkdir(parents=True, exist_ok=True)
    agents.install("claude", local={"sheaf": {"cwd": str(home()), **LOCAL_OURS}})
    code, out, err = init(capsys, "claude")
    assert code == 0, err
    assert len(agents.adds("claude")) == 1 and agents.adds("claude")[0][2:4] == ["--scope", "user"]


def test_claude_a_project_entry_in_the_home_folder_hides_the_users_and_counts_as_absent(
        agents, capsys):
    # Asked from the home folder, `get` shows this folder's own entry first, so the user's is not seen:
    # the look says absent, the add is tried, and claude's refusal is not printed.
    home().mkdir(parents=True, exist_ok=True)
    agents.install("claude", {"sheaf": our_claude()}, {"sheaf": {"cwd": str(home()), **LOCAL_OTHER}})
    code, out, err = init(capsys, "claude")
    assert code == 1
    assert len(agents.adds("claude")) == 1
    assert "failed" in err and "already exists" not in out + err


def test_claude_with_no_home_folder_still_asks_from_a_folder_that_is_no_project(
        agents, capsys, tmp_path, monkeypatch):
    # The user's door is there, and so is this project's own entry, which `get` shows first in the project.
    project = tmp_path / "project"
    project.mkdir()
    assert not home().exists()
    agents.install("claude", {"sheaf": our_claude()}, {"sheaf": {"cwd": str(project), **LOCAL_OTHER}})
    monkeypatch.chdir(project)
    code, out, err = init(capsys, "claude")
    assert code == 0, err
    assert agents.adds("claude") == [] and "already" in out


def test_claude_an_answer_with_no_scope_line_is_one_sheaf_cannot_tell(agents, capsys):
    agents.install("claude")
    (agents.folder / "claude").write_text(
        "#!/bin/sh\n[ \"$2\" = get ] && printf 'sheaf:\\n  Type: stdio\\n  Command: x\\n' && exit 0\nexit 3\n")
    code, out, err = init(capsys, "claude")
    assert code == 1 and not skill().exists()
    assert "cannot tell" in err and "claude mcp add --scope user sheaf" in err


def test_claude_an_existing_skill_it_did_not_write_stops_init_before_anything_is_changed(agents, capsys):
    agents.install("claude")
    skill().parent.mkdir(parents=True)
    mine = "---\nname: sheaf\ndescription: my own\n---\n\nmy notes on sheaf\n"
    skill().write_text(mine)
    code, out, err = init(capsys, "claude")
    assert code == 1
    assert skill().read_text() == mine
    assert agents.adds("claude") == [], "the door is not registered either: nothing changes"
    assert str(skill()) in err and "did not write" in err


# `mcp get` health-checks the server and can take up to a minute, so what is at the skill's path
# when init looked at it first can be another file when init writes it.
CLAUDE_THAT_WRITES_A_SKILL = '''#!{python}
import sys
if sys.argv[1:3] == ["mcp", "get"]:
    open({path!r}, "w").write({text!r})
    print('No MCP server named "sheaf".')
    sys.exit(1)
sys.exit(0)
'''
THEIRS = "---\nname: sheaf\ndescription: my own\n---\n\nmy notes on sheaf\n"


@pytest.mark.parametrize("before", [None, f"---\nname: sheaf\ndescription: old\n---\n{MARKER}\n\nthe old text\n"],
                         ids=["no file at first", "ours at first"])
def test_claude_a_skill_file_made_by_someone_else_while_the_door_is_registered_is_not_replaced(
        agents, capsys, before):
    agents.install("claude")
    skill().parent.mkdir(parents=True)
    if before:
        skill().write_text(before)
    (agents.folder / "claude").write_text(
        CLAUDE_THAT_WRITES_A_SKILL.format(python=sys.executable, path=str(skill()), text=THEIRS))
    code, out, err = init(capsys, "claude")
    assert code == 1
    assert skill().read_text() == THEIRS
    assert str(skill()) in err and "did not write" in err
    assert list(skill().parent.iterdir()) == [skill()], "no half-written file is left"


# SPEC 14.5: the marker is the first line of the file, or the first line after the front matter. A
# marker further down is not the line init writes, so the file is not init's to replace.
@pytest.mark.parametrize("text", [
    f"---\nname: sheaf\ndescription: mine\n---\n\n{MARKER}\n\nmy notes\n",       # a blank line first
    f"---\nname: sheaf\ndescription: mine\n---\n# sheaf\n{MARKER}\nmy notes\n",   # a heading first
    f"# my own sheaf notes\n{MARKER}\n",                                           # no front matter
    f"---\nname: sheaf\n{MARKER}\n",                                              # front matter never closed
], ids=["blank line before", "heading before", "second line", "front matter not closed"])
def test_claude_a_marker_that_is_not_where_init_writes_it_does_not_make_the_file_its_own(
        agents, capsys, text):
    agents.install("claude")
    skill().parent.mkdir(parents=True)
    skill().write_text(text)
    code, out, err = init(capsys, "claude")
    assert code == 1 and skill().read_text() == text
    assert "did not write" in err and agents.adds("claude") == []


@pytest.mark.parametrize("text", [
    f"{MARKER}\n\nthe old text\n",                                                # first line of the file
    f"---\nname: sheaf\ndescription: old\n---\n{MARKER}\n\nthe old text\n",       # first after the front matter
    f"---\r\nname: sheaf\r\n---\r\n{MARKER}\r\n\r\nthe old text\r\n",         # the same, with CRLF
], ids=["first line", "after front matter", "crlf"])
def test_claude_a_marker_where_init_writes_it_makes_the_file_its_own(agents, capsys, text):
    agents.install("claude")
    skill().parent.mkdir(parents=True)
    skill().write_bytes(text.encode())
    code, out, err = init(capsys, "claude")
    assert code == 0, err
    assert "the old text" not in skill().read_text()


def test_claude_a_skill_it_wrote_is_replaced_by_the_new_one(agents, capsys):
    agents.install("claude")
    skill().parent.mkdir(parents=True)
    skill().write_text(f"---\nname: sheaf\ndescription: old\n---\n{MARKER}\n\nthe old text\n")
    code, out, err = init(capsys, "claude")
    assert code == 0, err
    new = skill().read_text()
    assert "the old text" not in new and MARKER in new.splitlines()


def test_claude_a_skill_file_that_is_a_link_is_not_written_through(agents, capsys, tmp_path):
    agents.install("claude")
    target = tmp_path / "their-skill.md"
    target.write_text(f"{MARKER}\ntheirs\n")
    skill().parent.mkdir(parents=True)
    skill().symlink_to(target)
    code, out, err = init(capsys, "claude")
    assert code == 1 and target.read_text() == f"{MARKER}\ntheirs\n"
    assert skill().is_symlink() and agents.adds("claude") == []


def test_claude_a_skill_folder_that_is_a_link_is_not_written_through(agents, capsys, tmp_path):
    agents.install("claude")
    theirs = tmp_path / "their-skills" / "sheaf"
    theirs.mkdir(parents=True)
    skill().parent.parent.mkdir(parents=True)
    skill().parent.symlink_to(theirs)
    code, out, err = init(capsys, "claude")
    assert code == 1 and list(theirs.iterdir()) == [] and agents.adds("claude") == []


def test_claude_when_the_agent_command_fails_the_skill_is_not_written(agents, capsys):
    agents.install("claude")
    path = agents.folder / "claude"
    path.write_text("#!/bin/sh\necho 'it broke' >&2\nexit 1\n")
    code, out, err = init(capsys, "claude")
    assert code == 1 and not skill().exists()
    assert "claude mcp get sheaf" in err and "exit 1" in err and "it broke" not in err


def test_the_skill_is_written_whole_or_not_at_all(agents, capsys, monkeypatch):
    agents.install("claude")

    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(agent_setup.os, "replace", broken)
    code, out, err = init(capsys, "claude")
    assert code == 1 and not skill().exists()
    assert "disk full" in err
    assert list(skill().parent.iterdir()) == [], "no half-written file is left"


# ── codex and gemini: look first, because their `add` replaces ───────────────

def test_codex_gets_the_door_by_its_own_command(agents, capsys):
    agents.install("codex")
    code, out, err = init(capsys, "codex")
    assert code == 0, err
    assert agents.adds("codex") == [["mcp", "add", "sheaf", "--", SHEAF, "mcp", "--agent", "codex"]]
    assert not skill().exists(), "only claude has a skill"


def test_codex_a_door_called_sheaf_that_is_not_ours_is_not_replaced(agents, capsys):
    agents.install("codex", {"sheaf": {"command": "/somewhere/else", "args": []}})
    code, out, err = init(capsys, "codex")
    assert code == 1
    assert agents.adds("codex") == [], "`codex mcp add` would replace it without a word"
    assert agents.servers("codex")["sheaf"]["command"] == "/somewhere/else"
    assert "codex mcp remove sheaf" in err


def test_codex_our_own_door_is_left_as_it_is(agents, capsys):
    agents.install("codex", {"sheaf": {"command": SHEAF, "args": ["mcp", "--agent", "codex"]}})
    code, out, err = init(capsys, "codex")
    assert code == 0 and agents.adds("codex") == [] and "already" in out


def test_codex_not_on_the_path_prints_the_command(agents, capsys):
    code, out, err = init(capsys, "codex")
    assert code == 1 and f"codex mcp add sheaf -- {SHEAF} mcp --agent codex" in err


def test_codex_that_will_not_say_whether_it_has_the_door_is_not_asked_to_add_it(agents, capsys):
    agents.install("codex")
    (agents.folder / "codex").write_text("#!/bin/sh\necho 'config.toml is invalid' >&2\nexit 1\n")
    code, out, err = init(capsys, "codex")
    assert code == 1 and "codex mcp get sheaf --json" in err and "exit 1" in err
    assert "config.toml is invalid" not in err          # what it said is theirs, and is not printed


# What the real commands print when their config does not parse (read in a throwaway home with a
# fake token): codex quotes the offending line of
# config.toml, claude names the token its JSON parser stopped at. The first two texts are theirs,
# with the token swapped for one of ours; the third is invented, an entry on standard output with a
# failing exit, to cover that path too. A server that holds a token is exactly where a config breaks.
BROKEN_GET = '''#!{python}
import os, sys
if sys.argv[1:3] == ["mcp", "get"]:
    sys.stdout.write({out!r})
    sys.stderr.write({err!r})
    sys.exit({code})
with open(os.path.join(os.environ["FAKE_AGENT_STATE_DIR"], "adds"), "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
'''
TOKEN = "tok-" "2c7d90b1e4a85f36"
BROKEN_ANSWERS = {
    "codex, the line of config.toml": (
        "", "Error: failed to load bootstrap configuration\n\nCaused by:\n"
            "    0: /home/u/.codex/config.toml:6:11: string values must be quoted, expected literal string\n"
            "    1: TOML parse error at line 6, column 11\n         |\n"
            f"       6 | API_KEY = {TOKEN}\n         |           ^^^^^^^^^^^^^^^^^^^^^\n", 1),
    "claude, the token the parser stopped at": (
        "", f'Configuration error in /home/u/.claude.json: JSON Parse error: Unexpected identifier "{TOKEN}"\n', 1),
    "claude, an entry on standard output": (
        "sheaf:\n  Scope: User config\n  Type: stdio\n  Command: npx\n"
        f"  Args: mcp-remote https://hub.invalid/mcp --header Authorization: Bearer {TOKEN}\n", "", 1),
}


@pytest.mark.parametrize("case", BROKEN_ANSWERS)
def test_an_agent_that_fails_to_answer_is_named_and_what_it_said_is_never_printed(agents, capsys, case):
    agent, (out_text, err_text, exit_code) = case.split(",")[0], BROKEN_ANSWERS[case]
    agents.install(agent)
    (agents.folder / agent).write_text(
        BROKEN_GET.format(python=sys.executable, out=out_text, err=err_text, code=exit_code))
    code, out, err = init(capsys, agent)
    assert code == 1 and not (agents.state_dir / "adds").exists()
    assert f"`{agents.folder / agent} mcp get sheaf" in err and f"exit {exit_code}" in err
    assert f"{agent} mcp add" in err
    for what in (TOKEN, "Authorization", "mcp-remote", "hub.invalid", "API_KEY", "TOML parse error"):
        assert what not in out + err


# SPEC 14.5: a server of another kind (HTTP, as the real commands print it: claude 2.1.295 `Type:
# http` and `URL:`, codex-cli 0.147.0 `"type": "streamable_http"`) is "set up differently"; an answer
# sheaf does not know is "cannot tell": nothing changes, the add command is printed, exit 1.
ANSWERS_SHEAF_CANNOT_READ = {
    "codex, a warning line before the JSON": ("codex",
        'WARNING: could not create PATH aliases\n{"name": "sheaf", "transport": {"type": "stdio", '
        '"command": "/somewhere/else", "args": []}}\n'),
    "codex, not JSON at all": ("codex", "sheaf is an MCP server\n"),
    "codex, JSON that is not an object": ("codex", "[1, 2]\n"),
    "codex, an object with no transport": ("codex", '{"name": "sheaf"}\n'),
    "codex, a transport of no kind sheaf knows": ("codex", '{"name": "sheaf", "transport": {}}\n'),
    "claude, no type and no command": ("claude",
        "sheaf:\n  Scope: User config (available in all your projects)\n  Status: ok\n"),
    "claude, stdio with no command": ("claude",
        "sheaf:\n  Scope: User config (available in all your projects)\n  Type: stdio\n"),
}
ANSWERS_OF_ANOTHER_KIND = {
    "codex, an HTTP server": ("codex", '{"name": "sheaf", "transport": {"type": "streamable_http", '
                                       '"url": "http://127.0.0.1:1/mcp"}}\n'),
    "claude, an HTTP server": ("claude", "sheaf:\n  Scope: User config (available in all your projects)\n"
                                         "  Type: http\n  URL: http://127.0.0.1:1/mcp\n"),
}
SAYS_THIS = '''#!{python}
import os, sys
if sys.argv[1:3] == ["mcp", "get"]:
    sys.stdout.write({out!r})
    sys.exit(0)
with open(os.path.join(os.environ["FAKE_AGENT_STATE_DIR"], "adds"), "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
'''


def agent_that_says(agents, agent, text):
    agents.install(agent)
    (agents.folder / agent).write_text(SAYS_THIS.format(python=sys.executable, out=text))


@pytest.mark.parametrize("case", ANSWERS_SHEAF_CANNOT_READ)
def test_an_answer_sheaf_cannot_read_is_cannot_tell_not_a_server_set_up_differently(agents, capsys, case):
    agent, text = ANSWERS_SHEAF_CANNOT_READ[case]
    agent_that_says(agents, agent, text)
    code, out, err = init(capsys, agent)
    assert code == 1 and not (agents.state_dir / "adds").exists() and not skill().exists()
    assert "cannot tell" in err and f"{agent} mcp add" in err and "set up differently" not in err
    assert "failed" not in err, "it exited 0: nothing failed"
    for held in ("/somewhere/else", "127.0.0.1"):
        assert held not in out + err


@pytest.mark.parametrize("case", ANSWERS_OF_ANOTHER_KIND)
def test_a_server_of_another_kind_called_sheaf_is_set_up_differently_and_left_alone(agents, capsys, case):
    agent, text = ANSWERS_OF_ANOTHER_KIND[case]
    agent_that_says(agents, agent, text)
    code, out, err = init(capsys, agent)
    assert code == 1 and not (agents.state_dir / "adds").exists()
    assert "set up differently" in err and f"{agent} mcp remove sheaf" in err
    assert "127.0.0.1" not in out + err


def codex_entry(command=None, args=None, **top):
    """`codex mcp get sheaf --json` as codex-cli 0.147.0 prints it for an entry added with no options."""
    entry = {"name": "sheaf", "enabled": True, "disabled_reason": None,
             "transport": {"type": "stdio", "command": command or OLD, "args": args or ["mcp", "--agent", "codex"],
                           "env": None, "env_vars": [], "cwd": None},
             "enabled_tools": None, "disabled_tools": None, "startup_timeout_sec": None, "tool_timeout_sec": None}
    entry.update(top)
    return json.dumps(entry) + "\n"


def test_codex_an_entry_of_init_with_nothing_the_get_shows_is_still_not_replaced(agents, capsys):
    # What `codex mcp get --json` leaves out (supports_parallel_tool_calls, per-tool approval_mode, ...)
    # is what a replace would drop.
    agent_that_says(agents, "codex", codex_entry())
    code, out, err = init(capsys, "codex")
    assert code == 1 and not (agents.state_dir / "adds").exists()
    assert "sheaf init wrote" in err and "codex mcp remove sheaf" in err


@pytest.mark.parametrize("setting", [
    {"enabled": False}, {"enabled_tools": ["read"]}, {"disabled_tools": ["write"]},
    {"startup_timeout_sec": 30}, {"tool_timeout_sec": 120}, {"a_setting_of_a_later_codex": "x"},
], ids=lambda d: next(iter(d)))
def test_codex_an_entry_a_person_set_up_further_than_init_does_is_not_replaced(agents, capsys, setting):
    # `codex mcp add` writes only the command and arguments, so these would be lost.
    agent_that_says(agents, "codex", codex_entry(**setting))
    code, out, err = init(capsys, "codex")
    assert code == 1 and not (agents.state_dir / "adds").exists()
    assert "set up differently" in err and "codex mcp remove sheaf" in err


@pytest.mark.parametrize("args", [5, "mcp --agent codex"], ids=["a number", "a string"])
def test_an_entry_whose_arguments_are_not_a_list_is_another_server_not_a_traceback(agents, capsys, args):
    agent_that_says(agents, "codex", codex_entry(args=args))
    code, out, err = init(capsys, "codex")
    assert code == 1 and "set up differently" in err and not (agents.state_dir / "adds").exists()


# The add can fail after a look that found nothing (the config broke in between, or the add fails
# for a reason it quotes), and then the agent's answer is the same text the look steps never print.
# The answers are BROKEN_ANSWERS's: two the real commands print and one invented, an
# entry that names a bearer token on standard output.
BROKEN_ADD = '''#!{python}
import os, sys
if sys.argv[1:3] == ["mcp", "get"]:
    sys.stderr.write("Error: No MCP server named 'sheaf' found.\\n")
    sys.exit(1)
with open(os.path.join(os.environ["FAKE_AGENT_STATE_DIR"], "adds"), "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
sys.stdout.write({out!r})
sys.stderr.write({err!r})
sys.exit({code})
'''


@pytest.mark.parametrize("agent", ["claude", "codex", "gemini"])
@pytest.mark.parametrize("case", BROKEN_ANSWERS)
def test_an_add_that_fails_names_its_command_and_exit_status_and_never_what_the_agent_said(agents, capsys, agent, case):
    out_text, err_text, exit_code = BROKEN_ANSWERS[case]
    agents.install(agent)
    (agents.folder / agent).write_text(
        BROKEN_ADD.format(python=sys.executable, out=out_text, err=err_text, code=exit_code))
    code, out, err = init(capsys, agent)
    assert code == 1 and (agents.state_dir / "adds").exists()
    assert f"`{agents.folder / agent} mcp add" in err and f"exit {exit_code}" in err
    for what in (TOKEN, "Authorization", "mcp-remote", "hub.invalid", "API_KEY", "TOML parse error", "JSON Parse error"):
        assert what not in out + err


@pytest.mark.parametrize("agent", ["claude", "codex", "gemini"])
def test_an_add_that_works_is_unchanged_and_says_nothing_of_a_failure(agents, capsys, agent):
    agents.install(agent)
    code, out, err = init(capsys, agent)
    assert code == 0 and err == "" and f"{agent}: the sheaf door is registered" in out
    assert len(agents.adds(agent)) == 1


def gemini_settings() -> Path:
    return home() / ".gemini" / "settings.json"


# Codex's and Gemini's add replace a server of the same name without a word, which is why init looks
# first. Another command can register one in the time between that look and the add.
SET_UP_ELSEWHERE = {"command": "npx", "args": ["mcp-remote", "https://hub.invalid/mcp"]}


def a_sheaf_server_appears_after_the_look(monkeypatch, agents, agent, entry):
    """Right after init's first look answers, another command makes `entry` the agent's `sheaf`
    (nothing with entry None: the control). Returns what each look answered."""
    spec = agent_setup.CLI_AGENTS[agent]
    real, looks = spec.look, []

    def look(exe, command):
        found = real(exe, command)
        if not looks and entry is not None:
            if agent == "gemini":
                settings = json.loads(gemini_settings().read_text()) if gemini_settings().exists() else {}
                settings.setdefault("mcpServers", {})["sheaf"] = entry
                gemini_settings().parent.mkdir(parents=True, exist_ok=True)
                gemini_settings().write_text(json.dumps(settings))
            else:
                agents.put_server(agent, "sheaf", entry)
        looks.append(found.kind)
        return found

    monkeypatch.setattr(spec, "look", look)
    return looks


@pytest.mark.parametrize("late", [True, False], ids=["registered meanwhile", "control"])
@pytest.mark.parametrize("agent", ["codex", "gemini"])
def test_a_sheaf_server_registered_after_the_look_is_not_replaced_by_the_add(agents, capsys, monkeypatch,
                                                                             agent, late):
    agents.install(agent)
    looks = a_sheaf_server_appears_after_the_look(monkeypatch, agents, agent,
                                                  SET_UP_ELSEWHERE if late else None)
    code, out, err = init(capsys, agent)
    if late:
        assert code == 1 and agents.adds(agent) == [], "the add would have replaced it"
        assert entry_now(agents, agent) == SET_UP_ELSEWHERE
        assert f"{agent} changed what it holds under the name sheaf" in err and f"sheaf init {agent}" in err
        assert "mcp-remote" not in out + err and "hub.invalid" not in out + err
        assert looks == ["absent", "other"]
    else:
        assert code == 0, err
        assert entry_now(agents, agent)["args"] == ["mcp", "--agent", agent] and len(agents.adds(agent)) == 1


@pytest.mark.parametrize("agent", ["codex", "gemini"])
def test_a_second_look_that_cannot_tell_says_so_and_adds_nothing(agents, capsys, monkeypatch, agent):
    agents.install(agent)
    answers = iter([agent_setup.ABSENT, agent_setup.Found("unknown", "the second answer could not be read")])
    monkeypatch.setattr(agent_setup.CLI_AGENTS[agent], "look", lambda exe, command: next(answers))
    code, out, err = init(capsys, agent)
    assert code == 1 and agents.adds(agent) == []
    assert "cannot tell" in err and "the second answer could not be read" in err and "changed" not in err


@pytest.mark.parametrize("late", [True, False], ids=["replaced meanwhile", "control"])
def test_gemini_an_entry_of_init_replaced_by_another_after_the_look_is_not_pointed_at_this_sheaf(
        agents, capsys, monkeypatch, late):
    put_entry(agents, "gemini", old_entry("gemini"))
    looks = a_sheaf_server_appears_after_the_look(monkeypatch, agents, "gemini",
                                                  SET_UP_ELSEWHERE if late else None)
    code, out, err = init(capsys, "gemini")
    if late:
        assert code == 1 and agents.adds("gemini") == [] and entry_now(agents, "gemini") == SET_UP_ELSEWHERE
        assert looks == ["moved", "other"]
    else:
        assert code == 0, err
        assert entry_now(agents, "gemini")["command"] == SHEAF


def test_claude_is_asked_once_since_its_add_refuses_a_name_it_has(agents, capsys, monkeypatch):
    """`claude mcp get` health-checks the server and can take a minute; its add refuses a second
    `sheaf`, so a server made after the look is not replaced and a second look would buy nothing."""
    agents.install("claude")
    looks = a_sheaf_server_appears_after_the_look(monkeypatch, agents, "claude", SET_UP_ELSEWHERE)
    code, out, err = init(capsys, "claude")
    assert code == 1 and looks == ["absent"]
    assert agents.servers("claude")["sheaf"] == SET_UP_ELSEWHERE and len(agents.adds("claude")) == 1


def test_gemini_gets_the_door_in_the_user_scope_by_its_own_command(agents, capsys):
    agents.install("gemini")
    code, out, err = init(capsys, "gemini")
    assert code == 0, err
    assert agents.adds("gemini") == [
        ["mcp", "add", "--scope", "user", "sheaf", SHEAF, "--", "mcp", "--agent", "gemini"]]


def test_gemini_other_settings_survive_and_a_door_not_ours_is_not_replaced(agents, capsys):
    agents.install("gemini")
    gemini_settings().parent.mkdir(parents=True)
    mine = {"theme": "dark", "mcpServers": {"sheaf": {"command": "/somewhere/else", "args": []}}}
    gemini_settings().write_text(json.dumps(mine))
    code, out, err = init(capsys, "gemini")
    assert code == 1 and agents.adds("gemini") == []
    assert json.loads(gemini_settings().read_text()) == mine
    assert "gemini mcp remove" in err


def test_gemini_our_own_door_is_left_as_it_is(agents, capsys):
    agents.install("gemini")
    gemini_settings().parent.mkdir(parents=True)
    ours = {"mcpServers": {"sheaf": {"command": SHEAF, "args": ["mcp", "--agent", "gemini"]}}}
    gemini_settings().write_text(json.dumps(ours))
    code, out, err = init(capsys, "gemini")
    assert code == 0 and agents.adds("gemini") == [] and "already" in out


def test_gemini_settings_it_cannot_read_are_not_guessed_at(agents, capsys):
    agents.install("gemini")
    gemini_settings().parent.mkdir(parents=True)
    text = '{\n  // my notes\n  "theme": "dark"\n}\n'
    gemini_settings().write_text(text)
    code, out, err = init(capsys, "gemini")
    assert code == 1 and agents.adds("gemini") == []
    assert gemini_settings().read_text() == text
    assert str(gemini_settings()) in err and "gemini mcp add --scope user sheaf" in err


def moved_gemini_home(tmp_path, monkeypatch, servers):
    """GEMINI_CLI_HOME replaces the home directory for gemini itself (its homedir()), so its user
    scope is $GEMINI_CLI_HOME/.gemini/settings.json and `gemini mcp add` writes there."""
    moved = tmp_path / "moved-gemini-home"
    (moved / ".gemini").mkdir(parents=True)
    (moved / ".gemini" / "settings.json").write_text(json.dumps({"mcpServers": servers}))
    monkeypatch.setenv("GEMINI_CLI_HOME", str(moved))
    return moved


def test_gemini_with_its_home_moved_looks_where_it_keeps_its_settings_and_does_not_replace(
        agents, capsys, tmp_path, monkeypatch):
    agents.install("gemini")
    moved_gemini_home(tmp_path, monkeypatch, {"sheaf": {"command": "/somewhere/else", "args": []}})
    code, out, err = init(capsys, "gemini")
    assert code == 1 and agents.adds("gemini") == []
    assert "gemini mcp remove" in err


def test_gemini_with_its_home_moved_knows_its_own_door_there(agents, capsys, tmp_path, monkeypatch):
    agents.install("gemini")
    moved_gemini_home(tmp_path, monkeypatch,
                      {"sheaf": {"command": SHEAF, "args": ["mcp", "--agent", "gemini"]}})
    code, out, err = init(capsys, "gemini")
    assert code == 0 and agents.adds("gemini") == [] and "already" in out


def test_gemini_with_its_home_moved_does_not_read_the_settings_of_the_old_home(
        agents, capsys, tmp_path, monkeypatch):
    # A server in ~/.gemini is not the one `gemini mcp add` would replace now.
    agents.install("gemini")
    gemini_settings().parent.mkdir(parents=True)
    gemini_settings().write_text(json.dumps({"mcpServers": {"sheaf": {"command": "/old", "args": []}}}))
    moved_gemini_home(tmp_path, monkeypatch, {})
    code, out, err = init(capsys, "gemini")
    assert code == 0, err
    assert len(agents.adds("gemini")) == 1


def test_gemini_not_on_the_path_prints_the_command(agents, capsys):
    code, out, err = init(capsys, "gemini")
    assert code == 1 and "gemini mcp add --scope user sheaf " + SHEAF + " -- mcp --agent gemini" in err


# ── cursor: a file of its own, merged ────────────────────────────────────────

def test_cursor_gets_the_door_in_a_new_file_that_only_its_owner_reads(agents, capsys):
    code, out, err = init(capsys, "cursor")
    assert code == 0, err
    assert json.loads(cursor_config().read_text()) == {
        "mcpServers": {"sheaf": {"command": SHEAF, "args": ["mcp", "--agent", "cursor"]}}}
    assert stat.S_IMODE(cursor_config().stat().st_mode) == 0o600
    assert str(cursor_config()) in out


def test_cursor_the_other_servers_and_settings_in_the_file_survive_and_its_mode_is_kept(agents, capsys):
    cursor_config().parent.mkdir(parents=True)
    mine = {"other": [1, 2], "mcpServers": {"fs": {"command": "npx", "args": ["fs"], "env": {"K": "v"}}}}
    cursor_config().write_text(json.dumps(mine))
    cursor_config().chmod(0o640)
    code, out, err = init(capsys, "cursor")
    assert code == 0, err
    got = json.loads(cursor_config().read_text())
    assert got["other"] == [1, 2] and got["mcpServers"]["fs"] == mine["mcpServers"]["fs"]
    assert got["mcpServers"]["sheaf"]["args"] == ["mcp", "--agent", "cursor"]
    assert stat.S_IMODE(cursor_config().stat().st_mode) == 0o640


def test_cursor_a_door_called_sheaf_that_is_not_ours_is_not_replaced(agents, capsys):
    cursor_config().parent.mkdir(parents=True)
    text = json.dumps({"mcpServers": {"sheaf": {"command": "/somewhere/else"}}})
    cursor_config().write_text(text)
    code, out, err = init(capsys, "cursor")
    assert code == 1 and cursor_config().read_text() == text
    assert str(cursor_config()) in err and "/somewhere/else" not in err


def test_cursor_a_door_that_is_not_ours_is_named_and_what_it_holds_is_never_printed(agents, capsys):
    cursor_config().parent.mkdir(parents=True)
    token = "tok-" "8f3a91c2d7e04b65"
    text = json.dumps({"mcpServers": {"sheaf": {
        "url": "http://127.0.0.1:1/mcp", "headers": {"Authorization": f"Bearer {token}"}}}})
    cursor_config().write_text(text)
    code, out, err = init(capsys, "cursor")
    assert code == 1 and cursor_config().read_text() == text
    assert str(cursor_config()) in err and "server called sheaf" in err
    for held in (token, "Authorization", "127.0.0.1"):
        assert held not in out + err


@pytest.mark.parametrize("agent", ["claude", "codex", "gemini"])
def test_a_stdio_door_that_is_not_ours_is_named_and_what_it_holds_is_never_printed(agents, capsys, agent):
    token = "tok-" "2c7d90b1e4a85f36"
    held = {"command": "npx", "args": ["mcp-remote", "https://hub.invalid/mcp",
                                       "--header", f"Authorization: Bearer {token}"]}
    if agent == "gemini":
        agents.install("gemini")
        gemini_settings().parent.mkdir(parents=True)
        gemini_settings().write_text(json.dumps({"mcpServers": {"sheaf": held}}))
    else:
        agents.install(agent, {"sheaf": held})
    code, out, err = init(capsys, agent)
    assert code == 1 and agents.adds(agent) == []
    assert f"{agent} already has a server called sheaf" in err and f"{agent} mcp remove" in err
    for what in (token, "Authorization", "mcp-remote", "hub.invalid"):
        assert what not in out + err


def test_cursor_our_own_door_is_left_as_it_is(agents, capsys):
    init(capsys, "cursor")
    before = cursor_config().read_bytes()
    code, out, err = init(capsys, "cursor")
    assert code == 0 and cursor_config().read_bytes() == before and "already" in out


@pytest.mark.parametrize("text", ["{not json", '{"a": 1, // c\n}', "[]", '{"mcpServers": []}'])
def test_cursor_a_file_it_cannot_merge_into_is_left_exactly_as_it_is(agents, capsys, text):
    cursor_config().parent.mkdir(parents=True)
    cursor_config().write_text(text)
    code, out, err = init(capsys, "cursor")
    assert code == 1 and cursor_config().read_text() == text
    assert str(cursor_config()) in err and '"sheaf"' in err, "what to add by hand is printed"


def test_cursor_an_empty_file_has_nothing_to_lose_and_is_filled(agents, capsys):
    cursor_config().parent.mkdir(parents=True)
    cursor_config().write_text("\n")
    code, out, err = init(capsys, "cursor")
    assert code == 0, err
    assert json.loads(cursor_config().read_text())["mcpServers"]["sheaf"]["command"] == SHEAF


def another_writer_before_the_write(monkeypatch, write):
    """Run `write()` once between init's read of mcp.json and its write: Cursor, or another command,
    writing the file inside the time of `sheaf init cursor`."""
    real = agent_setup.write_text_atomic

    def late(*a, **k):
        write()
        return real(*a, **k)

    monkeypatch.setattr(agent_setup, "write_text_atomic", late)


ANOTHER_SERVER = {"command": "npx", "args": ["fs2"]}


def write_in_place(data):
    cursor_config().write_text(json.dumps(data))


def write_by_replace(data):
    tmp = cursor_config().with_name("mcp.json.new")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, cursor_config())


@pytest.mark.parametrize("late", [True, False], ids=["written meanwhile", "control"])
@pytest.mark.parametrize("how", [write_in_place, write_by_replace], ids=["in place", "replaced"])
def test_cursor_a_setting_written_between_inits_read_and_its_write_is_kept(agents, capsys, monkeypatch, late,
                                                                          how):
    cursor_config().parent.mkdir(parents=True)
    mine = {"mcpServers": {"fs": {"command": "npx", "args": ["fs"]}}}
    cursor_config().write_text(json.dumps(mine))
    theirs = {"mcpServers": {**mine["mcpServers"], "fs2": ANOTHER_SERVER}}
    another_writer_before_the_write(monkeypatch, lambda: how(theirs) if late else None)
    code, out, err = init(capsys, "cursor")
    got = json.loads(cursor_config().read_text())
    if late:
        assert code == 1 and got == theirs, "the other writer's setting is kept: the file is left as it is"
        assert str(cursor_config()) in err and "changed while sheaf init" in err and "sheaf init cursor" in err
        assert "fs2" not in out + err and "npx" not in out + err
    else:
        assert code == 0, err
        assert got["mcpServers"]["fs"] == mine["mcpServers"]["fs"] and "sheaf" in got["mcpServers"]
    assert sorted(p.name for p in cursor_config().parent.iterdir()) == ["mcp.json"]


@pytest.mark.parametrize("late", [True, False], ids=["made meanwhile", "control"])
def test_cursor_a_file_made_between_inits_look_and_its_write_is_kept(agents, capsys, monkeypatch, late):
    cursor_config().parent.mkdir(parents=True)
    theirs = {"mcpServers": {"fs2": ANOTHER_SERVER}}
    another_writer_before_the_write(monkeypatch, lambda: write_in_place(theirs) if late else None)
    code, out, err = init(capsys, "cursor")
    got = json.loads(cursor_config().read_text())
    if late:
        assert code == 1 and got == theirs
        assert str(cursor_config()) in err and "changed while sheaf init" in err
    else:
        assert code == 0, err
        assert got == {"mcpServers": {"sheaf": {"command": SHEAF, "args": ["mcp", "--agent", "cursor"]}}}


def test_cursor_a_file_that_is_a_link_is_not_replaced(agents, capsys, tmp_path):
    cursor_config().parent.mkdir(parents=True)
    target = tmp_path / "dotfiles-mcp.json"
    target.write_text("{}")
    cursor_config().symlink_to(target)
    code, out, err = init(capsys, "cursor")
    assert code == 1 and target.read_text() == "{}" and cursor_config().is_symlink()


def test_cursor_with_the_python_fallback_command_puts_the_module_in_the_arguments(agents, capsys, monkeypatch):
    monkeypatch.setattr(service, "sheaf_command", lambda: ["/usr/bin/python3", "-m", "sheafmd"])
    code, out, err = init(capsys, "cursor")
    assert code == 0, err
    entry = json.loads(cursor_config().read_text())["mcpServers"]["sheaf"]
    assert entry == {"command": "/usr/bin/python3", "args": ["-m", "sheafmd", "mcp", "--agent", "cursor"]}


# ── an entry init wrote itself, for a sheaf that has moved ────────────────────
#
# An entry is init's own when it is `<absolute path of a sheaf script> mcp --agent NAME` or
# `<absolute path of a python> -m sheafmd mcp --agent NAME`, with the NAME of that agent and nothing
# else set on it. When the sheaf that runs now is at another path (a second install first on PATH, a
# tool moved from pipx to uv, a moved venv), Gemini and Cursor, whose entry init reads whole from a
# file, are pointed at the sheaf that runs. Claude and Codex are not: what their `mcp get` prints
# leaves out settings a person can have added (claude's timeout and alwaysLoad, codex's tool lists and
# approval modes), and the add or the remove would drop them, so init says what to run.

DOOR = {"claude": "claude-code", "codex": "codex", "gemini": "gemini", "cursor": "cursor"}


def old_entry(agent, command=OLD, head=(), **more):
    return {"command": command, "args": [*head, "mcp", "--agent", DOOR[agent]], **more}


def put_entry(agents, agent, entry):
    """The agent holds `entry` as `sheaf`, where it keeps it."""
    if agent == "gemini":
        agents.install("gemini")
        gemini_settings().parent.mkdir(parents=True)
        gemini_settings().write_text(json.dumps({"theme": "dark", "mcpServers": {"sheaf": entry}}))
    elif agent == "cursor":
        cursor_config().parent.mkdir(parents=True)
        cursor_config().write_text(json.dumps({"other": 1, "mcpServers": {"sheaf": entry}}))
    else:
        agents.install(agent, {"sheaf": entry})


def entry_now(agents, agent):
    if agent == "gemini":
        return json.loads(gemini_settings().read_text())["mcpServers"]["sheaf"]
    if agent == "cursor":
        return json.loads(cursor_config().read_text())["mcpServers"]["sheaf"]
    return agents.servers(agent)["sheaf"]


@pytest.mark.parametrize("agent", ["gemini", "cursor"])
def test_an_entry_init_wrote_for_a_sheaf_at_another_path_is_pointed_at_the_sheaf_that_runs(
        agents, capsys, agent):
    put_entry(agents, agent, old_entry(agent))
    code, out, err = init(capsys, agent)
    assert code == 0, err
    assert entry_now(agents, agent) == {"command": SHEAF, "args": ["mcp", "--agent", DOOR[agent]]}
    assert "updated" in out and SHEAF in out and "Restart" in out
    assert OLD not in out + err


@pytest.mark.parametrize("agent", ["gemini", "cursor"])
def test_a_python_dash_m_entry_of_init_counts_as_its_own_too(agents, capsys, agent):
    put_entry(agents, agent, old_entry(agent, "/usr/bin/python3.12", ("-m", "sheafmd")))
    code, out, err = init(capsys, agent)
    assert code == 0, err
    assert entry_now(agents, agent)["command"] == SHEAF


@pytest.mark.parametrize("agent", ["gemini", "cursor"])
@pytest.mark.parametrize("python", ["/old/pypy3", "/opt/graalpy/bin/graalpy", "/usr/bin/py"])
def test_a_dash_m_entry_of_init_counts_as_its_own_whatever_interpreter_wrote_it(agents, capsys, agent, python):
    """service.sheaf_command() records sys.executable: pypy3 under PyPy, not only python*."""
    put_entry(agents, agent, old_entry(agent, python, ("-m", "sheafmd")))
    code, out, err = init(capsys, agent)
    assert code == 0, err
    assert entry_now(agents, agent)["command"] == SHEAF


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_claude_and_codex_know_an_entry_of_init_at_another_path_but_do_not_replace_it(agents, capsys, agent):
    put_entry(agents, agent, old_entry(agent))
    code, out, err = init(capsys, agent)
    assert code == 1
    assert entry_now(agents, agent) == old_entry(agent)
    assert [c[:2] for c in agents.calls(agent)] == [["mcp", "get"]], "no add and no remove"
    assert "sheaf init wrote" in err and "another path" in err, "it says it is its own, not set up differently"
    assert f"{agent} mcp remove sheaf" in err and f"sheaf init {agent}" in err
    assert OLD not in out + err and not skill().exists()


def test_cursor_the_rest_of_the_file_survives_the_update(agents, capsys):
    put_entry(agents, "cursor", old_entry("cursor"))
    init(capsys, "cursor")
    assert json.loads(cursor_config().read_text())["other"] == 1


@pytest.mark.parametrize("what, make", [
    ("another command", lambda a: old_entry(a, "/opt/tools/other-tool")),
    ("a sheaf with other arguments", lambda a: {"command": OLD, "args": ["serve", "--agent", DOOR[a]]}),
    ("a sheaf for another agent", lambda a: {"command": OLD, "args": ["mcp", "--agent", "someone-else"]}),
    ("a sheaf with something after the arguments", lambda a: {
        "command": OLD, "args": ["mcp", "--agent", DOOR[a], "--extra"]}),
    ("a python that runs another module", lambda a: old_entry(a, "/usr/bin/python3", ("-m", "other"))),
    ("a script called sheaf-old", lambda a: old_entry(a, "/home/u/bin/sheaf-old")),
    ("a bare sheaf, left to the PATH", lambda a: old_entry(a, "sheaf")),
    ("a bare python", lambda a: old_entry(a, "python3", ("-m", "sheafmd"))),
])
@pytest.mark.parametrize("agent", AGENTS)
def test_an_entry_that_is_not_the_shape_init_writes_is_left_alone(agents, capsys, agent, what, make):
    entry = make(agent)
    put_entry(agents, agent, entry)
    code, out, err = init(capsys, agent)
    assert code == 1 and "set up differently" in err
    assert entry_now(agents, agent) == entry
    if agent != "cursor":
        assert agents.adds(agent) == []


@pytest.mark.parametrize("agent", AGENTS)
def test_an_entry_of_init_that_a_person_gave_an_environment_is_left_alone_and_never_printed(
        agents, capsys, agent):
    entry = old_entry(agent, env={"API_KEY": "tok-5b1f09e2"})
    put_entry(agents, agent, entry)
    code, out, err = init(capsys, agent)
    assert code == 1
    assert entry_now(agents, agent) == entry
    assert "tok-5b1f09e2" not in out + err and "API_KEY" not in out + err


# ── a folder init may not enter ──────────────────────────────────────────────

@pytest.mark.parametrize("agent, folder", [
    ("claude", lambda: home() / ".claude" / "skills"),
    ("cursor", lambda: home() / ".cursor"),
    ("gemini", lambda: home() / ".gemini"),
])
def test_a_folder_init_may_not_enter_is_named_in_a_plain_message_not_a_traceback(
        agents, capsys, closed, agent, folder):
    if agent != "cursor":
        agents.install(agent)
    closed(folder())
    code, out, err = init(capsys, agent)
    assert code == 1
    assert str(folder()) in err and "Permission denied" in err and "Traceback" not in err
    if agent != "cursor":
        assert agents.adds(agent) == [], "nothing was changed"


def test_an_os_error_that_is_not_about_permissions_does_not_say_to_fix_permissions(
        agents, capsys, monkeypatch):
    agents.install("claude")

    def full(*a, **k):
        raise OSError(errno.ENOSPC, "No space left on device", str(skill()))
    monkeypatch.setattr(agent_setup, "_check_skill", full)
    code, out, err = init(capsys, "claude")
    assert code == 1 and str(skill()) in err and "No space left on device" in err
    assert "permission" not in err.lower() and agents.adds("claude") == []


@pytest.mark.parametrize("agent", AGENTS)
def test_a_say_that_breaks_after_the_door_is_registered_is_not_taken_for_a_refusal(agents, agent):
    if agent != "cursor":
        agents.install(agent)

    def closed_pipe(text):
        raise BrokenPipeError(errno.EPIPE, "Broken pipe")
    with pytest.raises(BrokenPipeError):
        agent_setup.init(agent, say=closed_pipe)
    if agent == "cursor":
        assert json.loads(cursor_config().read_text())["mcpServers"]["sheaf"]["command"] == SHEAF
    else:
        assert len(agents.adds(agent)) == 1, "the door was registered before the say"


# ── nothing leaves the temporary home ────────────────────────────────────────

@pytest.mark.parametrize("agent", ["claude", "codex", "gemini", "cursor"])
def test_every_agent_writes_only_under_the_home_of_the_test(agents, capsys, tmp_path, agent):
    if agent != "cursor":
        agents.install(agent)
    run = Path(os.environ["XDG_RUNTIME_DIR"])       # the runtime folder is not under tmp_path
    before, before_run = set(tmp_path.rglob("*")), set(run.rglob("*"))
    code, out, err = init(capsys, agent)
    assert code == 0, err
    new = set(tmp_path.rglob("*")) - before
    assert all(p.is_relative_to(home()) or p.name.endswith("-state.json") for p in new), new
    assert set(run.rglob("*")) == before_run


# ── what init says ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("agent", ["claude", "codex", "gemini", "cursor"])
def test_nothing_init_says_names_the_brand(agents, capsys, tmp_path, agent):
    if agent != "cursor":
        agents.install(agent)
    for _ in range(2):                                       # what it did, then that it is done
        code, out, err = init(capsys, agent)
        assert code == 0 and out.strip()
        assert brand_words_in(out + err, tmp_path) == []
    code, out, err = init(capsys, "emacs")
    assert brand_words_in(out + err, tmp_path) == []


# ── one table of agents, and names for the states ────────────────────────────

def test_every_agent_init_knows_is_signed_with_the_name_the_detection_table_gives_it():
    """`--agent` says the name agents/detect.py recognises; a second copy of it could drift."""
    from sheafmd.agents import detect
    known = {a.name for a in detect.TABLE}
    products = {a.name: a.product for a in detect.TABLE}
    for name, spec in agent_setup.AGENT_TABLE.items():
        assert spec.door_name in known, name
        assert products[spec.door_name].startswith(spec.product), name


def test_the_agents_the_help_and_the_parser_name_are_the_ones_of_the_table(capsys):
    names = "|".join(agent_setup.AGENTS)
    assert agent_setup.COMMAND_HELP["init"][0] == f"init {names}"
    with pytest.raises(SystemExit):
        agent_setup.cmd_init(["--help"])
    assert names in capsys.readouterr().out


def test_cursor_is_the_one_agent_whose_file_is_the_interface_and_claude_the_one_with_a_skill():
    assert set(agent_setup.CLI_AGENTS) == {"claude", "codex", "gemini"}
    assert [n for n, s in agent_setup.AGENT_TABLE.items() if s.skill] == ["claude"]


def test_what_a_look_found_is_one_of_the_kinds_and_cannot_be_changed():
    import dataclasses
    assert agent_setup.ABSENT.kind == "absent" and agent_setup.ABSENT.kind is agent_setup.Kind.ABSENT
    with pytest.raises(dataclasses.FrozenInstanceError):
        agent_setup.ABSENT.kind = agent_setup.Kind.OURS
    assert {k.value for k in agent_setup.Kind} == {"absent", "ours", "moved", "other", "unknown"}


def test_the_results_init_reports_are_named(agents, capsys):
    agents.install("codex")
    code, out, err = init(capsys, "codex")
    assert code == 0 and "registered" in out and "Restart Codex" in out
    assert {d.value for d in agent_setup.Done} == {"added", "already", "moved"}
    assert {s.value for s in agent_setup.Skill} == {"new", "replace", "same"}
