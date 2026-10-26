"""The Live Document: one Source file as a running page serves it (SPEC 8.9).

No server here. A render callback that records what it was given stands in for the
page, and a list stands in for the event stream.
"""
import threading

import pytest

import sheafmd.comments as rdc
import sheafmd.edit as rde
import sheafmd.hub.live as rdl
import sheafmd.source as rds
from helpers import BY_ID, writes_from_outside
from sheafmd.agents.base import State
from sheafmd.blocks import split_md_blocks

DOC = "# Title\n\nFirst paragraph.\n\nOther paragraph.\n"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def made(tmp_path):
    """made(text=DOC, cls=LiveDocument) -> (doc, md, rendered, events, clock)"""
    def go(text=DOC, cls=rdl.LiveDocument):
        md = tmp_path / "d.md"
        md.write_text(text, encoding="utf-8")
        rendered, events, clock = [], [], Clock()
        doc = cls(md, render=rendered.append, publish=lambda n, d: events.append((n, d)),
                  by="Ada", clock=clock)
        return doc, md, rendered, events, clock
    return go


def block_of(text, prefix):
    return next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith(prefix))


def prose(text):
    return rde.COMMENT_SRC_RE.sub("", text)


def edit_other(text, html="<p>Other paragraph, saved.</p>"):
    return [{"i": block_of(text, "Other paragraph"), "html": html}]


def test_a_live_document_starts_from_its_source_file(made):
    doc, md, rendered, events, _ = made()
    assert doc.current() == (rds.md_hash(DOC), DOC)
    assert rendered == [] and events == []


def test_a_save_writes_the_file_renders_it_and_names_the_new_text(made):
    doc, md, rendered, events, _ = made()
    got = doc.save(rds.md_hash(DOC), edit_other(DOC))
    text = md.read_text(encoding="utf-8")
    assert "Other paragraph, saved." in text
    assert got["hash"] == rds.md_hash(text) and got["changed"] and not got["merged"]
    assert rendered == [text] and doc.current() == (rds.md_hash(text), text)


def test_a_save_that_changes_nothing_renders_nothing_and_tells_nobody(made):
    doc, md, rendered, events, _ = made()
    got = doc.save(rds.md_hash(DOC), [])
    assert got["changed"] == [] and rendered == [] and md.read_text(encoding="utf-8") == DOC
    assert events == []


def test_a_save_tells_the_tabs_once_with_the_version_it_started_from(made):
    # SPEC 7.3: a `changed` event to every tab, whoever wrote. The tab that saved holds the new
    # hash by the time it hears (or ignores it by `hash`); a second tab reloads onto the text.
    doc, md, rendered, events, _ = made()
    got = doc.save(rds.md_hash(DOC), edit_other(DOC))
    text = md.read_text(encoding="utf-8")
    (name, data), = events
    assert name == "changed" and data["hash"] == got["hash"] == rds.md_hash(text)
    assert data["base"] == rds.md_hash(DOC) and data["textSame"] is False
    assert data["comments"] == [] and data["telling"] == [] and data["malformed"] == []
    assert doc.refresh() is None and len(events) == 1           # the watcher has nothing left to say


def test_a_save_merged_onto_a_write_the_watcher_has_not_seen_is_told_against_what_the_tabs_hold(made):
    doc, md, rendered, events, _ = made()
    rds.update_file(md, lambda t: t.replace("First paragraph.", "First, from outside."))
    got = doc.save(rds.md_hash(DOC), edit_other(DOC))
    assert got["merged"] is True
    (name, data), = events
    assert name == "changed" and data["hash"] == got["hash"] and data["base"] == rds.md_hash(DOC)
    assert data["textSame"] is False
    assert doc.refresh() is None and len(events) == 1


def test_a_save_against_an_older_version_it_served_is_merged(made):
    doc, md, rendered, events, _ = made()
    rds.update_file(md, lambda t: t.replace("First paragraph.", "First, from outside."))
    doc.refresh()
    got = doc.save(rds.md_hash(DOC), edit_other(DOC))
    text = md.read_text(encoding="utf-8")
    assert got["merged"] is True and got["conflicts"] == []
    assert "First, from outside." in text and "Other paragraph, saved." in text


def test_a_save_against_a_version_it_never_served_is_stale(made):
    doc, md, rendered, events, _ = made()
    rds.update_file(md, lambda t: t + "\nMore.\n")
    with pytest.raises(rds.StaleError, match="no longer known"):
        doc.save("0" * 16, edit_other(DOC))
    assert "saved" not in md.read_text(encoding="utf-8")


class Paused(rdl.LiveDocument):
    """Lets a test in between a save's write and its render."""
    during = None

    def _after_write(self):
        if self.during:
            self.during()


def test_an_outside_write_between_a_save_and_its_render_is_published_once(made):
    doc, md, rendered, events, _ = made(cls=Paused)
    doc.during = lambda: rds.update_file(md, lambda t: t.replace("First paragraph.", "First, outside."))
    got = doc.save(rds.md_hash(DOC), edit_other(DOC))
    doc.during = None
    outside = md.read_text(encoding="utf-8")
    saved = outside.replace("First, outside.", "First paragraph.")
    assert got["hash"] == rds.md_hash(saved)                    # the save names what it wrote
    assert doc.current()[1] == outside and rendered == [outside]
    assert [n for n, _ in events] == ["changed"]
    assert events[0][1]["hash"] == rds.md_hash(outside)
    assert events[0][1]["textSame"] is False
    assert doc.refresh() is None and len(events) == 1           # the watcher has nothing left to say


WITH_C1 = DOC.replace("Other paragraph.", "Other paragraph" + rdc.format(
    rdc.Comment(id="c1", by="T", at="2026-09-30T10:00", quote="Other paragraph", body="Fix it."),
    False) + ".")


def test_a_comment_is_written_by_the_documents_reader_and_rendered(made):
    doc, md, rendered, events, _ = made()
    blk, s, e = rdc.find_quote(DOC, "Other paragraph")
    got = doc.comment("add", {"block": blk, "start": s, "end": e, "quote": "Other paragraph",
                              "body": "Source?"}, rds.md_hash(DOC))
    text = md.read_text(encoding="utf-8")
    c = rdc.parse(text).by_id(got["id"])
    assert c.by == "Ada" and c.body == "Source?"
    assert got["hash"] == rds.md_hash(text) and got["textSame"] is True
    assert rendered == [text]


