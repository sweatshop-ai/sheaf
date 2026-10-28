"""
sheafmd.hub.visibility — who may open a sheaf (SPEC 9.11): its owner alone, or every member of its root.

    front_matter(text)              the top-level keys of the front matter: text, or a tuple for a list
    effective(fm)                   "owner" or "project", what the hub enforces
    owner_of(fm, members, assignees) the members who own the sheaf
    visible_to(fm, member, assignees=None)
    share(text, by, date)           the text the owner's Share writes
    newly_ticked(toggled)           the Share and Stop James boxes a save ticks
    for_door(text, old)             the text a door write puts on disk

A sheaf is `owner` when its `visibility` says so, or when one of its `sources` is private and the owner has
not shared it. A source is `<kind>:<ref>`; only the kinds of PROJECT_WIDE are known to be readable by every
member of the project, so every other kind, a bare word (`library`) and a kind the hub has never heard of is
private. A written `visibility: project` does not open a sheaf with a private source: only the `shared:` line
that the hub writes when the owner ticks Share does, and a door write cannot write that line.

The owner is the assignee of the sheaf's issue in the record, when the list knows it and it has one, told by
the member whose `github` it is; else the member whose `short` is the front matter's `owner`.
"""
import re

PROJECT_WIDE = ("issue", "pr", "repo", "web")
KEYS = ("visibility", "sources", "owner", "shared")
UNREAD = "?"                        # set by front_matter when a line it cannot read may hold one of KEYS

_KEY_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*):(?:\s+(.*?))?\s*")
_PLAIN_KEY_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_ .-]*:(?:\s.*)?")      # `my key: …`, `a.b: …`
_ITEM_RE = re.compile(r"\s*-\s+(.*?)\s*")


def _lines(text: str) -> list:
    """The lines of `text` as split_md_blocks numbers them: on "\n" only, never on U+2028 or "\x0c" as
    splitlines() does, so the front matter, the actions and the blocks agree on every line."""
    return [line.removesuffix("\r") for line in text.split("\n")]


_COMMENT_RE = re.compile(r"(?:^|\s)#")


def _uncomment(value: str) -> str:
    """`value` without the YAML comment after it, as pandoc reads it: a quoted value ends at its closing
    quote, an unquoted one at the first `#` that opens the value or follows a space (`a/b#7` keeps its `#`)."""
    value = value.strip()
    if value[:1] in ("\"", "'") and (close := value.find(value[0], 1)) > 0:
        rest = value[close + 1:].strip()
        if not rest or rest.startswith("#"):
            return value[:close + 1]
    if m := _COMMENT_RE.search(value):
        value = value[:m.start()]
    return value.strip()


def _unquote(value: str) -> str:
    """`value` without the pair of quotes around it, when it has one."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _end(lines: list) -> int:
    """The number of the front matter's closing line; -1 when `lines` opens with none."""
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return -1
    return next((n for n in range(1, len(lines)) if lines[n].strip() in ("---", "...")), -1)


def _may_spell_a_key(line: str) -> bool:
    """Whether `line`, an unindented line the reader cannot read, may hold one of KEYS: anything but a plain
    `key: value` (a quoted or complex key, a flow mapping, an anchor), or a plain one whose key is one of KEYS
    in any case (`Owner : x`). Its value is not looked at."""
    if not _PLAIN_KEY_RE.fullmatch(line):
        return True
    return " ".join(line.partition(":")[0].split()).casefold() in KEYS


def front_matter(text: str) -> dict:
    """The top-level `key: value` lines of the front matter at the top of `text`. A list, written
    `[a, b]` or as `- a` lines under an empty key, indented or not, is a tuple of its items; a nested table
    is not read. The reader fails closed: a line it cannot read that may hold one of KEYS (a line that is no
    plain `key: value`, or one whose key is one of them; an indented line under one of
    KEYS; one of KEYS written twice) sets `UNREAD`, and `effective` reads such a sheaf as `owner`. A plain
    `key: value` the reader does not read that names none of them (`my key: a value`) is another key's."""
    lines = _lines(text)
    end = _end(lines)
    if end < 0:
        return {}                   # none, or no closing line: no front matter
    out, listing, current, skipped = {}, None, None, False
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue                # a blank or comment line closes no list
        if listing is not None and (m := _ITEM_RE.fullmatch(line)):
            out[listing] += (_unquote(_uncomment(m.group(1))),)
            continue
        if skipped and _ITEM_RE.fullmatch(line):
            continue                # an item of the list under a plain key the reader skipped
        listing, skipped = None, False
        m = _KEY_RE.fullmatch(line)
        if not m:
            if line[:1] not in " \t":
                if _may_spell_a_key(line):
                    out[UNREAD] = True
                current = None      # a plain key the reader does not read: the indented lines below are its,
                skipped = line.rstrip().endswith(":")       # and so are the items of a list under it
            elif current in KEYS:
                out[UNREAD] = True
            continue                # an indented line under another key: a value this reader does not read
        key, value = m.group(1), _uncomment(m.group(2) or "")
        if key in KEYS and key in out:
            out[UNREAD] = True
        current = key
        if value.startswith("[") and value.endswith("]"):
            out[key] = tuple(_unquote(v.strip()) for v in value[1:-1].split(",") if v.strip())
        elif not value:
            out[key], listing = (), key
        else:
            out[key] = _unquote(value)
    for key, value in out.items():
        if value == ():
            out[key] = ""
    return out


def text(fm: dict, key: str) -> str:
    """`fm[key]` when it is text, else "" (a list where text was meant reads as nothing)."""
    v = fm.get(key, "")
    return v if isinstance(v, str) else ""


