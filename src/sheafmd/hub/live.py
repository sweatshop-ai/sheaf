"""
sheafmd.hub.live — the Live Document: one Source file as a running page serves it (SPEC 8.9).

It holds the text the page was last rendered from, the earlier versions a page may still be
showing, and the saves and comment changes made against them. The handler is a thin adapter
over it: HTTP in, one call, status codes out.

Two callbacks connect it to the page, and both run with its lock held:
- render(text) must have published the page for exactly that text when it returns.
- publish(name, data) hands an event to the open tabs, so events leave in the order the text
  changed.
Neither may call back into the Live Document (that raises instead of deadlocking), nor block
on anything another of its calls holds.
"""
import contextlib
import threading
import time

from .. import comments as rdc
from .. import edit as rde
from .. import source as rds

VERSIONS = 60
# The versions pages keep past a change of the file, beside the newest VERSIONS: the PINS pinned last (`pin`).
PINS = 16
# The request ids of the last comment writes and saves a document remembers (`comment`, `save`, `rid`).
RIDS = 256
# A save or a comment by id made against a version that is neither the file nor one this document
# knows (SPEC 7.3, 7.4).
UNKNOWN = "the .md changed on disk and this page's version is no longer known to the hub"
# The same for a request that names a thread by its id (SPEC 7.3).
BY_ID = f"{UNKNOWN}, so this comment may not be the one on the page"


class NotAuthor(Exception):
    """An edit or a delete, by an author who may change only their own (9.9), of a comment that
    is someone else's, or a delete of one that holds someone else's reply."""


def prose(text):
    """The document without its review comments: when this is unchanged, only comments
    moved, and an open page can take them without reloading."""
    return rde.COMMENT_SRC_RE.sub("", text)