def comment_fields(op):
    blk, s, e = rdc.find_quote(DOC, "Other paragraph")
    return {"add": {"block": blk, "start": s, "end": e, "quote": "Other paragraph", "body": "Source?"},
            "reply": {"id": "c1", "body": "Done"},
            "status": {"id": "c1", "status": "resolved"},
            "edit": {"id": "c1", "body": "Fix it properly."},
            "delete": {"id": "c1"}}[op]


@pytest.mark.parametrize("op", ["add", "reply", "status", "edit", "delete"])
def test_every_comment_operation_tells_the_tabs_once(made, op):
    doc, md, rendered, events, _ = made(DOC if op == "add" else WITH_C1)
    before = md.read_text(encoding="utf-8")
    got = doc.comment(op, comment_fields(op), rds.md_hash(before))
    text = md.read_text(encoding="utf-8")
    (name, data), = events
    assert name == "changed" and data["hash"] == got["hash"] == rds.md_hash(text)
    assert data["base"] == rds.md_hash(before) and data["textSame"] is True
    assert data["comments"] == got["comments"] and data["telling"] == got["telling"]
    assert doc.refresh() is None and len(events) == 1           # the watcher has nothing left to say


# The page gives up waiting for a comment's answer after 30 s (SPEC 8.5), and the hub may have taken it all the
# same: a comment re-renders the page as a save does. The page sends the same text again with the same request id,
# and the hub answers it as it answered the first, writing and telling nothing.
RID = "r0123456789abcdef"


@pytest.mark.parametrize("op", ["add", "reply"])
def test_a_comment_sent_again_with_its_request_id_is_written_once(made, op):
    doc, md, rendered, events, _ = made(DOC if op == "add" else WITH_C1)
    before = md.read_text(encoding="utf-8")
    first = doc.comment(op, comment_fields(op), rds.md_hash(before), rid=RID)
    once = md.read_text(encoding="utf-8")
    again = doc.comment(op, comment_fields(op), rds.md_hash(before), rid=RID)
    assert md.read_text(encoding="utf-8") == once and len(rendered) == 1
    assert again["id"] == first["id"] and again["hash"] == first["hash"] == rds.md_hash(once)
    assert again["again"] is True and "again" not in first
    (name, data), = events
    assert data["rid"] == RID                     # the tab that gave up hears that it was taken


def test_a_request_id_sent_with_other_text_is_another_comment(made):
    doc, md, *_ = made(WITH_C1)
    doc.comment("reply", {"id": "c1", "body": "Done"}, "", rid=RID)
    got = doc.comment("reply", {"id": "c1", "body": "Done, and more"}, "", rid=RID)
    assert "again" not in got
    assert [r.text for r in rdc.parse(md.read_text(encoding="utf-8")).by_id("c1").replies] == \
        ["Done", "Done, and more"]


# "Send reply" given up, then "Send and resolve" with the same text: the resolve was dropped as `again`.
@pytest.mark.parametrize("button", [{"resolve": True}, {"ask": True}, {"tell": True}])
def test_a_request_id_sent_again_with_another_button_is_another_write(made, button):
    doc, md, *_ = made(WITH_C1)
    doc.comment("reply", {"id": "c1", "body": "Done"}, "", rid=RID)
    got = doc.comment("reply", {"id": "c1", "body": "Done", **button}, "", rid=RID)
    assert "again" not in got
    assert len(rdc.parse(md.read_text(encoding="utf-8")).by_id("c1").replies) == 2


# The fingerprint of a write holds where an add was made: the same words sent at another passage (the page
# prefilled the form by quote alone, after it missed an event) are another comment, not `again`.
@pytest.mark.parametrize("text", ["# Title\n\nSame words.\n\nSame words.\n",       # another block
                                  "# Title\n\nSame words, Same words.\n"])         # another place in the block
def test_an_add_sent_again_at_another_passage_is_another_comment(made, text):
    doc, md, *_ = made(text)
    at = [(i, j) for i, b in enumerate(split_md_blocks(text)) if b.content.strip() and b.kind not in ("blank", "hr", "html")
          for t in [rdc.projection(b.content).text] for j in range(len(t)) if t.startswith("Samewords", j)]
    (b1, s1), (b2, s2) = at
    n = len("Samewords")
    fields = {"quote": "Same words", "body": "Source?"}
    doc.comment("add", {**fields, "block": b1, "start": s1, "end": s1 + n}, "", rid=RID)
    got = doc.comment("add", {**fields, "block": b2, "start": s2, "end": s2 + n}, "", rid=RID)
    assert "again" not in got
    assert len(rdc.parse(md.read_text(encoding="utf-8")).comments) == 2


# A write the hub took is not looked for in the file when it is sent again: the thread deleted, or the edit
# overwritten, since (SPEC 8.5). The answer is `again`, and nothing is written.
def test_a_comment_sent_again_after_its_thread_was_deleted_is_still_answered_as_taken(made):
    doc, md, *_ = made(WITH_C1)
    first = doc.comment("reply", {"id": "c1", "body": "Done"}, "", rid=RID)
    doc.comment("delete", {"id": "c1"}, "")
    gone = md.read_text(encoding="utf-8")
    got = doc.comment("reply", {"id": "c1", "body": "Done"}, "", rid=RID)
    assert got["again"] is True and got["id"] == first["id"]
    assert md.read_text(encoding="utf-8") == gone


# The hub names the ids it took, for a page that missed the event that names them (an outage, a tab closed).
def test_the_ids_a_document_took_are_named_oldest_first(made):
    doc, *_ = made(WITH_C1)
    assert doc.taken_rids() == []
    doc.comment("reply", {"id": "c1", "body": "One"}, "", rid=RID)
    doc.comment("reply", {"id": "c1", "body": "Two"}, "", rid=RID + "x")
    doc.comment("reply", {"id": "c1", "body": "No id"}, "")
    assert doc.taken_rids() == [RID, RID + "x"]