def sources(fm: dict) -> tuple:
    """The sheaf's sources, one item or a list, as a tuple."""
    v = fm.get("sources", ())
    return (v,) if isinstance(v, str) and v else v if isinstance(v, tuple) else ()


def private(source: str) -> bool:
    """Whether `source` may hold what not every member of the project may read (9.11): every kind but
    those of PROJECT_WIDE with a ref, an unknown kind included."""
    kind, colon, ref = source.partition(":")
    return not (colon and ref.strip() and kind.strip().casefold() in PROJECT_WIDE)


def effective(fm: dict) -> str:
    """`owner` or `project`, as the hub enforces it (9.11)."""
    if fm.get(UNREAD) or text(fm, "visibility").casefold() == "owner":
        return "owner"
    if any(private(s) for s in sources(fm)) and not text(fm, "shared"):
        return "owner"
    return "project"


def owner_of(fm: dict, members, assignees=None) -> list:
    """The members who own the sheaf `fm`: by the record's `assignees` when the list knows the issue and
    it has one, else by the front matter's `owner`."""
    members = list(members)
    if assignees:
        logins = {a.casefold() for a in assignees}
        return [m for m in members if m.github and m.github.casefold() in logins]
    short = text(fm, "owner").casefold()
    return [m for m in members if short and m.short and m.short.casefold() == short]


def visible_to(fm: dict, member, assignees=None) -> bool:
    """Whether `member` may open the sheaf `fm`. `assignees` is the record's for its issue, None when the
    list does not know it."""
    if effective(fm) == "project":
        return True
    return any(m.id == member.id for m in owner_of(fm, [member], assignees))


def set_keys(text_: str, values: dict) -> str:
    """`text_` with each key of `values` set to its value on one top-level line of the front matter, or
    taken out where the value is None; the other lines stay as written. A text with no front matter
    gets one only for a value that is not None."""
    lines = _lines(text_)
    nl = "\r\n" if text_.split("\n", 1)[0].endswith("\r") else "\n"
    end = _end(lines)
    if end < 0:
        keep = {k: v for k, v in values.items() if v is not None}
        if not keep:
            return text_
        return nl.join(["---", *(f"{k}: {v}" for k, v in keep.items()), "---"]) + nl + text_
    head, done = [lines[0]], set()
    skipping = False
    for line in lines[1:end]:
        m = _KEY_RE.fullmatch(line)
        if skipping and _ITEM_RE.fullmatch(line):
            continue
        skipping = False
        if m and m.group(1) in values:
            key = m.group(1)
            skipping = not (m.group(2) or "").strip()
            if key not in done and values[key] is not None:
                head.append(f"{key}: {values[key]}")
            done.add(key)
            continue
        head.append(line)
    head += [f"{k}: {v}" for k, v in values.items() if k not in done and v is not None]
    below = sum(len(raw) + 1 for raw in text_.split("\n")[:end])     # the closing line and the body, as written
    return nl.join(head) + nl + text_[below:]


def share(text_: str, by: str, date: str) -> str:
    """The sheaf `text_` once its owner, `by`, has ticked Share: open to the project, and the mark that says
    who opened it and when."""
    return set_keys(text_, {"visibility": "project", "shared": f"{by} {date}"})


_BOX_RE = re.compile(r"(\s*[-*+] \[)([ xX])(\] (Share|Stop James)(?:\s+@\S+)?\s*)")


def newly_ticked(toggled) -> set:
    """The words of the two actions the hub acts on, Share and Stop James, whose box a save ticked.
    `toggled` holds the (old, new) content of each block whose edit only flipped task marks (edit.py
    `apply_edits`): a line that reads `- [ ] <word>` in the old and is that line with only its box ticked
    in the new. Nothing else counts, not a block pandoc rewrote, so a line that takes the place of another
    (a ballot box, an `<input>`, an escaped `\\- [x]`, a box beside one the owner deleted) ticks nothing,
    and text an assistant writes cannot Share a sheaf through the owner's save."""
    words = set()
    for old, new in toggled:
        a, b = _lines(old), _lines(new)
        if len(a) != len(b):
            continue
        for was, now in zip(a, b):
            m, n = _BOX_RE.fullmatch(was), _BOX_RE.fullmatch(now)
            if m and n and m.group(2) == " " and n.group(2) in "xX" \
                    and (m.group(1), m.group(3)) == (n.group(1), n.group(3)):
                words.add(m.group(4))
    return words


def for_door(text_: str, old: str | None) -> str:
    """What a door write of `text_` puts on disk over `old` (None for a create). The caller is an assistant,
    never the owner: its `visibility` and `shared` are not read, and on an update the `owner` and the `issue`
    (whose assignee is the owner) stay the ones on disk. The sheaf is `owner` when it has a private source, and stays `owner` when it was, front matter
    dropped or not; a Share already made stays while the write adds no private source the owner did not
    share."""
    fm = front_matter(text_)
    was = front_matter(old) if old is not None else {}
    closed = old is not None and effective(was) == "owner"
    owner = text(was, "owner")
    if not fm and not closed:
        return text_
    mine = {s for s in sources(fm) if private(s)}
    kept = text(was, "shared") if text(was, "shared") and mine <= set(sources(was)) else None
    want = "owner" if closed or (mine and not kept) else "project"
    values = {"visibility": want, "shared": kept if want == "project" else None}
    if old is not None:
        # an update neither gives nor changes the owner, nor the issue whose assignee is the owner
        values["owner"] = owner or None
        values["issue"] = text(was, "issue") or None
    if want == "project" and not ({"visibility", "sources", "shared"} & fm.keys()) \
            and text(fm, "owner") == owner and (old is None or text(fm, "issue") == text(was, "issue")):
        return text_
    return set_keys(text_, values)
