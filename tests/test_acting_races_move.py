"""Keep and Archive against a Move (SPEC 8.6, 9.11, "One lock order"): `Handler._acting` reads the page's path in its root
(`_own_loose`) and then writes the mark. A Move that runs between the two carries the marks of the old path to the new one
(`loose.marks_moved`) before the write, and the write then lands at the old path, a mark of a page that is not there. The
two acts take the moves' lock from the read to the write, so a Move comes before the read or after the write, never between.
Through the handler as the proxy sets it. Not run on a laptop: they start a hub, so CI is their run."""
import json
import threading

import pytest
import test_share
from test_move_forward import ALICE, at, in_folder, move

from sheafmd.hub import handler as handler_mod

team = test_share.team

OLD, NEW = "a/plan.md", "b/plan.md"


def mark_paths(root, name):
    f = root.path / ".sheaf" / name
    if not f.exists():
        return set()
    data = json.loads(f.read_text())
    return set(data)


@pytest.mark.parametrize("act,mark_file,body", [("keep", "keep.json", {"on": True}), ("archive", "archived.json", {})])
def test_a_move_between_the_read_of_the_path_and_the_write_of_the_mark_leaves_no_mark_at_the_old_path(team, monkeypatch, act, mark_file, body):
    """The Keep or Archive has read the path and stops before it writes; a Move of the page comes in. Whichever of the two
    ends first, the mark is at the new path or the act found no page (404), and no mark is left at the old path."""
    old = in_folder(team, "a")
    read, go, out = threading.Event(), threading.Event(), {}
    real = handler_mod.Handler._own_loose

    def own_loose(self, req, doc):
        got = real(self, req, doc)
        if threading.current_thread().name == "acting":
            read.set()
            assert go.wait(20)
        return got
    monkeypatch.setattr(handler_mod.Handler, "_own_loose", own_loose)
    actor = threading.Thread(name="acting", target=lambda: out.update(act=team.post(f"/_/{act}", {"doc": old, **body}, member=ALICE)))
    actor.start()
    assert read.wait(20)
    mover = threading.Thread(target=lambda: out.update(move=move(team, ALICE, old, "b")))
    mover.start()
    mover.join(1.5)
    go.set()
    actor.join(20)
    mover.join(20)
    assert out["move"].status == 200, out["move"].text
    assert out["act"].status in (200, 404), out["act"].text
    root = team.hub.roots.get("loose-alice")
    marked = mark_paths(root, mark_file)
    assert OLD not in marked, f"a {act} mark is left at the old path {OLD}"
    if out["act"].status == 200:
        assert marked == {NEW}, marked