def test_a_comment_without_a_request_id_is_never_taken_for_another(made):
    doc, md, rendered, events, _ = made(WITH_C1)
    doc.comment("reply", {"id": "c1", "body": "Done"}, "")
    doc.comment("reply", {"id": "c1", "body": "Done"}, "")
    assert len(rdc.parse(md.read_text(encoding="utf-8")).by_id("c1").replies) == 2
    assert all("rid" not in d for _, d in events)


def test_the_hub_remembers_the_last_request_ids_only(made, monkeypatch):
    monkeypatch.setattr(rdl, "RIDS", 2)
    doc, md, *_ = made(WITH_C1)
    for n in "123":
        doc.comment("reply", {"id": "c1", "body": n}, "", rid=RID + n)
    doc.comment("reply", {"id": "c1", "body": "3"}, "", rid=RID + "3")
    doc.comment("reply", {"id": "c1", "body": "1"}, "", rid=RID + "1")
    assert [r.text for r in rdc.parse(md.read_text(encoding="utf-8")).by_id("c1").replies] == ["1", "2", "3", "1"]


@pytest.mark.parametrize("op, fields", [("status", {"id": "c1", "status": "open"}),
                                        ("edit", {"id": "c1", "body": "Fix it."})])
def test_a_comment_operation_that_changes_nothing_tells_nobody(made, op, fields):
    doc, md, rendered, events, _ = made(WITH_C1)
    got = doc.comment(op, fields, rds.md_hash(WITH_C1))
    assert md.read_text(encoding="utf-8") == WITH_C1 and got["hash"] == rds.md_hash(WITH_C1)
    assert events == []                                   # "one event per write that changed the file"


def test_a_comment_written_with_announce_off_tells_nobody(made):
    doc, md, rendered, events, _ = made(WITH_C1)
    doc.comment("status", {"id": "c1", "status": "resolved"}, rds.md_hash(WITH_C1), announce=False)
    assert events == []


def test_a_told_comment_tells_the_tabs_which_threads_are_waiting(made):
    doc, md, rendered, events, _ = made(WITH_C1)
    doc.comment("reply", {"id": "c1", "body": "Please."}, rds.md_hash(WITH_C1), await_action=True)
    (name, data), = events
    assert name == "changed" and data["telling"] == ["c1"]


def test_a_reply_names_its_thread_not_a_version(made):
    doc, md, rendered, events, _ = made(WITH_C1)
    rds.update_file(md, lambda t: t.replace("First paragraph.", "First, from outside."))
    got = doc.comment("reply", {"id": "c1", "body": "Done", "resolve": True}, rds.md_hash(WITH_C1))
    assert got["id"] == "c1" and got["textSame"] is False          # the prose moved under the page
    assert rdc.parse(md.read_text(encoding="utf-8")).by_id("c1").status == "resolved"


@pytest.mark.parametrize("op, fields", BY_ID, ids=[op for op, _ in BY_ID])
def test_a_comment_by_id_from_a_page_whose_version_the_document_does_not_know_is_refused(
        made, op, fields):
    """The id names a comment in the text the page holds. A page whose text the document never
    handed out (another file took the address, or the version aged out) may name another
    comment under that id, so nothing is written (SPEC 7.3)."""
    doc, md, rendered, events, _ = made(WITH_C1)
    other = WITH_C1.replace("First paragraph.", "First paragraph of another file.")
    with pytest.raises(rds.StaleError, match="no longer known to the hub"):
        doc.comment(op, dict(fields), rds.md_hash(other))
    assert md.read_text(encoding="utf-8") == WITH_C1 and rendered == [] and events == []


@pytest.mark.parametrize("op, fields", BY_ID, ids=[op for op, _ in BY_ID])
def test_a_comment_by_id_from_the_current_version_an_older_known_one_or_none_is_written(made, op, fields):
    """The controls of the refusal: the page that holds the file as it is, a page an agent wrote
    under since (the usual collision), and a caller with no page (the door, the CLI)."""
    for base in ("current", "older", None, ""):
        doc, md, rendered, events, _ = made(WITH_C1)
        h = rds.md_hash(WITH_C1) if base in ("current", "older") else base
        if base == "older":
            rds.update_file(md, lambda t: t.replace("First paragraph.", "First, from outside."))
        before = md.read_text(encoding="utf-8")
        doc.comment(op, dict(fields), h)
        assert md.read_text(encoding="utf-8") != before, base


def test_a_new_comment_follows_its_paragraph_or_asks_for_a_new_selection(made):
    doc, md, rendered, events, _ = made()
    rds.update_file(md, lambda t: "# Title\n\nInserted above.\n\n" + t.split("\n\n", 1)[1])
    blk, s, e = rdc.find_quote(DOC, "Other paragraph")
    got = doc.comment("add", {"block": blk, "start": s, "end": e, "quote": "Other paragraph",
                              "body": "Moved?"}, rds.md_hash(DOC))
    assert rdc.parse(md.read_text(encoding="utf-8")).by_id(got["id"]).quote == "Other paragraph"
    rds.update_file(md, lambda t: t.replace("First paragraph.", "First, changed."))
    blk, s, e = rdc.find_quote(DOC, "First paragraph")
    with pytest.raises(rds.StaleError, match="select the text again") as refused:
        doc.comment("add", {"block": blk, "start": s, "end": e, "quote": "First paragraph",
                            "body": "Gone?"}, rds.md_hash(DOC))
    assert refused.value.code == "select-again"


def test_an_unknown_operation_is_refused(made):
    doc, *_ = made(WITH_C1)
    with pytest.raises(rdc.AnchorError, match="unknown operation"):
        doc.comment("frobnicate", {"id": "c1"}, "")


def test_a_forced_refresh_renders_and_publishes_nothing(made):
    doc, md, rendered, events, _ = made(WITH_C1)
    rds.update_file(md, lambda t: rdc.reply(t, "c1", "An answer.", "Claude", "2026-09-30T10:05"))
    snap = doc.refresh(force=True)
    assert snap["comments"][0]["replies"][0]["text"] == "An answer."
    assert snap["hash"] == doc.current()[0] and len(rendered) == 1 and events == []


