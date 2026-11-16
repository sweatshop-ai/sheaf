"""The Sheaf view (SPEC 8.6): a member's folders as a tree and their rectoversos as table rows, as data for the front's
loader to mount from `/_/mount?sheaf=1`. Whose pages these are is the index's to say (9.9); this module only draws what
`Index.data` hands a member: it adds each row's title and its last write, and keeps no list of its own."""
import os
import re
from pathlib import Path

from . import index as index_mod
from . import place
from . import roots as roots_mod
from . import the_list

SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")      # what AgentView takes as a session id (SPEC 8.6)
CHAT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
TITLES_KEPT = 5000                 # titles kept; a full cache starts over, each file is read again once


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
    """The last write as the row says it: who and where (`Bea · page`), and the session it follows when it is not that
    session's own (`Bea · page, before Ada`). A chat client is its label alone; a pull and a disk write are named as
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


def way_back(line, member) -> dict | None:
    """What a row's session name links to, from the Write log's own line and nothing the page says (SPEC 8.6): `laptop` is
    the provider and id the member's own laptop session declared (the page asks AgentView on their laptop to bring it back), with the
    session's Remote Control link when it declared one; `remote` the link alone; `chat` an Open WebUI chat of this origin.
    A claude.ai or ChatGPT write, a session of another member's laptop without a link, an id that is not a plain id, and a
    session with no link at all give None: the name is plain text. A member's laptop is asked only for their own sessions
    (their agents sign `<client> (<member>)`), never for one another member's."""
    if line is None:
        return None
    if line.place == "chat client":
        return {"kind": "chat", "href": f"/c/{line.chat}"} if CHAT_ID.fullmatch(line.chat) else None
    if line.place == "laptop" and SESSION_ID.fullmatch(line.session) and line.writer.endswith(f"({member.name})"):
        provider = "codex" if line.writer.startswith("Codex (") else "claude"           # AgentView's `provider:id` key
        return {"kind": "laptop", "provider": provider, "session": line.session, "remote": line.link}
    return {"kind": "remote", "href": line.link} if line.link else None


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
    """`{tree, rows, more}` for `member`: every document of each of their roots that they may open, newest change first. A row
    is `{doc, url, title, root, folder, mtime, when, open, write, write_tip, session, session_tip, session_link}`: the folder is the
    path on disk, `write` the last write and `session` the writer of the last line that named an agent session. The
    tooltips hold the machine and the session's id, and only what the writer declared. No List status is in it. `more` is `{root: n}`, what the listing's cap (8.6) left out of each root."""
    found = hub.index.data(member=member)
    now = hub.clock()
    rows = []
    for root in found["roots"]:
        for d in root["docs"]:
            address = d["doc"]
            at = roots_mod.Address.parse(address)
            with place.held(hub, address):          # every read of a rectoverso's file holds its name's lock (9.11)
                try:
                    path = Path(os.path.realpath(hub.file(address)))
                except roots_mod.NotFound:
                    continue
                title = titles.of(path, at.rel)
            last, session = hub.writes.last(address), hub.writes.last_way_back(address)
            folder = "/".join([at.root, *at.rel.split("/")[:-1]])
            rows.append({"doc": address, "url": d["url"], "title": title, "root": at.root,
                         "folder": folder, "mtime": d["mtime"], "when": index_mod.when(d["mtime"], now),
                         "open": d["open"], "write": say_write(last, session),
                         "write_tip": last.host if last else "",
                         "session": session.writer if session else "",
                         "session_tip": (session.session + (f" on {session.host}" if session.host else "")) if session else "",
                         "session_link": way_back(session, member)})
    rows.sort(key=lambda r: (-r["mtime"], r["doc"]))
    return {"tree": tree(rows), "rows": rows, "more": found["more"]}
