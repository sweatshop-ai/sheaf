"""
sheafmd.agent_setup — `sheaf init AGENT`: register the stdio door with an agent (SPEC 14.5).

    sheaf init claude     claude mcp add --scope user sheaf -- <sheaf> mcp --agent claude-code,
                          then the skill in ~/.claude/skills/sheaf/SKILL.md
    sheaf init codex      codex mcp add sheaf -- <sheaf> mcp --agent codex
    sheaf init gemini     gemini mcp add --scope user sheaf <sheaf> -- mcp --agent gemini
    sheaf init cursor     the entry merged into ~/.cursor/mcp.json

`init` never replaces what it did not write. Before it adds, it asks the agent (or reads the
agent's file) whether a server called `sheaf` is there: `codex mcp add` and `gemini mcp add`
replace one without a word. One that is ours (the same command) is left as it is, and one init
wrote for a sheaf at another path is pointed at this one; any other is left alone and said so, with
the command that removes it. A skill file is replaced only when it holds the marker line below,
and the skill is checked first (and again just before it is written), so a refusal changes nothing.
A sheaf that runs from uv's or pipx's cache (`uvx`, `pipx run`) is not registered: that path goes when the cache is cleaned.

Each command is a function `(argv) -> exit code`, registered in COMMANDS and given its usage line in
COMMAND_HELP, which the foot of cli.py merges into its own. This module does not import cli.py.
"""
import argparse
import contextlib
import enum
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata, resources
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

from . import paths
from .atomic import write_text_atomic
from .hub import service

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

COMMANDS: dict = {}
COMMAND_HELP: dict = {}

NAME = "sheaf"
MARKER = "<!-- written by sheaf init; sheaf may replace it -->"
SKILL_FILE = "agent_files/claude-skill.md"
ASK_SECONDS = 60


class Done(enum.StrEnum):
    """What init did to the door of an agent."""
    ADDED = "added"
    ALREADY = "already"
    MOVED = "moved"          # init's own entry for another sheaf, now for this one


class Skill(enum.StrEnum):
    """What init does to the skill file."""
    NEW = "new"
    REPLACE = "replace"
    SAME = "same"


# What init says for each result: its sign, then what follows "the sheaf door is" for an agent's own
# command, and for Cursor's file.
_DONE = {Done.ADDED: ("+", "registered", "now in"),
         Done.ALREADY: ("=", "already registered", "already in"),
         Done.MOVED: ("~", "updated, to run {command}", "updated, to run {command}, in")}


class SetupError(Exception):
    """A message for a person: what init did not do, and what to do instead."""


def _out(line: str = ""):
    print(line)


def _err(line: str = ""):
    print(line, file=sys.stderr)


def installed_from() -> str | None:
    """The `direct_url.json` (PEP 610) of the sheafmd that is running: where `uvx --from` or
    `uv tool install` got it from. None when it came from an index, which records nothing."""
    try:
        return metadata.distribution("sheafmd").read_text("direct_url.json")
    except (metadata.PackageNotFoundError, OSError):
        return None        # a record that cannot be read is no record: the advice falls back to the index


class _Source(NamedTuple):
    spec: str            # the requirement `uv tool install` takes
    left_out: bool       # the URL had a query or a fragment, which `spec` leaves out


def _install_source() -> _Source:
    spec, left_out = "sheafmd", False
    try:
        source = json.loads(installed_from() or "")
        parts = urlsplit(source["url"])
        userinfo, _, host = parts.netloc.rpartition("@")
        netloc = parts.netloc if userinfo in ("", "git") else host
        left_out = bool(parts.query or parts.fragment)
        url = parts._replace(netloc=netloc, query="", fragment="").geturl()
        commit = source.get("vcs_info", {}).get("commit_id")
        spec = f"sheafmd @ git+{url}@{commit}" if commit else f"sheafmd @ {url}"
        if source.get("subdirectory"):
            spec += f"#subdirectory={source['subdirectory']}"
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    return _Source(spec, left_out)


def _line(source: _Source) -> str:
    return shlex.join(["uv", "tool", "install", source.spec])


def install_line() -> str:
    """The command that installs this same sheaf for good: the pinned revision when it came from
    git, the URL it came from otherwise (with its `subdirectory`), and `sheafmd` from the index when
    there is no record. A credential in the URL, a password or a token as the user name, is left
    out (only ssh's own `git@` stays), and so are its query and fragment, where a signed link keeps
    its token: the line goes to a terminal, and into a transcript."""
    return _line(_install_source())