def test_a_refresh_publishes_whether_only_comments_moved(made):
    doc, md, rendered, events, _ = made()
    assert doc.refresh() is None and events == []
    rds.update_file(md, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "Other paragraph"),
                                                  "Other paragraph", "Why?", "A", "2026-09-30T10:00")[0])
    assert doc.refresh()["textSame"] is True
    rds.update_file(md, lambda t: t.replace("First paragraph.", "First, reworded."))
    assert doc.refresh()["textSame"] is False
    assert [n for n, _ in events] == ["changed", "changed"]


def test_a_changed_event_names_the_version_its_textsame_is_measured_from(made):
    # A tab may be behind the hub (another tab saved and nobody told it). `textSame` says only
    # that the prose of the hub's last text equals the prose now; the tab can use it only when
    # the tab holds that last text, which it knows by the hash in `base`.
    doc, md, rendered, events, _ = made()
    before = md.read_text(encoding="utf-8")
    rds.update_file(md, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "Other paragraph"),
                                                  "Other paragraph", "Why?", "A", "2026-09-30T10:00")[0])
    snap = doc.refresh()
    assert snap["textSame"] is True and snap["base"] == rds.md_hash(before)
    assert events[0][1]["base"] == rds.md_hash(before)
    held = rds.md_hash(md.read_text(encoding="utf-8"))            # what the hub rendered last
    rds.update_file(md, lambda t: t.replace("First paragraph.", "First, reworded."))
    assert doc.refresh()["base"] == held


def test_a_save_that_a_write_raced_publishes_the_version_it_wrote_as_base(made):
    doc, md, rendered, events, _ = made(cls=Paused)
    doc.during = lambda: rds.update_file(md, lambda t: t.replace("First paragraph.", "First, outside."))
    got = doc.save(rds.md_hash(DOC), edit_other(DOC))
    doc.during = None
    assert events[0][1]["base"] == got["hash"]


def test_a_tab_that_missed_a_save_is_not_told_its_prose_is_current(made):
    """Two tabs on one version. Tab 2 saves; an outside writer then only adds a comment. The
    event of that write must not read as 'comments only' to tab 1, which still holds the old
    version: it would adopt the new hash over the old prose and its next save would overwrite
    tab 2's text with no merge."""
    doc, md, rendered, events, _ = made()
    tab1 = rds.md_hash(DOC)
    doc.save(tab1, edit_other(DOC))                                # tab 2's save
    rds.update_file(md, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "First paragraph"),
                                                  "First paragraph", "Why?", "A", "2026-09-30T10:00")[0])
    snap = doc.refresh()
    assert snap["textSame"] is True and snap["base"] != tab1       # true of the hub, not of tab 1


def test_a_told_thread_waits_for_an_action_reply_and_nothing_else(made):
    doc, md, rendered, events, clock = made(WITH_C1)
    got = doc.comment("reply", {"id": "c1", "body": "Please."}, rds.md_hash(WITH_C1),
                      await_action=True)
    assert got["telling"] == ["c1"] and doc.waiting() == ["c1"]
    got = doc.comment("reply", {"id": "c1", "body": "Me too"}, got["hash"])
    assert got["telling"] == ["c1"]                               # a reader's reply is not the answer
    rds.update_file(md, lambda t: rdc.reply(t, "c1", "Done.", "Claude", "2026-09-30T10:05", role="action"))
    assert doc.refresh()["telling"] == [] and doc.waiting() == []


def test_waiting_only_follows_an_add_or_a_reply(made):
    doc, *_ = made(WITH_C1)
    doc.comment("status", {"id": "c1", "status": "resolved"}, "", await_action=True)
    assert doc.waiting() == []


def test_an_existing_thread_can_be_told(made):
    doc, *_ = made(WITH_C1)
    assert doc.await_reply("c9") is False and doc.waiting() == []
    assert doc.await_reply("c1") is True and doc.waiting() == ["c1"]


def test_a_wait_nobody_answers_expires_and_says_so(made):
    doc, md, rendered, events, clock = made(WITH_C1)
    doc.await_reply("c1")
    clock.t += 600
    doc.expire(600)
    assert doc.waiting() == ["c1"] and events == []
    clock.t += 1
    doc.expire(600)
    assert doc.waiting() == []
    assert events == [("tell-failed", {"id": "c1", "error":
                       "no reply from the agent session after 10 min. It may be busy, closed, "
                       "or it answered in its own chat. Tell again, or reply here."})]


def test_stopping_a_wait_says_whether_there_was_one(made):
    doc, *_ = made(WITH_C1)
    doc.await_reply("c1")
    assert doc.stop_waiting("c1") is True and doc.waiting() == []
    assert doc.stop_waiting("c1") is False


def test_a_callback_that_calls_back_in_fails_loudly(tmp_path):
    md = tmp_path / "d.md"
    md.write_text(DOC, encoding="utf-8")
    box = {}
    doc = rdl.LiveDocument(md, render=lambda text: box["doc"].current(),
                           publish=lambda n, d: None)
    box["doc"] = doc
    rds.update_file(md, lambda t: t + "\nMore.\n")
    with pytest.raises(RuntimeError, match="re-entered"):
        doc.refresh()
    doc._render = lambda text: None
    assert doc.refresh() is not None                            # and the lock was let go


def test_another_thread_waits_while_a_render_runs(made):
    doc, md, rendered, events, _ = made()
    rendering, finish = threading.Event(), threading.Event()
    doc._render = lambda text: (rendering.set(), finish.wait(5))
    rds.update_file(md, lambda t: t + "\nMore.\n")
    t = threading.Thread(target=doc.refresh)
    t.start()
    assert rendering.wait(5)
    seen = []
    reader = threading.Thread(target=lambda: seen.append(doc.current()))
    reader.start()
    reader.join(0.3)
    assert seen == []                                           # blocked, not wrong
    finish.set()
    t.join(5)
    reader.join(5)
    assert seen[0][0] == rds.md_hash(md.read_text(encoding="utf-8"))


