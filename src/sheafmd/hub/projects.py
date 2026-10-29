"""`projects.toml` at the top of a root (SPEC 8.12): one entry per `<client>/<project>` folder, with its
members and its status. The hub reads it for one thing: a sheaf folder it does not name is a warning,
in the hub's log and in the diagnostics log (15), once per folder per hub run. Access stays the
member's roots (9.9); the file grants nothing.

    [projects."acme/blog"]
    members = ["ada", "bob"]          # the front's short names of who works on it
    status = "live"                   # or "closed"

    read(folder)              the entries, or None without the file; raises Invalid
    unlisted(entries, rels)   the `<client>/<project>` folders of `rels` that the entries do not name
"""
import tomllib
from pathlib import Path

FILE = "projects.toml"
STATUSES = ("live", "closed")


class Invalid(Exception):
    """A `projects.toml` the hub cannot read. The message names the reason."""


def read(folder: Path) -> dict | None:
    try:
        raw = (Path(folder) / FILE).read_bytes()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise Invalid(f"cannot be read ({e.strerror})") from None
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise Invalid(str(e)) from None
    unknown = sorted(set(data) - {"projects"})
    if unknown:
        raise Invalid(f"unknown key '{unknown[0]}' at the top")
    projects = data.get("projects", {})
    if not isinstance(projects, dict):
        raise Invalid("'projects' must be a table")
    for name, p in projects.items():
        here = f'[projects."{name}"]'
        parts = name.split("/")
        if len(parts) != 2 or not all(parts) or any(x.startswith(".") for x in parts):
            raise Invalid(f"{here}: a project is named <client>/<project>")
        if parts[1] == "private":
            # `<client>/<project>/private/` holds the sheaves the hub places as their owner's alone (9.11)
            raise Invalid(f"{here}: a project cannot be named private, the name of the folder of owner-only sheaves")
        if not isinstance(p, dict):
            raise Invalid(f"{here} must be a table with members and status")
        extra = sorted(set(p) - {"members", "status"})
        if extra:
            raise Invalid(f"unknown key '{extra[0]}' in {here}")
        if not isinstance(p.get("members"), list) or not all(isinstance(m, str) and m for m in p["members"]):
            raise Invalid(f"'members' in {here} must be a list of names")
        if p.get("status") not in STATUSES:
            raise Invalid(f"'status' in {here} must be one of {', '.join(STATUSES)}, not {p.get('status')!r}")
    return projects


def unlisted(entries: dict, rels) -> list[str]:
    """The `<client>/<project>` folders that hold a document of `rels` (paths in the root) and that
    `entries` does not name, sorted. A document above that depth (a README at the top, a page of a
    client folder) belongs to no project and is not counted."""
    out = set()
    for rel in rels:
        parts = rel.split("/")
        if len(parts) >= 3 and (folder := f"{parts[0]}/{parts[1]}") not in entries:
            out.add(folder)
    return sorted(out)
