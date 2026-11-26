"""
sheafmd.config — the two config files a person writes (SPEC 4.3, 4.4).

    config.toml    per user: port, name, browser          (paths.config_file())
    .sheaf.toml    per root: theme, for, links, link_tlds, credit

Every key is optional. An unknown key prints a warning that names the file; a TOML
error stops the command and names the file and the line. theme.py reads theme.toml
through `read_toml` too, so the three files fail the same way.
"""
import os
import re
import subprocess
import sys
import threading
import tomllib
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from . import paths
from .hub.auth import clean_display

DEFAULT_PORT = 27419
ROOT_FILE = ".sheaf.toml"

USER_KEYS = {"port": int, "name": str, "browser": bool, "proxy": dict, "jump": dict,
             "reopen": dict, "list": dict, "transcribe": dict, "tiroir": str, "block_editor": bool}   # proxy: hub.proxy reads it (9.9); list: hub.the_list (9.10); transcribe: hub.transcribe
JUMP_KEYS = {"command": list}
ROOT_KEYS = {"theme": str, "for": str, "links": bool, "link_tlds": list, "credit": bool,
             "versions": str, "commit": bool, "push": bool, "tiroir": str, "branch": str,
             "archive_after": object}      # object: a bad number warns and the default holds, it does not stop the hub

_ENDING = re.compile(r"[a-z0-9]+")


class ConfigError(Exception):
    """A config file that cannot be used. The message names the file."""


def _stderr(line: str):
    print(line, file=sys.stderr)


def read_toml(path: Path, keys: dict, warn=None) -> dict:
    """The table in `path`, with its keys checked against `keys` ({name: type}).

    A missing file is an empty table. A key of the wrong type stops the command;
    an unknown key only warns."""
    warn = warn or _stderr
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except UnicodeDecodeError:
        raise ConfigError(f"{path}: is not UTF-8 text")
    except OSError as e:
        raise ConfigError(f"{path}: cannot be read ({e.strerror or e})")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}")
    for key, value in data.items():
        want = keys.get(key)
        if want is None:
            warn(f"  ! unknown key '{key}' in {path}")
        elif not isinstance(value, want) or (want is int and isinstance(value, bool)):
            raise ConfigError(f"{path}: '{key}' must be {_TYPE_WORDS[want]}, not {value!r}")
    return data


_TYPE_WORDS = {int: "a number", str: "text", bool: "true or false", list: "a list", dict: "a table"}


# ── config.toml ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UserConfig:
    port: int | None = None
    name: str | None = None
    browser: bool | None = None
    tiroir: str | None = None     # the laptop's default tiroir: https://host (SPEC 13)


def load_user_config(warn=None) -> UserConfig:
    path = paths.config_file()
    data = read_toml(path, USER_KEYS, warn)
    port = data.get("port")
    if port is not None and not 0 < port < 65536:
        raise ConfigError(f"{path}: 'port' must be between 1 and 65535, not {port}")
    return UserConfig(port=port, name=data.get("name") or None, browser=data.get("browser"), tiroir=data.get("tiroir") or None)


def block_editor(warn=None) -> bool:
    """Whether the page edits in the block editor (SPEC 4.3): `SHEAF_BLOCK_EDITOR=1` or `0`, then `block_editor`, then false."""
    v = os.environ.get("SHEAF_BLOCK_EDITOR", "").strip()
    if v:
        return v not in ("0", "false")
    return bool(read_toml(paths.config_file(), USER_KEYS, warn).get("block_editor"))


def port(warn=None) -> int:
    """SHEAF_PORT, then `port`, then 27419."""
    v = os.environ.get("SHEAF_PORT", "").strip()
    if v:
        if not (v.isascii() and v.isdigit()) or not 0 < int(v) < 65536:
            raise ConfigError(f"SHEAF_PORT={v!r} is not a port number")
        return int(v)
    return load_user_config(warn).port or DEFAULT_PORT


def jump_command(warn=None) -> list[str] | None:
    """The argv of the `[jump]` table (SPEC 4.3), or None when there is no table."""
    return _command_table("jump", warn)


def reopen_command(warn=None) -> list[str] | None:
    """The argv of the `[reopen]` table (SPEC 4.3): what opens an ended session again for a Tell. None
    when there is no table."""
    return _command_table("reopen", warn)


def _command_table(name: str, warn=None) -> list[str] | None:
    """The argv of a table that holds one `command`. A list of non-empty text: a string would need a
    shell, and none is ever started."""
    warn = warn or _stderr
    path = paths.config_file()
    table = read_toml(path, USER_KEYS, warn).get(name)
    if table is None:
        return None
    for key in table:
        if key not in JUMP_KEYS:
            warn(f"  ! unknown key '{key}' in [{name}] of {path}")
    command = table.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(a, str) and a for a in command):
        raise ConfigError(f"{path}: 'command' in [{name}] must be a list of text, the program and its "
                          f"arguments, such as [\"curl\", \"-s\"]")
    return command