def test_events_leave_in_the_order_the_text_changed(made):
    doc, md, rendered, events, _ = made(cls=Paused)
    order = []
    doc._publish = lambda n, d: order.append(d["hash"])
    racer = {}

    def outside_then_refresh_elsewhere():
        rds.update_file(md, lambda t: t.replace("First paragraph.", "First, C."))
        racer["t"] = threading.Thread(target=lambda: (
            rds.update_file(md, lambda t: t.replace("First, C.", "First, D.")), doc.refresh()))
        racer["t"].start()

    doc.during = outside_then_refresh_elsewhere
    doc.save(rds.md_hash(DOC), edit_other(DOC))
    doc.during = None
    racer["t"].join(5)
    final = rds.md_hash(md.read_text(encoding="utf-8"))
    assert order[-1] == final                                   # the newest text is published last
    assert len(order) == len(set(order))


def test_an_action_reply_landing_while_the_told_comment_renders_answers_it(made):
    # The session is fast: its reply lands after the comment is written but before
    # the wait began, while pandoc still ran. It answers the Tell all the same.
    doc, md, rendered, events, _ = made(WITH_C1)

    def render(text):
        if "Please." in text and "Done." not in text:
            rds.update_file(md, lambda t: rdc.reply(t, "c1", "Done.", "Claude", "2026-09-30T10:05", role="action"))

    doc._render = render
    got = doc.comment("reply", {"id": "c1", "body": "Please."}, rds.md_hash(WITH_C1),
                      await_action=True)
    assert got["telling"] == ["c1"]
    assert doc.refresh()["telling"] == [] and doc.waiting() == []


def test_an_action_reply_landing_before_the_told_comment_renders_answers_it(made):
    doc, md, rendered, events, _ = made(WITH_C1, cls=Paused)
    doc.during = lambda: rds.update_file(
        md, lambda t: rdc.reply(t, "c1", "Done.", "Claude", "2026-09-30T10:05", role="action"))
    got = doc.comment("reply", {"id": "c1", "body": "Please."}, rds.md_hash(WITH_C1),
                      await_action=True)
    doc.during = None
    assert "Done." in rendered[-1]                              # the page already shows the answer
    assert got["telling"] == [] and doc.waiting() == []         # so nothing is left waiting


def test_a_told_session_asking_its_user_says_so_and_does_not_expire(made):
    """Tell went in, the session answered with AskUserQuestion, and the page must not keep
    saying "Claude is working" until it gives up after 10 min."""
    doc, md, rendered, events, clock = made(WITH_C1)
    doc.await_reply("c1")
    doc.observe(State("working"))
    assert events == []
    doc.observe(State("waiting", "Which tagline?"))
    assert events == [("tell-waiting", {"ids": ["c1"], "question": "Which tagline?"})]
    assert doc.session_question() == "Which tagline?"
    doc.observe(State("waiting", "Which tagline?"))
    assert len(events) == 1                                        # said once
    clock.t += 3600
    doc.expire(600)
    assert doc.waiting() == ["c1"]                                 # waiting on him is not silence
    doc.observe(State("working"))
    assert events[-1] == ("tell-working", {"ids": ["c1"]}) and doc.session_question() == ""
    clock.t += 600
    doc.expire(600)
    assert doc.waiting() == ["c1"]                                 # the clock restarted
    clock.t += 1
    doc.expire(600)
    assert doc.waiting() == [] and events[-1][0] == "tell-failed"


def test_nothing_is_said_about_the_session_when_no_thread_waits(made):
    doc, md, rendered, events, clock = made(WITH_C1)
    doc.observe(State("waiting", "Unrelated?"))
    assert events == [] and doc.session_question() == ""


# ── versions on disk (SPEC 7.4) ──────────────────────────────────────────────

from sheafmd.hub import state                                   # noqa: E402

ADDR = "proj/d.md"


@pytest.fixture
def stored(tmp_path):
    """stored(text) -> (doc, md, rendered, events): a document that writes the texts it
    hands out to the state folder, as the hub does."""
    def go(text=DOC, cls=rdl.LiveDocument):
        md = tmp_path / "d.md"
        md.write_text(text, encoding="utf-8")
        rendered, events = [], []
        doc = cls(md, render=rendered.append, publish=lambda n, d: events.append((n, d)),
                  by="Ada", versions=state.Versions(), address=ADDR)
        return doc, md, rendered, events
    return go


def test_every_text_handed_to_a_page_is_written_to_disk(stored):
    doc, md, *_ = stored()
    assert state.Versions().get(ADDR, rds.md_hash(DOC)) == DOC
    got = doc.save(rds.md_hash(DOC), edit_other(DOC))
    new = md.read_text(encoding="utf-8")
    assert state.Versions().get(ADDR, got["hash"]) == new
    assert state.Versions().get(ADDR, rds.md_hash(DOC)) == DOC


def test_a_save_against_a_version_only_on_disk_merges_after_a_restart(stored):
    doc, md, *_ = stored()
    rds.update_file(md, lambda t: t.replace("First paragraph.", "First, from outside."))
    doc.refresh()
    # The hub restarts: a new LiveDocument over the same file and the same state folder. The
    # page it never heard of still holds the text it was rendered from.
    again, *_ = stored(md.read_text(encoding="utf-8"))
    got = again.save(rds.md_hash(DOC), edit_other(DOC))
    text = md.read_text(encoding="utf-8")
    assert got["merged"] is True and got["conflicts"] == []
    assert "First, from outside." in text and "Other paragraph, saved." in text


def test_a_new_comment_after_a_restart_finds_its_paragraph_from_the_disk_version(stored):
    doc, md, *_ = stored()
    rds.update_file(md, lambda t: "# Title\n\nInserted above.\n\n" + t.split("\n\n", 1)[1])
    again, *_ = stored(md.read_text(encoding="utf-8"))
    blk, s, e = rdc.find_quote(DOC, "Other paragraph")
    got = again.comment("add", {"block": blk, "start": s, "end": e, "quote": "Other paragraph",
                                "body": "Moved?"}, rds.md_hash(DOC))
    assert rdc.parse(md.read_text(encoding="utf-8")).by_id(got["id"]).quote == "Other paragraph"
    assert got["textSame"] is False                           # the page must merge and reload


