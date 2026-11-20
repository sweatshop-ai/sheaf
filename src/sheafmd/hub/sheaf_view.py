"""The Sheaf view (SPEC 8.6): a member's folders as a tree and their rectoversos as table rows, as data for the front's
loader to mount from `/_/mount?sheaf=1`. Whose pages these are is the index's to say (9.9); this module only draws what
`Index.data` hands a member: it adds each row's title and its last write, and keeps no list of its own."""
import re
from pathlib import Path

from .. import config
from ..source import md_hash
from . import archive as archive_mod
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
                text = path.read_bytes().decode("utf-8", errors="replace")      # bytes: the hash is of the text a save reads, line ends as they are
                if len(self._kept) >= TITLES_KEPT:
                    self._kept.clear()
                kept = (the_list.read_rectoverso(rel, text).title, shared_by(text),
                        md_hash(text) if visibility.audience(text) is None else "")
                self._kept[key] = kept      # another thread's clear() may come before a read of it: the local is the answer
                return kept
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
    if hub.alias(member, address) != address:       # a Shared page: the owner's machine, session and link are theirs
        return {"name": line.writer, "tip": "", "link": None}
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

    def node(into: dict, name: str, path: str, rename: bool = False) -> dict:
        # `rename`: the folder is one of the owner's own loose root, whose pages a folder rename may move (9.11); never the root itself.
        n = into.setdefault(name, {"name": name, "path": path, "rename": False, "children": {}})
        n["rename"] = n["rename"] or rename
        return n

    for r in rows:
        if "shared_from" in r:      # the owner's own folders are theirs: the page is one level under its owner's name
            node(node(nodes, SHARED, SHARED)["children"], r["shared_from"], f"{SHARED}/{r['shared_from']}")
            continue
        at = roots_mod.Address.parse(r["doc"])
        top = node(nodes, at.root, at.root)
        here = top
        for part in visible_folders(at.rel):
            here = node(here["children"], part, f"{here['path']}/{part}", r.get("can_move", False))

    def done(level: dict) -> list[dict]:
        return [{**n, "children": done(n["children"])} for _, n in sorted(level.items(), key=lambda kv: kv[0].casefold())]
    return done(nodes)


NO_EMAIL = "There is no Clients folder for you: this tiroir does not know your e-mail address, so a client tiroir cannot tell who is asking."


def with_clients(out: dict, names: list, email: str = "x") -> dict:
    """`out` (the member's own Sheaf) with the agency's `Clients` node: one child per client tiroir from the config, drawn whether or not
    its rows were asked for yet, since the rows are read through when the node is opened and never kept (9.9). A member with no
    e-mail has no node, only `clients_line`, the sentence that says why."""
    if not names:
        return out
    if not email:
        return {**out, "clients_line": NO_EMAIL}
    node = {"name": "Clients", "path": "Clients", "clients": True,
            "children": [{"name": n, "path": f"Clients/{n}", "client": n, "children": []} for n in names]}
    return {**out, "clients": names, "tree": [*out["tree"], node]}


def mine(hub, member, root_name: str) -> bool:
    """Whether the root named `root_name` is `member`'s own loose root: the pages of one are the ones a row may Share (9.11)."""
    root = hub.roots.get(root_name)
    return root is not None and hub.loose.owner_of(root) == member.id


Abandoned = index_mod.Abandoned


# Pages between two looks at the connection: a look is a system call, so it is not taken on every page.
CHECK_EVERY = 8


def data(hub, member, titles: Titles, view: str = "", gone=None) -> dict:
    """The listing below, with the loose registry read once for all of it, the rows' own questions included (SPEC 8.6)."""
    with config.git_places_remembered(), hub.loose.remembered():      # each folder resolved once for the rows too (8.2)
        return _data(hub, member, titles, view, gone)