def tell_wait() -> int:
    """SHEAF_TELL_WAIT, then 600: the seconds a Tell waits for the agent's reply (SPEC 8.9)."""
    v = os.environ.get("SHEAF_TELL_WAIT", "").strip()
    if not v:
        return 600
    if not (v.isascii() and v.isdigit()) or int(v) < 1:
        raise ConfigError(f"SHEAF_TELL_WAIT={v!r} is not a number of seconds")
    return int(v)


def user_name(warn=None) -> str:
    """SHEAF_NAME, then `name`, then `git config user.name`, then the login name, then
    `author`. Each source is cleaned by the display-name rule (SPEC 12) and one that has
    nothing left is not a name: the next is tried."""
    def git_name() -> str:
        try:
            r = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True,
                               errors="replace", timeout=5)
            return r.stdout if r.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    sources = (
        lambda: os.environ.get("SHEAF_NAME", ""),
        lambda: load_user_config(warn).name or "",
        git_name,
        lambda: os.environ.get("USER", ""),
        lambda: os.environ.get("USERNAME", ""),
    )
    for source in sources:
        if name := clean_display(source()):
            return name
    return "author"


def browser_enabled(warn=None) -> bool:
    """SHEAF_NO_BROWSER=1 turns it off, then `browser`, then true."""
    if os.environ.get("SHEAF_NO_BROWSER", "").strip() == "1":
        return False
    b = load_user_config(warn).browser
    return True if b is None else b


# ── .sheaf.toml ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RootConfig:
    theme: str | None = None       # a built-in name, or a folder relative to the root
    for_: str | None = None        # byline: "Document prepared by <by> for <for>"
    links: bool = True             # the link rule (6.6)
    link_tlds: tuple[str, ...] = ()
    credit: bool = False           # the page credit line (6.7)
    versions_inside: bool = False  # `versions = "root"`: the versions store at `.sheaf/versions/` (7.4)
    commit: bool = False           # every write on the page is a git commit of who made it (8.11)
    push: bool = False             # and the hub pushes it (8.11)
    tiroir: str | None = None      # where a loose page of this root is sent: https://host (SPEC 13)
    branch: str | None = None      # the branch the tiroir saves a repo's pages on when the repo has no `dev` (SPEC 14)
    archive_after: int = 30        # days without a write or a comment before a loose page is archived (8.6)


def load_root_config(root: Path, warn=None) -> RootConfig:
    """`.sheaf.toml` at the top of `root`; without the file, the defaults. Never read
    from a subfolder."""
    warn = warn or _stderr
    path = Path(root) / ROOT_FILE
    data = read_toml(path, ROOT_KEYS, warn)
    tlds = []
    for raw in data.get("link_tlds", []):
        e = str(raw).strip().lower().lstrip(".")
        if _ENDING.fullmatch(e):
            tlds.append(e)
        else:
            warn(f"  ! link_tlds in {path}: {raw!r} is not a domain ending; ignored")
    versions = data.get("versions", "state")
    if versions not in ("state", "root"):
        warn(f"  ! versions in {path}: {versions!r} is neither \"state\" nor \"root\"; the state folder is used")
    after = data.get("archive_after", 30)
    if isinstance(after, bool) or not isinstance(after, int) or after < 1:
        warn(f"  ! archive_after in {path}: {after!r} is not a whole number of days, at least 1; 30 is used")
        after = 30
    return RootConfig(theme=data.get("theme") or None, archive_after=after, for_=data.get("for") or None,
                      links=data.get("links", True), link_tlds=tuple(tlds),
                      credit=data.get("credit", False), versions_inside=versions == "root",
                      commit=data.get("commit", False), push=data.get("push", False),
                      tiroir=data.get("tiroir") or None, branch=data.get("branch") or None)