def test_a_version_in_neither_memory_nor_disk_is_refused(stored):
    doc, md, *_ = stored()
    rds.update_file(md, lambda t: t + "\nMore.\n")
    with pytest.raises(rds.StaleError, match="no longer known to the hub"):
        doc.save("0" * 16, edit_other(DOC))
    with pytest.raises(rds.StaleError, match="no longer known to the hub"):
        doc.save("../../hub.key", edit_other(DOC))
    assert "saved" not in md.read_text(encoding="utf-8")


def test_a_disk_that_cannot_be_written_never_stops_a_save(stored, monkeypatch):
    doc, md, *_ = stored()
    monkeypatch.setattr(state.Versions, "put", lambda *a: (_ for _ in ()).throw(OSError("full")))
    got = doc.save(rds.md_hash(DOC), edit_other(DOC))
    assert got["changed"] and "Other paragraph, saved." in md.read_text(encoding="utf-8")


# ── the versions pages keep, beside the newest (SPEC 7.4) ────────────────────

def edit_first(text, html="<p>First, saved.</p>"):
    return [{"i": block_of(text, "First paragraph"), "html": html}]


@pytest.mark.parametrize("held", ["served", "merged"])
def test_a_save_against_a_version_a_page_pinned_merges_after_more_writes_than_the_document_keeps(made, held):
    """A page keeps the version it shows while a form holds the reload a change needs: the one it was
    served at, or the base of a save the hub merged, until that save's reload. It pins that version, and
    what it saves against it is merged however much was written meanwhile."""
    doc, md, *_ = made()
    h = rds.md_hash(DOC)
    writes_from_outside(md, doc, 1)
    if held == "merged":
        assert doc.save(h, edit_other(DOC))["merged"] is True
    assert doc.pin(h) is True
    writes_from_outside(md, doc, rdl.VERSIONS + 1)
    got = doc.save(h, edit_first(DOC))
    text = md.read_text(encoding="utf-8")
    assert got["merged"] is True and got["conflicts"] == []
    assert "First, saved." in text and f"From outside {rdl.VERSIONS}." in text
    assert ("Other paragraph, saved." in text) is (held == "merged")


@pytest.mark.parametrize("op, fields", BY_ID, ids=[op for op, _ in BY_ID])
def test_a_comment_by_id_from_a_page_that_pinned_its_version_is_written_after_more_writes_than_the_document_keeps(
        made, op, fields):
    """A reply sent from the form that held the reload, among them: the id still names the comment of the
    text the page holds. So does an Ask or a Tell (`knows`)."""
    doc, md, *_ = made(WITH_C1)
    h = rds.md_hash(WITH_C1)
    writes_from_outside(md, doc, 1)
    assert doc.pin(h) is True
    writes_from_outside(md, doc, rdl.VERSIONS + 1)
    assert doc.knows(h) is True
    before = md.read_text(encoding="utf-8")
    doc.comment(op, dict(fields), h)
    assert md.read_text(encoding="utf-8") != before


def test_a_new_comment_from_a_page_that_pinned_its_version_finds_its_paragraph_after_more_writes(made):
    doc, md, *_ = made()
    h = rds.md_hash(DOC)
    rds.update_file(md, lambda t: "# Title\n\nInserted above.\n\n" + t.split("\n\n", 1)[1])
    doc.refresh()
    assert doc.pin(h) is True
    writes_from_outside(md, doc, rdl.VERSIONS + 1)
    blk, s, e = rdc.find_quote(DOC, "Other paragraph")
    got = doc.comment("add", {"block": blk, "start": s, "end": e, "quote": "Other paragraph",
                              "body": "Moved?"}, h)
    assert rdc.parse(md.read_text(encoding="utf-8")).by_id(got["id"]).quote == "Other paragraph"


def test_a_version_no_page_pinned_is_no_longer_known_after_more_writes_than_the_document_keeps(made):
    """The bound holds: a version no page keeps goes with the oldest, as before."""
    doc, md, *_ = made(WITH_C1)
    h = rds.md_hash(WITH_C1)
    writes_from_outside(md, doc, rdl.VERSIONS + 1)
    with pytest.raises(rds.StaleError, match="no longer known to the hub"):
        doc.save(h, edit_other(WITH_C1))
    with pytest.raises(rds.StaleError, match="no longer known to the hub"):
        doc.comment("reply", {"id": "c1", "body": "Done"}, h)
    assert doc.knows(h) is False


def test_a_version_no_page_pinned_still_merges_after_fewer_writes_than_the_document_keeps(made):
    doc, md, *_ = made()
    writes_from_outside(md, doc, rdl.VERSIONS - 1)
    assert doc.save(rds.md_hash(DOC), edit_first(DOC))["merged"] is True


def test_a_document_keeps_the_versions_pinned_last_and_no_more(made):
    """Pins have a bound of their own, the PINS pinned last; pinned again, a version counts from then."""
    doc, md, *_ = made()
    pinned = []
    for _ in range(rdl.PINS):
        pinned.append(doc.current()[0])
        assert doc.pin(pinned[-1]) is True
        writes_from_outside(md, doc, 1)
    assert doc.pin(pinned[0]) is True
    pinned.append(doc.current()[0])
    assert doc.pin(pinned[-1]) is True                       # the PINS + 1st: the oldest pin goes
    writes_from_outside(md, doc, rdl.VERSIONS + 1)
    assert [doc.knows(h) for h in pinned] == [True, False] + [True] * (rdl.PINS - 1)


@pytest.mark.parametrize("h", ["0" * 16, "../../hub.key", ""])
def test_a_version_the_document_does_not_know_cannot_be_pinned(stored, h):
    doc, md, *_ = stored()
    assert doc.pin(h) is False
    assert not (state.Versions().dir / state.doc_key(ADDR) / "pins").exists()


def test_a_pinned_version_is_known_after_a_restart_and_more_writes_than_the_disk_keeps(stored):
    """The pin is on disk too: a page that held the reload through a restart of the hub (10.7) still
    saves against the version it shows."""
    doc, md, *_ = stored()
    h = rds.md_hash(DOC)
    writes_from_outside(md, doc, 1)
    assert doc.pin(h) is True
    writes_from_outside(md, doc, max(rdl.VERSIONS, state.VERSIONS_KEPT) + 1)
    again, *_ = stored(md.read_text(encoding="utf-8"))
    got = again.save(h, edit_first(DOC))
    assert got["merged"] is True and "First, saved." in md.read_text(encoding="utf-8")