def install_advice() -> str:
    """`install_line`, and under it, when the URL had a query or a fragment, a line saying that it
    was left out, so a person whose link needs it knows to add it."""
    source = _install_source()
    line = _line(source)
    if not source.left_out:
        return line
    return f"{line}\n  (the URL had a query or a fragment, which is left out of that line; add it if the link needs it)"


def door_command(agent: str) -> list[str]:
    """The command an agent runs for the stdio door: the absolute sheaf command, `mcp --agent`."""
    return [*service.sheaf_command(), "mcp", "--agent", AGENT_TABLE[agent].door_name]


def _entry(command: list[str]) -> dict:
    """The server entry a JSON file keeps for the door: Gemini's settings, Cursor's mcp.json."""
    return {"command": command[0], "args": command[1:]}


# ── what an agent already holds under the name `sheaf` ───────────────────────

class Kind(enum.StrEnum):
    ABSENT = "absent"
    OURS = "ours"
    MOVED = "moved"        # ours, for a sheaf at another path
    OTHER = "other"        # a server of that name, set up differently
    UNKNOWN = "unknown"    # sheaf could not tell


@dataclass(frozen=True)
class Found:
    kind: Kind
    detail: str = ""     # for UNKNOWN: why sheaf could not tell. Never what a server holds: it can carry a token


ABSENT = Found(Kind.ABSENT)


def _ours_at_another_path(found_command, found_args: list, command: list[str]) -> bool:
    """Is this an entry init itself would have written, for a sheaf at another path: `</abs/path/to/a
    sheaf script> mcp --agent NAME`, or `</abs/path/to/an/interpreter> -m sheafmd mcp --agent NAME` (`sys.executable` is whatever runs sheaf:
    python3, pypy3, ...), with this agent's NAME
    (the tail of `command`, which `door_command` made)?"""
    if not isinstance(found_command, str) or not os.path.isabs(found_command) \
            or found_args[-3:] != command[-3:]:
        return False               # init writes the absolute path: a bare `sheaf` was left to the PATH on purpose
    name = Path(found_command).name
    return ((found_args[:-3] == [] and name == service.SCRIPT)
            or found_args[:-3] == ["-m", service.MODULE])


def _compare(found_command, found_args, command: list[str], plain: bool = True) -> Found:
    """`plain` is false when the entry holds more than a command and arguments (an environment, a
    working folder, a switch): one that a person has set up further is not replaced."""
    if not isinstance(found_args, list):
        return Found(Kind.OTHER)          # no entry of ours has arguments that are not a list
    if found_command == command[0] and found_args == command[1:]:
        return Found(Kind.OURS)
    if plain and _ours_at_another_path(found_command, found_args, command):
        return Found(Kind.MOVED)
    return Found(Kind.OTHER)


def _compare_json_entry(entry, command: list[str]) -> Found:
    """An entry of a JSON file that an agent keeps its servers in: Gemini's settings, Cursor's mcp.json."""
    if not isinstance(entry, dict) or "command" not in entry:
        return Found(Kind.OTHER)
    return _compare(entry["command"], entry.get("args") or [], command,
                    plain=set(entry) <= {"command", "args"})