def branch_named(text: str) -> str | None:
    """The `branch` a `.sheaf.toml` says, given as text (a repo's file read from git, not a work tree's); None when it
    names none, is not TOML or gives a thing that is no branch name."""
    try:
        branch = tomllib.loads(text).get("branch")
    except tomllib.TOMLDecodeError:
        return None
    return branch if isinstance(branch, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", branch) \
        and ".." not in branch and not branch.endswith((".lock", "/", ".")) else None


def tiroir_named(text: str) -> str | None:
    """The `tiroir` a `.sheaf.toml` says, given as text (a repo's file read from git); None when it names none or is not TOML."""
    try:
        named = tomllib.loads(text).get("tiroir")
    except tomllib.TOMLDecodeError:
        return None
    return named if isinstance(named, str) and named.strip() else None


class GitPlace(NamedTuple):
    top: Path | None            # the top of the git work tree the folder is in; each worktree is its own
    in_git_dir: bool            # inside a git directory, where no work tree is the folder's


def _rev_parse(folder: Path, *asks: str):
    """`git rev-parse` asked in `folder`, its output read as the file system's bytes; None when git does
    not run."""
    try:
        return subprocess.run(["git", "-C", str(folder), "rev-parse", *asks], capture_output=True,
                              encoding="utf-8", errors="surrogateescape", timeout=5,
                              env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return None


_remembered = threading.local()      # the thread's `git_places_remembered` memo: {folder: GitPlace}, None outside one


@contextmanager
def git_places_remembered():
    """Within it, this thread asks git once for each folder (SPEC 8.2): a listing judges every page against the same few folders,
    and a run per page and rule took 48-51 s for 1067 pages. The answers are dropped when it ends, so the next listing, and
    every other caller, asks git afresh; a nested use shares the outer one's."""
    if getattr(_remembered, "places", None) is not None:
        yield
        return
    _remembered.places, _remembered.fs = {}, {}
    try:
        yield
    finally:
        _remembered.places = _remembered.fs = None


def remembered_fs(kind: str, path, asked: Callable):
    """`asked(path)`, once per `kind` and path within `git_places_remembered` (the same listing, the same lifetime): what a listing
    asks of the file system about a folder (where it really is, whether it is shaped like a git directory) it asked for every page,
    and for every folder above it. Outside one, asked afresh."""
    answers = getattr(_remembered, "fs", None)
    if answers is None:
        return asked(path)
    if (kind, path) not in answers:
        answers[kind, path] = asked(path)
    return answers[kind, path]


def realpath(path) -> str:
    """`os.path.realpath(path)`, asked once for each path within `git_places_remembered` (SPEC 8.12): a listing asked for the same
    few paths, the roots and their folders, for every page and rule, 53,867 times for 1,685 paths, a third of its time."""
    return remembered_fs("real", os.fspath(path), os.path.realpath)


def real_path(path) -> Path:
    """Where `path` really is (SPEC 8.2): like `os.path.realpath`, but a file that is no link is placed in its folder's real folder,
    asked once per folder within `git_places_remembered`, since a listing resolved the same few folders for every page. A link is
    resolved itself."""
    path = Path(path)
    if os.path.islink(path):
        return Path(os.path.realpath(path))
    return Path(realpath(path.parent)) / path.name


def git_place(folder: Path) -> GitPlace:
    places = getattr(_remembered, "places", None)
    if places is None:
        return _git_place_asked(folder)
    if folder not in places:
        places[folder] = _git_place_asked(folder)
    return places[folder]


def _git_place_asked(folder: Path) -> GitPlace:
    """Where `folder` stands to git (SPEC 8.2): inside a work tree, which has a top, or inside a git
    directory: a repository's `.git` folder, a bare repository, a submodule's git directory, or a
    folder in one. Only the top, asked last, can hold a newline. A folder git finds in a repository
    but outside its work tree is inside the git directory only when it lies at or under the one git
    names (the top of a submodule's, where git names the submodule's work tree); the folders beside a
    bare repository's worktrees are not. A bare repository git refuses to use (`safe.bareRepository`)
    is inside one too."""
    r = _rev_parse(folder, "--is-inside-git-dir", "--is-inside-work-tree", "--show-toplevel")
    if r is None:
        return GitPlace(None, False)
    in_git_dir, in_work_tree, top = (r.stdout.split("\n", 2) + ["", ""])[:3]
    if in_work_tree == "true" and r.returncode == 0:
        return GitPlace(Path(realpath(top.removesuffix("\n"))), False)
    if in_git_dir == "true" or re.search(r"^fatal: cannot use bare repository", r.stderr, re.M):
        return GitPlace(None, True)
    g = _rev_parse(folder, "--absolute-git-dir") if in_git_dir == "false" else None
    if g is None or g.returncode != 0 or not g.stdout.removesuffix("\n"):
        return GitPlace(None, False)
    real, git_dir = Path(os.path.realpath(folder)), Path(g.stdout.removesuffix("\n")).resolve()
    return GitPlace(None, real == git_dir or git_dir in real.parents)


def find_root(doc: Path) -> Path:
    """The root of a document, without the hub's registry (SPEC 8.2): the top of its
    git work tree, else its own folder. Each worktree is its own root."""
    folder = Path(doc).resolve().parent
    return git_place(folder).top or folder
