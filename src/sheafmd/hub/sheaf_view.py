"""The Sheaf view (SPEC 8.6): a member's folders as a tree and their rectoversos as table rows, as data for the front's
loader to mount from `/_/mount?sheaf=1`. Whose pages these are is the index's to say (9.9); this module only draws what
`Index.data` hands a member: it adds each row's title and its last write, and keeps no list of its own."""
import os
import re
from pathlib import Path

from ..source import md_hash
from . import index as index_mod
from . import place
from . import roots as roots_mod
from . import the_list
from . import visibility

SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")      # what AgentView takes as a session id (SPEC 8.6)
AGENTS = {"Claude Code": "claude", "Codex": "codex"}                # the client of `<client> (<member>)` and AgentView's provider
CHAT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
TITLES_KEPT = 5000                 # titles kept; a full cache starts over, each file is read again once
SHARED = "Shared with me"          # the top-level folder of the pages other members Shared with this one, a folder per owner


class Titles:
    """The first `# ` heading of a file, the agent that Shared it on its create (9.11), and its hash while no Share line of it
    is ticked (what the row's Share button writes against), read again only when the file changed."""

    def __init__(self):
        self._kept: dict = {}

    def of(self, path: Path, rel: str) -> str:
        return self.read(path, rel)[0]

    def read(self, path: Path, rel: str) -> tuple:
        """(the title, the agent that Shared the page or "", the hash of a page no Share line opens or "")."""
        try:
            st = path.stat()
            key = (str(path), st.st_mtime_ns, st.st_size)
            if key not in self._kept:
                text = path.read_text(encoding="utf-8", errors="replace")
                if len(self._kept) >= TITLES_KEPT:
                    self._kept.clear()
                self._kept[key] = (the_list.read_rectoverso(rel, text).title, shared_by(text),
                                    md_hash(text) if visibility.audience(text) is None else "")
            return self._kept[key]
        except OSError:
            return rel.rsplit("/", 1)[-1][:-3], "", ""


def shared_by(text: str) -> str:
    """The agent that opened the page when it made it: its `shared` line reads `agent:<name> <time>` (the hub writes
    it on a door `create` that carries a ticked Share line), else ""."""
    mark = visibility.text(visibility.front_matter(text), "shared")
    return mark[len("agent:"):].rpartition(" ")[0] if mark.startswith("agent:") else ""


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
    if line.place == "laptop" and line.session:
        if not SESSION_ID.fullmatch(line.session):
            return None
        client, _, own = line.writer.partition(" (")
        if own == f"{member.name})" and client in AGENTS:
            return {"kind": "laptop", "provider": AGENTS[client], "session": line.session, "remote": line.link}
    return {"kind": "remote", "href": line.link} if line.link else None


def session_tip(line) -> str:
    """The session's id and its machine, as far as the write declared them."""
    return " on ".join(t for t in (line.session, line.host) if t)


def byline(hub, address: str, member) -> dict | None:
    """The last agent session of a page as its byline says it (SPEC 6.2, item 11): `{name, tip, link}`, the name and tooltip of a row
    and the same `way_back`, for the member asking; None when no write named a session or a chat."""
    line = hub.writes.last_way_back(address)
    if line is None:
        return None
    return {"name": line.writer, "tip": session_tip(line), "link": way_back(line, member)}


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
        if "shared_from" in r:      # the owner's own folders are theirs: the page is one level under its owner's name
            node(node(nodes, SHARED, SHARED)["children"], r["shared_from"], f"{SHARED}/{r['shared_from']}")
            continue
        at = roots_mod.Address.parse(r["doc"])
        top = node(nodes, at.root, at.root)
        here = top
        for part in visible_folders(at.rel):
            here = node(here["children"], part, f"{here['path']}/{part}")

    def done(level: dict) -> list[dict]:
        return [{**n, "children": done(n["children"])} for _, n in sorted(level.items(), key=lambda kv: kv[0].casefold())]
    return done(nodes)


def mine(hub, member, root_name: str) -> bool:
    """Whether the root named `root_name` is `member`'s own loose root: the pages of one are the ones a row may Share (9.11)."""
    root = hub.roots.get(root_name)
    return root is not None and hub.loose.owner_of(root) == member.id


def data(hub, member, titles: Titles) -> dict:
    """`{tree, rows, more}` for `member`: every document of each of their roots that they may open, newest change first. A row
    is `{doc, url, title, root, folder, share, mtime, when, open, write, write_tip, session, session_tip, session_link}`:
    the folder is the path on disk; `share` the hash of a page of the member's own loose root that no Share line opens (the
    row's Share button writes against it), else ""; `write` the last write and `session` the writer of the last line that named
    an agent session. The tooltips hold the machine and the session's id, and only what the writer declared. No List status is
    in it. `more` is `{root: n}`, what the listing's cap (8.6) left out of each root."""
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
                title, agent, unshared = titles.read(path, at.rel)
            last, session = hub.writes.last(address), hub.writes.last_way_back(address)
            folder = "/".join([at.root, *at.rel.split("/")[:-1]])
            given = {}
            if "shared_from" in root:       # another member's page, found under the owner's name and nowhere else
                folder, given = f"{SHARED}/{root['shared_from']}", {"shared_from": root["shared_from"],
                                                                      "new": hub.member_opened.get(member.id, address) != int(d["mtime"] * 1e9)}
            rows.append({"doc": address, "url": d["url"], "title": title, "root": SHARED if given else at.root,
                         "folder": folder, "shared_by": agent, **given,
                         "share": unshared if mine(hub, member, at.root) and not given else "", "mtime": d["mtime"], "when": index_mod.when(d["mtime"], now),
                         "open": d["open"], "write": say_write(last, session),
                         "write_tip": last.host if last else "",
                         "session": session.writer if session else "",
                         "session_tip": session_tip(session) if session else "",
                         "session_link": way_back(session, member)})
    rows.sort(key=lambda r: (-r["mtime"], r["doc"]))
    return {"tree": tree(rows), "rows": rows, "more": found["more"]}
