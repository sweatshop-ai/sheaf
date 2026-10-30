"""`projects.toml` at the top of a root (SPEC 8.12): one entry per `<client>/<project>` folder, with its
members and its status. In proxy mode the file grants (#44): a member opens the shared sheaves of a project
folder only when its `members` hold their `short`, and a folder it does not name, or every folder of a file
the hub cannot read, is open to its sheaves' owners alone. A sheaf folder it does not name is also a warning,
in the hub's log and in the diagnostics log (15), once per folder per hub run.

    [projects."acme/blog"]
    members = ["ada", "bob"]          # the front's short names of who works on it
    status = "live"                   # or "closed"
    assistants = ["james"]            # optional: the agents that work on it for its members, for the Library

    read(folder)              the entries, or None without the file; raises Invalid
    unlisted(entries, rels)   the `<client>/<project>` folders of `rels` that the entries do not name
    grants(entries, rel, short)   whether the member `short` may open the shared sheaves at `rel`
    groups(entries)           what `sheaf projects groups` prints for the Library: the same judgement
    image_in_reach(doc, image)   whether a page of `doc` may embed the local image `image` (9.9)
"""
import re
import tomllib
from pathlib import Path

from . import place

FILE = "projects.toml"
# A folder name the Library's glob reads as itself: no `*`, `?`, `[`, space or other character it could take apart.
PART = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")
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
        if len(parts) != 2 or not all(PART.fullmatch(x) for x in parts):
            raise Invalid(f"{here}: a project is named <client>/<project>, each of letters, digits, '.', '_' or '-' "
                          "and not starting with '.'")
        if parts[1] == place.PRIVATE:
            # `<client>/<project>/private/` holds the sheaves the hub places as their owner's alone (9.11)
            raise Invalid(f"{here}: a project cannot be named private, the name of the folder of owner-only sheaves")
        if not isinstance(p, dict):
            raise Invalid(f"{here} must be a table with members and status")
        extra = sorted(set(p) - {"members", "status", "assistants"})
        if extra:
            raise Invalid(f"unknown key '{extra[0]}' in {here}")
        if not isinstance(p.get("members"), list) or not all(isinstance(m, str) and m for m in p["members"]):
            raise Invalid(f"'members' in {here} must be a list of names")
        # An agent reaches the hub through its member's token (9.7), so `assistants` grants nothing here: it is
        # read for the Library alone, which knows an agent by its own principal.
        if "assistants" in p and not (isinstance(p["assistants"], list)
                                      and all(isinstance(a, str) and a for a in p["assistants"])):
            raise Invalid(f"'assistants' in {here} must be a list of names")
        if p.get("status") not in STATUSES:
            raise Invalid(f"'status' in {here} must be one of {', '.join(STATUSES)}, not {p.get('status')!r}")
    seen = {}
    for name in sorted(projects):
        # The Library knows a project by its group alone: two that share one would give each the other's sheaves.
        if (other := seen.setdefault(group_of(name).casefold(), name)) != name:
            raise Invalid(f'[projects."{other}"] and [projects."{name}"] would share the group {group_of(name)}')
    return projects


def group_of(name: str) -> str:
    """The Library's group of the project `name` (`<client>/<project>`): `group:proj-<client>-<project>`."""
    return "group:proj-" + name.replace("/", "-")


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


def project_of(rel: str) -> str | None:
    """The `<client>/<project>` folder of the path `rel` in a root, None above that depth."""
    parts = rel.split("/")
    return f"{parts[0]}/{parts[1]}" if len(parts) >= 3 else None


def image_in_reach(doc: str, image: str) -> bool:
    """Whether a page of the document at `doc` may embed the image at `image` (paths in one root, 9.9 "Local
    images"), judged as a document is (8.12, 9.11) and the same for every reader of the page: an image above project
    depth is open to every member of the root; one of a project only to a page of that project; one in a
    `private/<short>/` only to a sheaf in that same folder."""
    folder = project_of(image)
    if folder is None:
        return True
    if project_of(doc) != folder:
        return False
    d, i = doc.split("/"), image.split("/")
    return i[2] != place.PRIVATE or (len(d) >= 5 and d[:4] == i[:4])


def grants(entries, rel: str, short: str) -> bool:
    """Whether the file's `entries` (None for no file, an `Invalid` for one the hub cannot read) let the member of
    `short` open the shared sheaves at `rel` (8.12): its project's `members` hold `short`, compared in lower case
    (`str.lower()`, not casefolded: `groups` prints the names so, and the Library compares principal ids as given).
    A root with no file, and a document above project depth, grant as before: to every member of the root. A
    project the file does not name, and every project of a file the hub cannot read, grant no one."""
    folder = project_of(rel)
    if entries is None or folder is None:
        return True
    if isinstance(entries, Invalid) or (entry := entries.get(folder)) is None:
        return False
    return bool(short) and short.lower() in {m.lower() for m in entry["members"]}


def groups(entries: dict) -> dict:
    """The Library's groups from the same entries the hub grants by (8.12, 13): each project's group
    `group:proj-<client>-<project>`, its glob `<client>/<project>/*.md`, its status and its members (lower case,
    as `grants` compares them) and its assistants (lower case too), and for each member short, and each assistant,
    the groups of the projects that name them. A name in both maps keeps its two lists apart: its principal's
    groups are their union (13)."""
    out, members, assistants = [], {}, {}
    for name in sorted(entries):
        group = group_of(name)
        names = sorted({m.lower() for m in entries[name]["members"]})
        agents = sorted({a.lower() for a in entries[name].get("assistants", [])})
        out.append({"project": name, "group": group, "glob": f"{name}/*.md", "status": entries[name]["status"],
                    "members": names, "assistants": agents})
        for m in names:
            members.setdefault(m, []).append(group)
        for a in agents:
            assistants.setdefault(a, []).append(group)
    return {"members": {m: sorted(g) for m, g in sorted(members.items())},
            "assistants": {a: sorted(g) for a, g in sorted(assistants.items())}, "projects": out}
