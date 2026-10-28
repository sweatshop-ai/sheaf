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
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from . import paths
from .hub.auth import clean_display

DEFAULT_PORT = 27419
ROOT_FILE = ".sheaf.toml"

USER_KEYS = {"port": int, "name": str, "browser": bool, "proxy": dict, "jump": dict}   # proxy: hub.proxy reads it (9.9)
JUMP_KEYS = {"command": list}
ROOT_KEYS = {"theme": str, "for": str, "links": bool, "link_tlds": list, "credit": bool,
             "versions": str, "commit": bool, "push": bool}

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


def load_user_config(warn=None) -> UserConfig:
    path = paths.config_file()
    data = read_toml(path, USER_KEYS, warn)
    port = data.get("port")
    if port is not None and not 0 < port < 65536:
        raise ConfigError(f"{path}: 'port' must be between 1 and 65535, not {port}")
    return UserConfig(port=port, name=data.get("name") or None, browser=data.get("browser"))


def port(warn=None) -> int:
    """SHEAF_PORT, then `port`, then 27419."""
    v = os.environ.get("SHEAF_PORT", "").strip()
    if v:
        if not (v.isascii() and v.isdigit()) or not 0 < int(v) < 65536:
            raise ConfigError(f"SHEAF_PORT={v!r} is not a port number")
        return int(v)
    return load_user_config(warn).port or DEFAULT_PORT


def jump_command(warn=None) -> list[str] | None:
    """The argv of the `[jump]` table (SPEC 4.3), or None when there is no table. A list of
    non-empty text: a string would need a shell, and none is ever started."""
    warn = warn or _stderr
    path = paths.config_file()
    table = read_toml(path, USER_KEYS, warn).get("jump")
    if table is None:
        return None
    for key in table:
        if key not in JUMP_KEYS:
            warn(f"  ! unknown key '{key}' in [jump] of {path}")
    command = table.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(a, str) and a for a in command):
        raise ConfigError(f"{path}: 'command' in [jump] must be a list of text, the program and its "
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
    return RootConfig(theme=data.get("theme") or None, for_=data.get("for") or None,
                      links=data.get("links", True), link_tlds=tuple(tlds),
                      credit=data.get("credit", False), versions_inside=versions == "root",
                      commit=data.get("commit", False), push=data.get("push", False))


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


def git_place(folder: Path) -> GitPlace:
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
        return GitPlace(Path(top.removesuffix("\n")).resolve(), False)
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