def test_an_unpinned_version_is_not_known_after_a_restart_and_more_writes_than_the_disk_keeps(stored):
    doc, md, *_ = stored()
    writes_from_outside(md, doc, max(rdl.VERSIONS, state.VERSIONS_KEPT) + 1)
    again, *_ = stored(md.read_text(encoding="utf-8"))
    with pytest.raises(rds.StaleError, match="no longer known to the hub"):
        again.save(rds.md_hash(DOC), edit_first(DOC))


def test_a_disk_that_cannot_be_written_never_stops_a_pin(stored, monkeypatch):
    doc, md, *_ = stored()
    monkeypatch.setattr(state.Versions, "pin", lambda *a: (_ for _ in ()).throw(OSError("full")), raising=False)
    writes_from_outside(md, doc, 1)
    assert doc.pin(rds.md_hash(DOC)) is True
    writes_from_outside(md, doc, rdl.VERSIONS + 1)
    assert doc.save(rds.md_hash(DOC), edit_first(DOC))["merged"] is True


# ── what the handler asks beside save and comment ────────────────────────────

def test_a_snapshot_is_what_a_page_asks_for_on_load(made):
    doc, md, rendered, events, _ = made(WITH_C1)
    snap = doc.snapshot()
    assert snap["hash"] == rds.md_hash(WITH_C1) and snap["telling"] == []
    assert [c["id"] for c in snap["comments"]] == ["c1"] and snap["malformed"] == []
    assert rendered == [] and events == []


def test_a_rebuild_renders_the_same_text_again_and_says_the_page_is_not_the_same(made):
    doc, md, rendered, events, _ = made(WITH_C1)
    snap = doc.rebuild()
    assert rendered == [WITH_C1] and md.read_text(encoding="utf-8") == WITH_C1
    assert events == [("changed", snap)] and snap["textSame"] is False
    assert snap["hash"] == rds.md_hash(WITH_C1)


# ── the product named in the expiry, and an answer written by the agent (SPEC 8.9, 11.2) ──────

def test_the_expiry_names_the_product_of_the_session_told(made):
    doc, md, rendered, events, clock = made(WITH_C1)
    doc.await_reply("c1")
    clock.t += 601
    doc.expire(600, "Claude Code")
    assert events == [("tell-failed", {"id": "c1", "error":
                       "no reply from the Claude Code session after 10 min. It may be busy, "
                       "closed, or it answered in its own chat. Tell again, or reply here."})]


def test_nothing_observed_means_nothing_said(made):
    doc, md, rendered, events, clock = made(WITH_C1)
    doc.await_reply("c1")
    doc.observe(None)
    doc.observe(State("gone"))
    doc.observe(State("idle"))
    assert events == [] and doc.session_question() == ""


def test_an_answer_is_a_reply_by_the_agent_announced_with_the_text_it_was_measured_from(made):
    doc, md, rendered, events, _ = made(WITH_C1)
    snap = doc.reply_as("c1", "It is fine.", "Claude", "answer", "ask-done")
    text = md.read_text(encoding="utf-8")
    c = rdc.parse(text).by_id("c1")
    assert [(r.by, r.role, r.text) for r in c.replies] == [("Claude", "answer", "It is fine.")]
    assert rendered[-1] == text
    [(name, data)] = events
    assert name == "ask-done" and data["id"] == "c1"
    assert data["hash"] == rds.md_hash(text) and data["base"] == rds.md_hash(WITH_C1)
    assert data["textSame"] is True
    assert data["comments"][0]["replies"][0]["role"] == "answer"
    assert snap["hash"] == data["hash"] and snap["base"] == data["base"]
    assert doc.refresh() is None                          # the watcher has nothing left to announce


def test_an_answer_over_text_that_moved_on_says_the_prose_is_not_the_pages(made):
    """An outside edit the hub has not caught up with: the tabs hold the old text, so the
    answer must not be adopted by them over it."""
    doc, md, rendered, events, _ = made(WITH_C1)
    rds.update_file(md, lambda t: t.replace("First paragraph.", "First, reworded."))
    doc.reply_as("c1", "It is fine.", "Claude", "answer", "ask-done")
    [(name, data)] = events
    assert data["textSame"] is False and data["base"] == rds.md_hash(WITH_C1)


def test_an_answer_to_a_thread_that_is_gone_writes_and_says_nothing(made):
    doc, md, rendered, events, _ = made(WITH_C1)
    before = md.read_text(encoding="utf-8")
    with pytest.raises(rdc.AnchorError):
        doc.reply_as("c9", "x", "Claude", "answer", "ask-done")
    assert md.read_text(encoding="utf-8") == before and events == []


def test_an_answer_does_not_end_a_tell_wait_unless_its_role_is_action(made):
    doc, md, rendered, events, _ = made(WITH_C1)
    doc.await_reply("c1")
    doc.reply_as("c1", "Just an answer.", "Claude", "answer", "ask-done")
    assert doc.waiting() == ["c1"]


def test_announce_publishes_the_snapshot_measured_from_the_text_the_tabs_hold(made):
    doc, md, rendered, events, _ = made()
    held = doc._text
    rds.update_file(md, lambda t: t.replace("First paragraph.", "First, reworded."))
    doc._rerender()
    snap = doc._snapshot(doc._text)
    sent = doc._announce(snap, held, "ask-done", id="c1")
    measured = {"textSame": False, "base": rds.md_hash(held)}
    assert events == [("ask-done", {**snap, **measured, "id": "c1"})]
    assert sent == {**snap, **measured}                  # the extras are not in it
    assert "id" not in snap and "base" not in snap       # the caller's snapshot is not changed


# A save the page gave up after 120 s (SPEC 8.5, 10.3) may have been written all the same. The page sends it again with
# the same request id, as a comment is, and the hub that took it answers as it answered the first time and writes
# nothing again.
SAVE_RID = "s0123456789abcdef"
SPLIT = "<p>Other paragraph, first half.</p><p>Other paragraph, second half.</p>"