class LiveDocument:
    def __init__(self, md, render, publish, by="unknown", clock=time.time,
                 versions=None, address=None, hold=None):
        """`versions` (a `state.Versions`) and `address` (`<root>/<path>`) together keep every
        text this document hands a page on disk too (SPEC 7.4), so a save made against a page
        rendered before a restart still merges.

        `md` is the file, or a callable that finds it at each read and write: a sheaf of the list's
        root is the document of its name wherever its file is (9.11). `hold()` is a context held
        around each write and each render, taken before this document's lock: the lock of the
        sheaf's name, under which no move comes, so the file found under it is the one written or
        read. The first read, here, is its maker's to hold (`Hub.entry`)."""
        self._file = md if callable(md) else (lambda: md)
        self._hold = hold or contextlib.nullcontext
        self._render, self._publish = render, publish
        self._by, self._clock = by, clock
        self._store, self._address = versions, address
        self._lock = threading.Lock()
        self._owner = None
        text = self._read()
        self._text, self._hash = text, rds.md_hash(text)
        # Every text this hub run has handed a page a hash of, so a save made against an older
        # one can be merged onto the file as it is now instead of refused. The disk copy
        # (state.Versions) answers for a hash from before a restart.
        self._versions = {}
        # The versions pages said they keep (`pin`), the last pinned last: apart from `_versions`, so
        # that writes from outside, however many, never push them out.
        self._pins = {}
        self._remember(text)
        # Threads told to a live session: the count of its action replies each had when it was
        # sent, and when. A thread stays "working" until it has more (comments.action_replies,
        # the replies whose effective role is action): an Ask answer or a reader's reply is not
        # the answer.
        self._telling, self._told_at = {}, {}
        # The question the told session put to its person in its own chat, while it waits for
        # them there ("" when it is not waiting).
        self._question = ""
        # The writes taken with a request id, newest last: rid -> (what was sent, the comment's id, or the
        # report of a save). Apart, so that the many saves of an editing page never push a comment's out.
        self._rids = {}
        self._save_rids = {}

    def _read(self):
        """The file's text, found where it is now: under the name's lock (`hold`), so no move takes it between
        finding it and reading it (9.11)."""
        return self._file().read_text(encoding="utf-8")

    # ── the lock, and the guard against a callback calling back in ─────────────
    def _held(self):
        doc = self

        class Held:
            def __enter__(self):
                if doc._owner == threading.get_ident():
                    raise RuntimeError("Live Document re-entered from its own callback")
                doc._lock.acquire()
                doc._owner = threading.get_ident()

            def __exit__(self, *a):
                doc._owner = None
                doc._lock.release()
        return Held()

    def _after_write(self):
        """Test seam, a no-op: a save or a comment calls it after its write and before its
        render, with the lock held and the file lock released."""

    def _remember(self, text):
        v = self._versions
        v[rds.md_hash(text)] = text
        while len(v) > VERSIONS:
            v.pop(next(iter(v)))
        if self._store is not None and self._address is not None:
            try:
                self._store.put(self._address, text)
            except OSError:
                pass            # a full disk costs a merge after a restart, never a save

    def _names(self, h, text):
        """Whether a page that holds the version `h` names the threads of `text` by their ids: `h` is
        `text`'s own hash or a version this document knows (SPEC 7.3). A request with no hash is
        not checked."""
        return not h or rds.md_hash(text) == h or self._known(h) is not None

    def _known(self, h):
        """The text a page with hash `h` was rendered from, or None."""
        if not h:
            return None
        text = self._versions.get(h)
        if text is None:
            text = self._pins.get(h)
        if text is None and self._store is not None and self._address is not None:
            text = self._store.get(self._address, h)
        return text

    def _rerender(self):
        # One read for both. Reading the file once for the page and again for the state lets a
        # write land in between (a session's reply right after its own edit, while pandoc
        # runs). The page would then carry a hash the hub does not know, the watcher would see
        # its own hash and never rebuild, and every new comment would fail with "select the text again".
        text = self._read()
        self._render(text)
        self._text, self._hash = text, rds.md_hash(text)
        self._remember(text)

    def _snapshot(self, text):
        """What an open page needs to update its comments in place, without a reload."""
        got = rdc.parse(text)
        for c in got.comments:
            if c.id in self._telling and rdc.action_replies(c) > self._telling[c.id]:
                del self._telling[c.id]
        return {"hash": rds.md_hash(text), "telling": sorted(self._telling),
                "comments": [c.as_dict() for c in got.comments],
                "malformed": [{"line": m.line, "reason": m.reason} for m in got.malformed]}

    # ── the interface ─────────────────────────────────────────────────────────
    def current(self):
        """(hash, text) of what the page was last rendered from."""
        with self._held():
            return self._hash, self._text

    def snapshot(self):
        """What an open page needs to update its comments in place, as of the text it was last
        rendered from."""
        with self._held():
            return self._snapshot(self._text)

    def rebuild(self):
        """Render the page again from the file as it is and tell the tabs: the render settings
        changed, so what they show is not the same page (`textSame` false)."""
        with self._hold(), self._held():
            self._rerender()
            snap = self._snapshot(self._text)
            snap["textSame"] = False
            self._publish("changed", snap)
            return snap

    def save(self, base_hash, edits, rid=None, guard=None, move=None):
        """Apply a page's block edits, made against the text named by base_hash.

        A save that changed the file tells the open tabs with one `changed` event (SPEC 7.3:
        every tab, whoever wrote), as the watcher does for a write from outside; the page that
        saved already holds the new hash by then, or takes the event in after its answer. A
        save that changed nothing tells nobody.

        `rid` is the page's request id. A page gives a save up after 120 s while the hub may still write
        it (a long document, or a save behind another); sent again, the same save comes with the same id.
        A save already taken with that id, against the same version and with the same `i` and `html` of
        each edit (`saved` is what the page knew when it sent, not what it sent), writes nothing again:
        the answer is the report of the first, as it was (its `hash` may not be the file's now), with `again`. It is not looked for in the file, so a
        paragraph the page split, or one the file changed since, is never written a second time. A save
        the hub refused is not remembered. `taken_rids` names the ids kept, and
        the `changed` event of the write names its id. The last RIDS ids of saves are kept, in memory, apart from those of comments.

        `guard(text, new, toggled)` sees the text a save would write over the file's text, under the file
        lock, with the (old, new) content of each block whose edit only flipped task marks, and returns the
        text to write; an EditError it raises refuses the save and nothing is written (9.11). `move(text, new)`
        may move the file to the home of the new text before it is written (`rds.update_file`), so the render
        that follows reads it from its new folder.

        Returns the report: hash (of the text written), changed, skipped, remap, merged,
        conflicts. Raises StaleError when the file moved on from a version this document no
        longer knows, EditError when an edit cannot apply."""
        sent = (base_hash, tuple((x["i"], x["html"]) for x in edits))
        with self._hold(), self._held():
            if rid is not None and rid in self._save_rids and self._save_rids[rid][0] == sent:
                return {**self._save_rids[rid][1], "again": True}
            before = self._text
            got = {}

            def change(text):
                if base_hash and rds.md_hash(text) != base_hash:
                    # Saved against an older version: merge it onto this one.
                    base = self._known(base_hash)
                    if base is None:
                        raise rds.StaleError(f"{UNKNOWN}. Copy your edit, then reload")
                    new, got["report"] = rde.merge_edits(base, text, edits, rds.now())
                else:
                    new, got["report"] = rde.apply_edits(text, edits)
                if not got["report"]["changed"]:
                    return text
                return guard(text, new, got["report"]["toggled"]) if guard is not None else new
            # The version check happens inside change(), under the file lock: the CLI and an
            # Ask job write this file from other processes.
            md = self._file()
            token = rde.DOC.set(md)
            try:
                _, new_text = rds.update_file(md, change, move=move)
            finally:
                rde.DOC.reset(token)
            self._after_write()
            report = got["report"]
            self._remember(new_text)
            if report["changed"]:
                self._rerender()
                # One event for the whole write: the watcher compares the hash just taken and
                # will say nothing more of it. Measured from the text the tabs hold, or, when
                # someone wrote between our write and the render (the watcher will not see
                # that either), from the text we wrote: the tab that saved holds that one.
                raced = self._hash != rds.md_hash(new_text)
                start = new_text if raced else before
                self._announce(self._snapshot(self._text), start, **({"rid": rid} if rid is not None else {}))
            answer = {"hash": rds.md_hash(new_text), "changed": report["changed"],
                      "skipped": report["skipped"], "remap": report["remap"],
                      "merged": bool(report.get("merged")),
                      "conflicts": report.get("conflicts", [])}
            if rid is not None:
                self._take(self._save_rids, rid, sent, answer)
            return answer

    def comment(self, op, fields, base_hash, await_action=False, *, by=None, role=None,
                announce=True, author=None, rid=None, guard=None):
        """add / reply / status / edit / delete, written as this document's reader.

        `by` signs an add or a reply as someone else, and `role` gives a reply a role of its own
        (the MCP door writes as an agent; a member of proxy mode as themselves). With `author`,
        `edit` and `delete` apply only to a comment signed `author`, and `delete` only to one that
        holds no reply by another name: NotAuthor otherwise, and nothing is written (9.9).
        The open tabs hear of every change with one `changed` event
        (SPEC 7.3: every tab, whoever wrote), as they do for a write from outside; the page
        that wrote already holds the new hash by then, or takes the event in after its answer.
        `announce=False` is for a caller that tells the tabs itself.

        No whole-file version check: reply, status, edit and delete find their comment by id,
        and add finds its paragraph again in the file as it is now. Refusing them because a
        session wrote elsewhere in the file would be the usual collision (the page and an
        agent both answering in one document). The page's version must be one this document knows,
        though (SPEC 7.3). With await_action, an add or a reply also starts
        waiting for the thread's next action reply. Returns the snapshot with the comment's id
        and textSame. Raises StaleError when a new comment's paragraph itself changed or the
        page's version is unknown, AnchorError for an unknown thread or operation,
        KeyError/ValueError for bad fields.

        `rid` is the page's request id. A page stops waiting for an answer after 30 s and gives the
        form back, while this write may still be running (behind a long save, or its own render of a
        long document); sent again, the same text comes with the same id. A write already taken with
        that id, the same text, the same button (resolve, Ask, Tell) and, for an add, the same passage
        (`block`, `start`, `end`) writes and tells nothing again: the answer is the snapshot as it is
        now, with the comment's id and `again`. It is not looked for in the file: a thread deleted or
        an edit overwritten since still answers `again`. `taken_rids` names the ids kept. The
        `changed` event of a write names its id, so the tab that gave up hears that it was taken.
        The last RIDS ids are kept, in memory. `guard(text)` sees the file's text under the file lock
        before anything is written, and raises to write nothing."""
        sent = (op, fields.get("id", ""), fields.get("body", ""), fields.get("quote", ""), by or self._by,
                bool(fields.get("resolve")), bool(fields.get("ask")), bool(fields.get("tell")),
                fields.get("block"), fields.get("start"), fields.get("end"))
        with self._hold(), self._held():
            if rid is not None and rid in self._rids and self._rids[rid][0] == sent:
                return {**self._answer(self._rids[rid][1], base_hash), "again": True}
            made = {}
            now = rds.now()
            wait = await_action and op in ("add", "reply")
            before = self._text

            def change(t):
                if guard is not None:
                    guard(t)
                new = write(t)
                if wait:
                    # The Tell's baseline comes from the very text written, inside the file
                    # lock. Read after the lock is let go, it could take in a reply the session
                    # made in between, and the thread would then wait for a second one that
                    # never comes.
                    c = rdc.parse(new).by_id(made["id"])
                    made["baseline"] = rdc.action_replies(c) if c else 0
                return new

            def write(t):
                if op == "add":
                    blk = int(fields["block"])
                    if base_hash and rds.md_hash(t) != base_hash:
                        # The file moved on since the page was rendered: find the paragraph
                        # where it is now. Only if that paragraph itself changed does the
                        # reader have to select the text again.
                        base = self._known(base_hash)
                        blk = rde.map_block(base, t, blk) if base is not None else None
                        if blk is None:
                            raise rds.StaleError("this paragraph changed on disk since the "
                                                 "page was rendered - select the text again",
                                                 code="select-again")
                    new, made["id"] = rdc.add_comment(
                        t, blk, int(fields["start"]), int(fields["end"]),
                        fields.get("quote", ""), fields.get("body", ""), by or self._by, now)
                    return new
                cid = fields.get("id", "")
                made["id"] = cid
                if not self._names(base_hash, t):
                    # The id names a comment in the text the page holds. In a text this document never
                    # handed out (another folder's file took the address, or the version aged out) it
                    # may name another comment.
                    raise rds.StaleError(f"{BY_ID}. Copy anything you typed, then reload")
                if author is not None and op in ("edit", "delete"):
                    # Read in the text as it is now, inside the file lock: a reply that came a moment
                    # ago counts.
                    c = rdc.parse(t).by_id(cid)
                    if c is not None and (c.by != author or (op == "delete" and
                                                             any(r.by != author for r in c.replies))):
                        raise NotAuthor("only your own comments can be deleted, and only while no one "
                                        "else has replied to them" if op == "delete" else
                                        "only your own comments can be edited")
                return rdc.apply_op(t, op, fields, by or self._by, now, role)

            rds.update_file(self._file(), change)
            self._after_write()
            self._rerender()
            if wait:
                # Before the snapshot, so a reply already in the text ends the wait now:
                # nothing would look at this text again to end it later.
                self._telling[made["id"]] = made["baseline"]
                self._told_at[made["id"]] = self._clock()
            if rid is not None:
                self._take(self._rids, rid, sent, made.get("id"))
            snap = self._snapshot(self._text)
            if announce and self._text != before:        # one event per write that changed the file
                self._announce(snap, before, **({"rid": rid} if rid is not None else {}))
            return self._answer(made.get("id"), base_hash, snap)

    @staticmethod
    def _take(kept, rid, sent, answer):
        kept.pop(rid, None)
        kept[rid] = (sent, answer)
        while len(kept) > RIDS:
            kept.pop(next(iter(kept)))

    def taken_rids(self):
        """The request ids of the comment writes, then those of the saves, this document took, each oldest first:
        what a page that missed the `changed` event naming its id asks for (`/_/doc`, SPEC 8.5)."""
        with self._held():
            return [*self._rids, *self._save_rids]

    def _announce(self, snap, start, event="changed", **extra):
        """Publish `event` with `snap` and `extra`, and return the snapshot as it was published:
        `textSame` says whether the prose is the same as in `start`, the text the tabs hold, and
        `base` is the hash of `start`. A tab that does not hold `start` (it missed a save) cannot
        use `textSame` and tells by `base`. `snap` is not changed."""
        sent = {**snap, "textSame": prose(start) == prose(self._text), "base": rds.md_hash(start)}
        self._publish(event, {**extra, **sent})
        return sent

    def _answer(self, cid, base_hash, snap=None):
        """What a comment write answers the page: the snapshot with the comment's id. Without a version
        check the answer carries the newest file. If its prose moved on from the page's (a session
        edited text meanwhile), the page must not adopt that hash over stale text: it merges and
        reloads."""
        snap = dict(snap or self._snapshot(self._text))
        base = self._known(base_hash or "")
        snap["textSame"] = base is not None and prose(base) == prose(self._text)
        return {"id": cid, **snap}

    def reply_as(self, cid, text, by, role, event, expect=None):
        """Write `text` as a reply by `by` with `role` (an Ask's answer), render it, and publish
        `event` with the snapshot as `refresh` makes it: the hash the tabs measure from
        (`base`) and whether the prose is the same, so a tab adopts the comments only when it
        holds that base. The event leaves with the lock held, in the order the text changed.
        `expect` is the `rdc.thread_identity` of the thread the text answers: another thread
        under that id is ThreadChanged. Raises AnchorError when the thread is gone, writing and
        saying nothing."""
        def write(t):
            c = rdc.parse(t).by_id(cid)
            if expect is not None and c is not None and rdc.thread_identity(c) != expect:
                raise rdc.ThreadChanged(cid)
            return rdc.reply(t, cid, text, by, rds.now(), False, role)
        with self._hold(), self._held():
            before = self._text
            rds.update_file(self._file(), write)
            self._after_write()
            self._rerender()
            return self._announce(self._snapshot(self._text), before, event, id=cid)

    def rewrite(self, change):
        """Write `change(text)` over the file's text as it is under the file lock, so a write that landed
        meanwhile is kept, then render and tell the tabs, as a save does. Returns the hash of the text
        written (9.12: the hub's own line in the front matter)."""
        with self._hold(), self._held():
            before = self._text
            _, new_text = rds.update_file(self._file(), change)
            self._after_write()
            self._remember(new_text)
            if new_text != before:
                self._rerender()
                self._announce(self._snapshot(self._text), before)
            return rds.md_hash(new_text)

    def _await(self, cid):
        c = rdc.parse(self._read()).by_id(cid)
        if c is None:
            return False
        self._telling[cid] = rdc.action_replies(c)
        self._told_at[cid] = self._clock()
        return True

    def await_reply(self, cid):
        """Start waiting for an action reply in an existing thread. False if there is no such
        thread. Under the name's lock (9.11), as every read of the file: a Tell start that calls it under the hub's
        admission lock waits there for a write of the name under way, its render and its commit (8.11), as it waited
        for the render alone under the document's lock before; nothing takes the admission lock under a name's."""
        with self._hold(), self._held():
            return self._await(cid)

    def forget(self):
        """Its root was forgotten (SPEC 8.2): drop its versions on disk, and keep the texts it hands out in
        memory only from now on. Under the lock, so the text of a write still under way is on disk by
        then and goes with the others."""
        with self._held():
            if self._store is not None and self._address is not None:
                self._store.forget(self._address)
            self._store = None

    def pin(self, h):
        """A page keeps the version `h` past a change of the file: a form holds the reload that change
        needs, a merged save's reload among them (SPEC 7.4, 10.4). Keep it beside the newest VERSIONS,
        so that what the page sends with it once the form is done (a save, a reply, an Ask, a Tell) is
        still taken however much was written meanwhile. The PINS pinned last are kept, in memory and on
        disk; pinned again, a version counts from then. False when the document does not know `h`."""
        with self._held():
            text = self._known(h)
            if text is None:
                return False
            self._pins.pop(h, None)
            self._pins[h] = text
            while len(self._pins) > PINS:
                self._pins.pop(next(iter(self._pins)))
            if self._store is not None and self._address is not None:
                try:
                    self._store.pin(self._address, text)
                except OSError:
                    pass        # a full disk costs the pin after a restart, never the one in memory
            return True

    def knows(self, h):
        """`_names` for the file as it is now: what an Ask or a Tell of a thread by its id must hold."""
        if not h:
            return True
        with self._hold(), self._held():        # the name's lock (9.11), as every read of the file
            try:
                return self._names(h, self._read())
            except OSError:
                return self._known(h) is not None

    def waiting(self):
        """The threads still waiting for an action reply."""
        with self._held():
            return sorted(self._telling)

    def peek(self):
        """(whether any thread waits for an action reply, the question the session waits on
        its person for), read without the lock: the index asks for every document at once, and
        a render that holds the lock for a second must not hold the index with it. The next
        event corrects an answer that was a moment old."""
        return bool(self._telling), self._question

    def is_waiting(self, cid):
        """Whether `cid` waits for an action reply, read without the lock as `peek` is: it is asked under
        the admission lock, which must not wait for a render that holds the document's lock."""
        return cid in self._telling

    def stop_waiting(self, cid):
        """A delivery failed or was cancelled. Returns whether cid was waiting."""
        with self._held():
            self._told_at.pop(cid, None)
            return self._telling.pop(cid, None) is not None

    def observe(self, state):
        """The told session's state (an `agents.base.State`, or None when the adapter has
        none). A session that answered Tell with a question to its person is waiting for them
        in its own chat: say so once, and hold the expiry clock, since that silence is not the
        session being gone. When it works again, say that and restart the clock."""
        with self._held():
            ids = sorted(self._telling)
            q = ""
            if ids and state and state.status == "waiting":
                q = state.question or "a question"
            if q:
                if q != self._question:
                    self._question = q
                    self._publish("tell-waiting", {"ids": ids, "question": q})
            elif self._question:
                self._question = ""
                now = self._clock()
                for cid in ids:
                    self._told_at[cid] = now
                if ids:
                    self._publish("tell-working", {"ids": ids})

    def session_question(self):
        """The question the told session is waiting on its person for, or ""."""
        with self._held():
            return self._question

    def expire(self, wait, product="agent"):
        """Give up on waits older than `wait` seconds, and say so, naming the `product` of the
        session told. A thread told to a session that answered in its own chat, is busy, or has
        ended would otherwise show "working" for ever."""
        with self._held():
            if self._question:
                return
            now = self._clock()
            for cid, t0 in list(self._told_at.items()):
                if cid not in self._telling:
                    self._told_at.pop(cid, None)
                elif now - t0 > wait:
                    self._telling.pop(cid, None)
                    self._told_at.pop(cid, None)
                    self._publish("tell-failed", {"id": cid, "error":
                                  f"no reply from the {product} session after {wait // 60} min. "
                                  "It may be busy, closed, or it answered in its own chat. "
                                  "Tell again, or reply here."})

    def refresh(self, force=False):
        """Catch up with a write from outside (the CLI, an agent, an editor). Publishes
        `changed` and returns its snapshot, or returns None when nothing moved.

        force: render whatever the file holds and return the snapshot, publishing nothing: an
        Ask that just wrote announces its own event."""
        with self._hold(), self._held():
            if force:
                self._rerender()
                return self._snapshot(self._text)
            if rds.md_hash(self._read()) == self._hash:
                return None
            before = self._text
            self._rerender()
            return self._announce(self._snapshot(self._text), before)