def _ask(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run an agent's own command and keep what it said. Its standard input is closed: a prompt
    would hang the command."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=ASK_SECONDS, cwd=cwd,
                              stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise SetupError(f"`{shlex.join(argv)}` did not answer in {ASK_SECONDS} s")
    except OSError as e:
        raise SetupError(f"`{shlex.join(argv)}` could not run: {e}")


def _said(r: subprocess.CompletedProcess) -> str:
    return " ".join(f"{r.stdout or ''} {r.stderr or ''}".split())


def _no_such_server(r: subprocess.CompletedProcess) -> bool:
    return r.returncode != 0 and "no mcp server" in _said(r).lower()


def _did_not_say(argv: list[str], r: subprocess.CompletedProcess) -> str:
    """What init says of an agent's command in place of what the command said: when its config will
    not parse, codex quotes the offending line of config.toml and claude names the token its parser
    stopped at, and that line can be a token."""
    what = f"failed (exit {r.returncode})" if r.returncode else "answered in a way sheaf cannot read (exit 0)"
    return f"`{shlex.join(argv)}` {what}, and sheaf does not print its answer, because that can quote the entry"


def _unknown(argv: list[str], r: subprocess.CompletedProcess) -> Found:
    return Found(Kind.UNKNOWN, f"{_did_not_say(argv, r)}. Run it yourself to read it")


def _neutral_folder() -> Path:
    """A folder that is no project of any agent: the home directory, or the temporary one where
    there is no home folder."""
    home = Path.home()
    return home if home.is_dir() else Path(tempfile.gettempdir())


def _look_claude(exe: str, command: list[str]) -> Found:
    argv = [exe, "mcp", "get", NAME]
    # `claude mcp get` shows the entry of the project it is run in before the user's, and
    # `claude mcp add sheaf` with no scope makes one. From a folder that is no project it shows the user's.
    r = _ask(argv, _neutral_folder())
    if _no_such_server(r):
        return ABSENT
    if r.returncode != 0:
        return _unknown(argv, r)
    answer_lines = r.stdout.splitlines()
    lines = {k.strip(): v.strip() for k, _, v in (ln.partition(":") for ln in answer_lines)}
    if "Scope" not in lines:
        return _unknown(argv, r)
    if not lines["Scope"].lower().startswith("user"):
        return ABSENT              # a project's own entry: the user scope has none, and the add refuses a second there
    if "Command" in lines:
        env_lines = next((answer_lines[i + 1:i + 2] for i, ln in enumerate(answer_lines)
                          if ln.strip() == "Environment:"), [])
        return _compare(lines["Command"], lines.get("Args", "").split(), command,
                        plain=not any(ln.strip() for ln in env_lines))
    if lines.get("Type", "stdio").lower() != "stdio":
        return Found(Kind.OTHER)      # an HTTP or SSE server: set up differently
    return _unknown(argv, r)


def _codex_holds_only_the_command(answer: dict) -> bool:
    """`codex mcp add` writes a command and arguments and nothing else, so an entry with an
    environment, a working folder, a switch, a tool list or a timeout set on it is one a person set
    up further (codex-cli 0.147.0 prints null for each of these when nothing is set)."""
    transport = answer["transport"]
    settings = [v for k, v in answer.items() if k not in ("name", "transport", "enabled")]
    return (answer.get("enabled", True) is True
            and not (transport.get("env") or transport.get("env_vars") or transport.get("cwd"))
            and all(v in (None, [], {}) for v in settings))


def _look_codex(exe: str, command: list[str]) -> Found:
    argv = [exe, "mcp", "get", NAME, "--json"]
    r = _ask(argv)
    if _no_such_server(r):
        return ABSENT
    if r.returncode != 0:
        return _unknown(argv, r)
    try:
        answer = json.loads(r.stdout)
        transport = answer["transport"]
    except (ValueError, KeyError, TypeError):
        return _unknown(argv, r)
    if not isinstance(transport, dict):
        return _unknown(argv, r)
    if "command" in transport:
        return _compare(transport["command"], transport.get("args") or [], command,
                        plain=_codex_holds_only_the_command(answer))
    if isinstance(transport.get("type"), str) and transport["type"] != "stdio":
        return Found(Kind.OTHER)      # streamable_http: set up differently
    return _unknown(argv, r)


def gemini_path() -> Path:
    """Gemini's user scope. `GEMINI_CLI_HOME` replaces the home directory for gemini itself, so
    `gemini mcp add --scope user` writes under it; looking in ~/.gemini would miss a server that
    the add then replaces."""
    base = os.environ.get("GEMINI_CLI_HOME")
    root = Path(os.path.abspath(base)) if base else Path.home()
    return root / ".gemini" / "settings.json"


def _read_servers(path: Path, blank_ok: bool) -> tuple[dict, object]:
    """The JSON file an agent keeps its servers in, and its `mcpServers` object (made if there is none;
    not a dict if the file holds something else). `blank_ok`: a file with only whitespace is an empty
    object. Raises OSError or ValueError when the file cannot be read as plain JSON."""
    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if text.strip() or not blank_ok else {}
    return data, (data.setdefault("mcpServers", {}) if isinstance(data, dict) else None)


def _look_gemini(exe: str, command: list[str]) -> Found:
    """Gemini has no command that says what one server holds, so the file its user scope writes is
    read. A file that is not plain JSON (it allows comments) cannot be read, and then the answer is
    not guessed."""
    path = gemini_path()
    # Not `Path.exists`, which says False behind a closed folder from Python 3.14 on: init would take
    # a file it cannot see for an absent one and register the door before the write that then fails.
    if not paths.exists(path):
        return ABSENT
    try:
        _, servers = _read_servers(path, blank_ok=False)
    except (OSError, ValueError) as e:
        return Found(Kind.UNKNOWN, f"{path} cannot be read as JSON ({e})")
    if not isinstance(servers, dict):
        return Found(Kind.UNKNOWN, f"{path} has no mcpServers object sheaf can read")
    if NAME not in servers:
        return ABSENT
    return _compare_json_entry(servers[NAME], command)


@dataclass
class CliAgent:
    """An agent with a command of its own to register a server."""
    exe: str
    look: Callable[[str, list[str]], Found]
    add: Callable[[str, list[str]], list[str]]     # (exe, command) -> argv
    remove: str                # how to take a server called sheaf away, for the message
    sees_all: bool = False        # the look reads the entry whole (Gemini's file), so a replace drops nothing unseen
    add_replaces: bool = True     # the add replaces a server of the same name without a word; Claude's refuses


@dataclass(frozen=True)
class AgentSpec:
    """What init knows of one agent. Adding an agent is one row of AGENT_TABLE, plus the way it is looked
    at and written if it is not one of the four below. `door_name` and `product` repeat agents/detect.py
    TABLE; tests/test_init.py pins them against it (the product there is the page's wording: "Codex CLI")."""
    door_name: str                    # what `--agent` says: the name its replies are signed from
    product: str                      # how init names it when it says to restart it
    cli: CliAgent | None = None       # None: the agent's file is the interface (Cursor)
    skill: bool = False               # init also installs the skill


AGENT_TABLE = {
    "claude": AgentSpec("claude-code", "Claude Code", skill=True, cli=CliAgent(
        "claude", _look_claude,
        lambda exe, cmd: [exe, "mcp", "add", "--scope", "user", NAME, "--", *cmd],
        "claude mcp remove sheaf", add_replaces=False)),
    "codex": AgentSpec("codex", "Codex", cli=CliAgent(
        "codex", _look_codex,
        lambda exe, cmd: [exe, "mcp", "add", NAME, "--", *cmd],
        "codex mcp remove sheaf")),
    "gemini": AgentSpec("gemini", "Gemini CLI", cli=CliAgent(
        "gemini", _look_gemini,
        lambda exe, cmd: [exe, "mcp", "add", "--scope", "user", NAME, cmd[0], "--", *cmd[1:]],
        "gemini mcp remove --scope user sheaf", sees_all=True)),
    "cursor": AgentSpec("cursor", "Cursor"),
}
AGENTS = tuple(AGENT_TABLE)
CHOICES = "|".join(AGENTS)
CLI_AGENTS = {name: spec.cli for name, spec in AGENT_TABLE.items() if spec.cli is not None}


def _cannot_tell(spec: CliAgent, command: list[str], found: Found) -> SetupError:
    by_hand = shlex.join(spec.add(spec.exe, command))
    return SetupError(f"sheaf cannot tell whether {spec.exe} already has a server called sheaf, "
                      f"and the add would replace one without a word: {found.detail}. If there is "
                      f"none, run this yourself:\n  {by_hand}")


def _register(agent: str, command: list[str]) -> Done:
    """Make the agent hold the door. Returns ADDED, ALREADY, or MOVED (init's own entry for another
    sheaf, now for this one: Gemini only, see `sees_all`), or raises SetupError."""
    spec = CLI_AGENTS[agent]
    exe = shutil.which(spec.exe)
    if exe is None:
        by_hand = shlex.join(spec.add(spec.exe, command))
        then = f"; then run `sheaf init {agent}` again to install the skill" if AGENT_TABLE[agent].skill else ""
        raise SetupError(f"{spec.exe} is not on PATH, so sheaf cannot register itself with it. "
                         f"Run this yourself where {spec.exe} is installed:\n  {by_hand}{then}")
    with _looks(agent):
        found = spec.look(exe, command)
    if found.kind == Kind.OURS:
        return Done.ALREADY
    if found.kind == Kind.OTHER:
        raise SetupError(f"{spec.exe} already has a server called sheaf, set up differently. "
                         f"sheaf init does not replace what it did not write, and does not print "
                         f"it, because it can hold a token. To replace it: {spec.remove}, then run "
                         f"`sheaf init {agent}` again.")
    if found.kind == Kind.UNKNOWN:
        raise _cannot_tell(spec, command, found)
    if found.kind == Kind.MOVED and not spec.sees_all:
        raise SetupError(f"{spec.exe} has the sheaf door that sheaf init wrote for a sheaf at another path, "
                         f"and sheaf init does not replace it: what {spec.exe} says about an entry leaves "
                         f"out settings a person can have added by hand (a timeout, a tool list), and "
                         f"replacing it would drop them. To point it at this sheaf: {spec.remove}, "
                         f"then run `sheaf init {agent}` again.")
    # Another command can register a sheaf between the look and the add, which would replace it. A
    # second look just before the add narrows that to the add's own start; nothing closes it.
    with _looks(agent):
        again = spec.look(exe, command) if spec.add_replaces else found
    if again.kind == Kind.UNKNOWN:
        raise _cannot_tell(spec, command, again)
    if again.kind != found.kind:
        raise SetupError(f"{spec.exe} changed what it holds under the name sheaf while sheaf init "
                         f"looked, and the add replaces a server of that name without a word, so "
                         f"sheaf init changes nothing. Run `sheaf init {agent}` again.")
    argv = spec.add(exe, command)
    r = _ask(argv)
    if r.returncode != 0:
        raise SetupError(f"`{shlex.join(argv)}` failed (exit {r.returncode}), and sheaf does not "
                         f"print its answer, because that can quote a line of the config, a token "
                         f"among them. Run it yourself to read it")
    return Done.MOVED if found.kind == Kind.MOVED else Done.ADDED


# ── the skill (Claude Code) ──────────────────────────────────────────────────

def skill_text() -> str:
    return resources.files("sheafmd").joinpath(SKILL_FILE).read_text(encoding="utf-8")


def skill_path() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    root = Path(os.path.abspath(os.path.expanduser(base))) if base else Path.home() / ".claude"
    return root / "skills" / NAME / "SKILL.md"


def written_by_init(text: str) -> bool:
    """The marker is the first line of the file, or the line right after its front matter (SPEC
    14.5): Claude Code reads the front matter only when it opens the file, so the marker cannot come
    before it. Not the first non-blank line: a file where something else comes first is not init's."""
    lines = text.splitlines()
    at = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i, ln in enumerate(lines[1:], 1) if ln.strip() == "---"), None)
        if end is None:
            return False
        at = end + 1
    return at < len(lines) and lines[at].strip() == MARKER


