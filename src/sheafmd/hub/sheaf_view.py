"""The Sheaf view (SPEC 8.6): a member's folders as a tree and their rectoversos as table rows, as data for the front's
loader to mount from `/_/mount?sheaf=1`. Whose pages these are is the index's to say (9.9); this module only draws what
`Index.data` hands a member: it adds each row's title and its last write, and keeps no list of its own."""
import os
from pathlib import Path

from . import index as index_mod
from . import roots as roots_mod
from . import the_list

TITLES_KEPT = 5000


class Titles:
    """The first `# ` heading of a file, read again only when the file changed."""

    def __init__(self):
        self._kept: dict = {}

    def of(self, path: Path, rel: str) -> str:
        try:
            st = path.stat()
            key = (str(path), st.st_mtime_ns, st.st_size)
            if key not in self._kept:
                text = path.read_text(encoding="utf-8", errors="replace")
                if len(self._kept) >= TITLES_KEPT:
                    self._kept.clear()
                self._kept[key] = the_list.read_rectoverso(rel, text).title
            return self._kept[key]
        except OSError:
            return rel.rsplit("/", 1)[-1][:-3]


def say_write(line, session) -> str:
    """The last write as the row says it: who and where (`Hans · page`), and the session it follows when it is not that
    session's own (`Hans · page, before Dimitri`). A chat client is its label alone; a pull and a disk write are named as
    9.12 names them (`git · <author>`, `tiroir · ?`)."""
    if line is None:
        return ""
    if line.via == "pull" or line.place == "chat client":
        said = line.writer
    elif line.via == "disk":
        said = f"tiroir · {line.writer}"
    else:
        said = f"{line.writer} · {line.place}"
    if session is not None and session is not line:
        said += f", before {session.writer}"
    return said


def visible_folders(rel: str) -> list[str]:
    """The folders of a path inside a root that the tree draws: the ones above the first whose name starts with a dot."""
    out = []
    for part in rel.split("/")[:-1]:
        if part.startswith("."):
            break
        out.append(part)
    return out


def tree(rows: list[dict]) -> list[dict]:
    """The tree of the rows' folders: each root, then its folders, as the path on disk. A node exists only because a row
    is in it or below it, so a folder with no page the member may see is not drawn; a dot-folder is no node, and a page in
    one is in its parent's table."""
    nodes: dict = {}

    def node(into: dict, name: str, path: str) -> dict:
        return into.setdefault(name, {"name": name, "path": path, "children": {}})

    for r in rows:
        at = roots_mod.Address.parse(r["doc"])
        top = node(nodes, at.root, at.root)
        here = top
        for part in visible_folders(at.rel):
            here = node(here["children"], part, f"{here['path']}/{part}")

    def done(level: dict) -> list[dict]:
        return [{**n, "children": done(n["children"])} for _, n in sorted(level.items(), key=lambda kv: kv[0].casefold())]
    return done(nodes)


def data(hub, member, titles: Titles) -> dict:
    """`{tree, rows}` for `member`: every document of each of their roots that they may open, newest change first. A row
    is `{doc, url, title, root, folder, mtime, when, open, write, write_tip, session, session_tip}`: the folder is the
    path on disk, `write` the last write and `session` the writer of the last line that named an agent session. The
    tooltips hold the machine and the session's id, and only what the writer declared. No List status is in it."""
    found = hub.index.data(member=member)
    now = hub.clock()
    rows = []
    for root in found["roots"]:
        for d in root["docs"]:
            address = d["doc"]
            at = roots_mod.Address.parse(address)
            try:
                path = Path(os.path.realpath(hub.file(address)))
            except roots_mod.NotFound:
                continue
            last, session = hub.writes.last(address), hub.writes.last_session(address)
            folder = "/".join([at.root, *at.rel.split("/")[:-1]])
            rows.append({"doc": address, "url": d["url"], "title": titles.of(path, at.rel), "root": at.root,
                         "folder": folder, "mtime": d["mtime"], "when": index_mod.when(d["mtime"], now),
                         "open": d["open"], "write": say_write(last, session),
                         "write_tip": last.host if last else "",
                         "session": session.writer if session else "",
                         "session_tip": (session.session + (f" on {session.host}" if session.host else "")) if session else ""})
    rows.sort(key=lambda r: (-r["mtime"], r["doc"]))
    return {"tree": tree(rows), "rows": rows}