def test_a_save_sent_again_with_its_request_id_is_written_once(made):
    doc, md, rendered, events, _ = made()
    base = rds.md_hash(DOC)
    first = doc.save(base, edit_other(DOC), rid=SAVE_RID)
    once = md.read_text(encoding="utf-8")
    again = doc.save(base, edit_other(DOC), rid=SAVE_RID)
    assert md.read_text(encoding="utf-8") == once and len(rendered) == 1
    assert again == {**first, "again": True} and "again" not in first
    (name, data), = events
    assert name == "changed" and data["rid"] == SAVE_RID      # the tab that gave up hears that it was taken


# a Restore that timed out and was written late, pressed again, split a paragraph twice.
def test_a_save_that_splits_a_paragraph_sent_again_splits_it_once(made):
    doc, md, *_ = made()
    base = rds.md_hash(DOC)
    doc.save(base, edit_other(DOC, SPLIT), rid=SAVE_RID)
    once = md.read_text(encoding="utf-8")
    again = doc.save(base, edit_other(DOC, SPLIT), rid=SAVE_RID)
    assert again["again"] is True and md.read_text(encoding="utf-8") == once
    assert once.count("second half") == 1 and "conflict" not in prose(once).lower()


# a save that was written late, and a later save of the same block made before the reload, are each applied
# once. The first, sent again, does not take the second's text away.
def test_an_earlier_save_sent_again_after_a_later_one_changes_nothing(made):
    doc, md, *_ = made()
    base = rds.md_hash(DOC)
    first = doc.save(base, edit_other(DOC, "<p>Other paragraph, one.</p>"), rid=SAVE_RID)
    later = doc.save(base, [{**edit_other(DOC, "<p>Other paragraph, two.</p>")[0],
                             "saved": "<p>Other paragraph, one.</p>"}], rid=SAVE_RID + "b")
    text = md.read_text(encoding="utf-8")
    assert "two." in text and later["merged"] is True
    again = doc.save(base, edit_other(DOC, "<p>Other paragraph, one.</p>"), rid=SAVE_RID)
    assert again["again"] is True and again["hash"] == first["hash"]
    assert md.read_text(encoding="utf-8") == text


def test_a_save_sent_again_with_other_edits_is_another_save(made):
    doc, md, *_ = made()
    base = rds.md_hash(DOC)
    doc.save(base, edit_other(DOC, "<p>Other paragraph, one.</p>"), rid=SAVE_RID)
    got = doc.save(base, edit_other(DOC, "<p>Other paragraph, one and more.</p>"), rid=SAVE_RID)
    assert "again" not in got and "one and more." in md.read_text(encoding="utf-8")


def test_a_save_sent_again_with_another_saved_field_is_still_the_same_save(made):
    doc, md, *_ = made()
    base = rds.md_hash(DOC)
    doc.save(base, edit_other(DOC), rid=SAVE_RID)
    once = md.read_text(encoding="utf-8")
    again = doc.save(base, [{**edit_other(DOC)[0], "saved": "<p>Other paragraph, saved.</p>"}], rid=SAVE_RID)
    assert again["again"] is True and md.read_text(encoding="utf-8") == once


def test_a_save_that_was_refused_is_not_remembered(made):
    doc, md, *_ = made()
    with pytest.raises(rds.StaleError):
        doc.save("0" * 16, edit_other(DOC), rid=SAVE_RID)
    got = doc.save(rds.md_hash(DOC), edit_other(DOC), rid=SAVE_RID)
    assert "again" not in got and got["changed"] != []


def test_a_save_without_a_request_id_is_never_taken_for_another(made):
    doc, md, rendered, events, _ = made()
    base = rds.md_hash(DOC)
    first = doc.save(base, edit_other(DOC))
    second = doc.save(base, edit_other(DOC))
    assert "again" not in first and "again" not in second
    assert all("rid" not in d for _, d in events)


# the page that was reloaded or closed after a timed-out save asks which ids the hub took, and drops the draft.
def test_the_ids_of_saves_are_named_with_those_of_comments(made):
    doc, *_ = made(WITH_C1)
    doc.save(rds.md_hash(WITH_C1), edit_other(WITH_C1), rid=SAVE_RID)
    doc.comment("reply", {"id": "c1", "body": "One"}, "", rid=RID)
    assert doc.taken_rids() == [RID, SAVE_RID]


def test_a_save_and_a_comment_with_one_request_id_are_not_taken_for_each_other(made):
    doc, md, *_ = made(WITH_C1)
    base = rds.md_hash(WITH_C1)
    doc.save(base, edit_other(WITH_C1), rid=RID)
    got = doc.comment("reply", {"id": "c1", "body": "Done"}, "", rid=RID)
    assert "again" not in got and len(rdc.parse(md.read_text(encoding="utf-8")).by_id("c1").replies) == 1
    assert doc.save(base, edit_other(WITH_C1), rid=RID)["again"] is True      # each is still remembered


# The many saves of an editing page do not push a comment's id out of the ones kept.
def test_the_saves_kept_never_push_out_a_comments_id(made, monkeypatch):
    monkeypatch.setattr(rdl, "RIDS", 2)
    doc, md, *_ = made(WITH_C1)
    doc.comment("reply", {"id": "c1", "body": "One"}, "", rid=RID)
    for n in "123":
        doc.save(rds.md_hash(WITH_C1), edit_other(WITH_C1, f"<p>Other {n}.</p>"), rid=SAVE_RID + n)
    assert doc.taken_rids() == [RID, SAVE_RID + "2", SAVE_RID + "3"]


def test_a_save_that_changed_nothing_sent_again_is_answered_as_taken(made):
    doc, md, rendered, events, _ = made()
    same = [{"i": block_of(DOC, "Other paragraph"), "html": "<p>Other paragraph.</p>"}]
    first = doc.save(rds.md_hash(DOC), same, rid=SAVE_RID)
    again = doc.save(rds.md_hash(DOC), same, rid=SAVE_RID)
    assert first["changed"] == [] and again == {**first, "again": True} and events == []