def _check_skill() -> Skill:
    """What init would do to the skill file. Raises SetupError when the
    file is not sheaf's to touch."""
    target = skill_path()
    if target.parent.is_symlink() or target.is_symlink():
        raise SetupError(f"{target if target.is_symlink() else target.parent} is a link, and sheaf "
                         "init does not write through a link. Remove the link, or install the "
                         "skill by hand from the sheaf project.")
    if not paths.exists(target):
        return Skill.NEW
    if not target.is_file():
        raise SetupError(f"{target} is not a file, and sheaf init leaves it alone")
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, ValueError) as e:
        raise SetupError(f"{target} cannot be read ({e}), and sheaf init leaves it alone")
    if not written_by_init(text):
        raise SetupError(f"{target} exists and sheaf did not write it (it lacks the line "
                         f"`{MARKER}`), so sheaf init leaves it alone. Move it aside and run "
                         "`sheaf init claude` again.")
    return Skill.SAME if text == skill_text() else Skill.REPLACE


def _install_skill(state: Skill) -> Skill:
    if state == Skill.SAME:
        return Skill.SAME
    target = skill_path()
    try:
        write_text_atomic(target, skill_text(), check=_check_skill)
    except OSError as e:
        raise SetupError(f"the skill could not be written to {target}: {e}")
    return state


