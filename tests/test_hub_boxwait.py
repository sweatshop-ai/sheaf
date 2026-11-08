"""The wait of a Tell the hub drops for James's window (SPEC 9.12): a drop is always a Tell, so `add` takes no kind."""
from sheafmd import comments as rdc
from sheafmd.hub import boxwait

DOC = "Par one.\n\nPar two.\n"


def test_a_drop_added_with_no_kind_is_pending_as_a_tell():
    md, cid = rdc.add_comment(DOC, 0, 0, 3, "Par", "Send the draft.", "Hans", "2026-11-09T10:00")
    waits = boxwait.BoxWaits(lambda: 100.0)
    waits.add("x.md", cid, md, "drop-1")
    assert waits.pending("x.md", md) == [{"id": cid, "kind": "tell", "state": "sent"}]
    (doc, thread, drop), = waits.drops()
    assert (doc, thread, drop.name) == ("x.md", cid, "drop-1")