def _data(hub, member, titles: Titles, view: str = "", gone=None) -> dict:
    """`{tree, rows, more}` for `member`: every document of each of their roots that they may open, newest change first. A row
    is `{doc, url, title, root, folder, share, mtime, when, open, write, write_tip, session, session_tip, session_link}`:
    the folder is the path on disk; `can_move` whether the member may Move it (a page of their own loose root, 9.11); `share` the hash of a page of the member's own loose root that no Share line opens (the
    row's Share button writes against it), else ""; `write` the last write and `session` the writer of the last line that named
    an agent session. The tooltips hold the machine and the session's id, and only what the writer declared. No List status is
    in it. `more` is `{root: n}`, what the listing's cap (8.6) left out of each root. `gone()` says the caller closed the
    connection: the run is then ended with `Abandoned`, looked at before the listing, at each root and every `CHECK_EVERY` pages."""
    def check():
        if gone is not None and gone():
            raise Abandoned
    check()
    found = hub.index.data(member=member, gone=gone)
    now = hub.clock()
    rows = []
    marked: dict = {}           # a loose root's name -> its marks, read once; None when they cannot be read

    owned: dict = {}            # a root's name -> whether it is the member's own loose root, asked once

    def own_root(name):
        if name not in owned:
            owned[name] = mine(hub, member, name)
        return owned[name]

    def marks_of(name):
        if name not in marked:
            root = hub.roots.get(name)
            marked[name] = hub.archive.facts(root) if root is not None and hub.loose.owner_of(root) is not None else None
        return marked[name]
    for root in found["roots"]:
        check()
        for n, d in enumerate(root["docs"]):
            if n and n % CHECK_EVERY == 0:
                check()
            address = d["doc"]
            at = roots_mod.Address.parse(address)
            with place.held(hub, address):          # every read of a rectoverso's file holds its name's lock (9.11)
                try:
                    path = config.real_path(hub.file(address))
                except roots_mod.NotFound:
                    continue
                title, agent, unshared = titles.read(path, at.rel)
            last, session = hub.writes.last(address), hub.writes.last_way_back(address)
            folder = "/".join([at.root, *at.rel.split("/")[:-1]])
            given = {}
            if "shared_from" in root:       # another member's page, found under the owner's name and nowhere else
                folder, given = f"{SHARED}/{root['shared_from']}", {"shared_from": root["shared_from"],
                                                                      "new": hub.member_opened.get(member.id, address) != int(d["mtime"] * 1e9)}
            m = marks_of(at.root)
            archived, kept_ = (m is not None and archive_mod.is_archived(m.archived, at.rel, d["mtime"])), m is not None and at.rel in m.kept
            told = hub.alias(member, address)     # the owner's folders are not the recipient's to read (9.11)
            if given:                             # nor is the owner's machine, session or Remote Control link
                write_tip, session_tip_, link = "", "", None
            else:
                write_tip, session_tip_, link = last.host if last else "", session_tip(session) if session else "", way_back(session, member)
            rows.append({"doc": told, "url": d["url"] if told == address else roots_mod.url_path(told), "title": title, "root": SHARED if given else at.root,
                         "folder": folder, "shared_by": agent, **given,
                         "share": unshared if own_root(at.root) and not given else "",
                         "can_move": own_root(at.root) and not given, "mtime": d["mtime"], "when": index_mod.when(d["mtime"], now),
                         "open": d["open"], "own": own_root(at.root) and not given, "archived": archived, "kept": kept_, "write": say_write(last, session),
                         "write_tip": write_tip,
                         "session": session.writer if session else "",
                         "session_tip": session_tip_,
                         "session_link": link})
    rows.sort(key=lambda r: (-r["mtime"], r["doc"]))
    counts = {"archived": sum(r["archived"] for r in rows)}
    rows = [r for r in rows if r["archived"] == (view == "archived")]      # a page is in the default view or in "Archived"
    return {"tree": tree(rows), "rows": rows, "more": found["more"], "view": view or "default", **counts_and_trash(hub, member, counts, view)}


def counts_and_trash(hub, member, counts: dict, view: str) -> dict:
    """`counts` of what the other views hold, and in the trash view the member's own trashed pages (8.6)."""
    out = {"counts": counts}
    root = hub.loose.known(member)
    root = hub.archive.own_root(root) if root is not None else None
    trashed = hub.archive.trashed(root) if root is not None else []
    counts["trash"] = len(trashed)
    if view == "trash":
        out["rows"] = []
        out["tree"] = []
        out["trash"] = trashed
    return out