# ── Cursor: the file is the interface ────────────────────────────────────────

def cursor_path() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def _by_hand(command: list[str]) -> str:
    return json.dumps({"mcpServers": {NAME: _entry(command)}}, indent=2)


def _stamp(path: Path):
    """What tells one state of a file from another without reading it: which file the name holds,
    its size and when it was last written. None when there is none."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns


def _init_cursor(command: list[str]) -> Done:
    path = cursor_path()
    if path.is_symlink():
        raise SetupError(f"{path} is a link, and sheaf init does not write through a link. Add this "
                         f"to the file it points to:\n{_by_hand(command)}")
    mode = 0o600
    moved = False
    data: dict = {}
    # Taken before the read, so a write during it counts as a change too.
    seen = _stamp(path)

    def check_unchanged():
        # Cursor locks nothing, so a write between this look and the replace is still lost; the
        # window is that of two lines of Python.
        if _stamp(path) != seen:
            raise SetupError(f"{path} changed while sheaf init read it and wrote it, so sheaf init "
                             f"leaves it as it is now. Run `sheaf init cursor` again.")
    if path.exists():
        mode = path.stat().st_mode & 0o7777
        try:
            data, servers = _read_servers(path, blank_ok=True)
        except (OSError, ValueError) as e:
            raise SetupError(f"{path} cannot be read as plain JSON ({e}), so sheaf init leaves it "
                             f"alone. Add this to it yourself:\n{_by_hand(command)}")
        if not isinstance(servers, dict):
            raise SetupError(f"{path} has no mcpServers object sheaf can add to, so sheaf init "
                             f"leaves it alone. Add this to it yourself:\n{_by_hand(command)}")
        if NAME in servers:
            found = _compare_json_entry(servers[NAME], command)
            if found.kind == Kind.OURS:
                return Done.ALREADY
            if found.kind == Kind.OTHER:
                raise SetupError(f"{path} already has a server called sheaf, set up differently. "
                                 f"sheaf init does not replace what it did not write, and does not "
                                 f"print it, because it can hold a token. To replace it, delete that "
                                 f"entry and run `sheaf init cursor` again.")
            moved = True
    else:
        data = {"mcpServers": {}}
    data["mcpServers"][NAME] = _entry(command)
    try:
        write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n", mode, check=check_unchanged)
    except OSError as e:
        raise SetupError(f"{path} could not be written: {e}")
    return Done.MOVED if moved else Done.ADDED


# ── the command ──────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _looks(agent: str):
    """The looks of init: reading what is there. A file or folder the person's account may not enter
    (`paths.exists` raises on it, as `open` does) is a refusal like the others, named, and not a
    traceback. Only the looks are wrapped: an OSError from `say` after the door is registered
    (a closed pipe) is not a refusal, and init must not say it left things alone."""
    try:
        yield
    except OSError as e:
        raise SetupError(f"{e.filename or 'a file it needed'} cannot be used: {e.strerror or e}. sheaf init "
                         f"leaves it alone; once that is fixed, run `sheaf init {agent}` again.")


def init(agent: str, say=_out) -> None:
    """Set one agent up. Everything that can refuse is checked before anything is written."""
    _set_up(agent, say)


def _set_up(agent: str, say) -> None:
    spec = AGENT_TABLE[agent]
    with _looks(agent):
        command = door_command(agent)
        cache = service.runs_from_a_cache(command)
    if cache:
        raise SetupError(f"{service.cache_refusal(cache, command[0])} An agent registered with that path "
                         f"would lose sheaf then, so init registers nothing. Install sheaf, then run "
                         f"init again:\n  {install_advice()}\n  sheaf init {agent}")
    if spec.cli is None:
        with _looks(agent):
            done = _init_cursor(command)
        sign, _, where = _DONE[done]
        say(f"  {sign} {agent}: the sheaf door is {where.format(command=shlex.join(command))} {cursor_path()}")
        changed = done != Done.ALREADY
    else:
        with _looks(agent):
            skill = _check_skill() if spec.skill else None
        done = _register(agent, command)
        sign, what, _ = _DONE[done]
        say(f"  {sign} {agent}: the sheaf door is {what.format(command=shlex.join(command))}")
        changed = done != Done.ALREADY
        if skill is not None:
            result = _install_skill(skill)
            say({Skill.SAME: f"  = {agent}: the skill at {skill_path()} is up to date",
                 Skill.NEW: f"  + {agent}: the skill is written to {skill_path()}",
                 Skill.REPLACE: f"  ~ {agent}: the skill at {skill_path()} is updated"}[result])
            changed = changed or result != Skill.SAME
    if changed:
        say(f"  Restart {spec.product} to load it.")


def cmd_init(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="sheaf init", usage=f"sheaf init {CHOICES}",
        description="Register sheaf with an agent, using that agent's own command: the agent runs "
                    "`sheaf mcp`, the MCP door, so it can read and answer the comments of a "
                    "document. For Claude Code it also installs the skill. Nothing the agent holds "
                    "that sheaf did not write is replaced.")
    p.add_argument("agent", choices=AGENTS, metavar=CHOICES)
    args = p.parse_args(argv)
    try:
        init(args.agent)
    except SetupError as e:
        _err(f"sheaf: {e}")
        return EXIT_FAILED
    return EXIT_OK


COMMANDS.update({"init": cmd_init})
COMMAND_HELP.update({
    "init": (f"init {CHOICES}",
             "register sheaf with an agent (and install the skill for Claude Code)"),
})
