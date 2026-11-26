"""Archive and Keep on a member's loose pages (SPEC 8.6, 9.9): a page quiet for `archive_after` days leaves the default
view for "Archived" and still opens at its address; a write or a new comment brings it back, an open does not; Keep
and `--keep` pages are never archived; a hub's first boot archives nothing, whatever the pages' mtimes. Through the
handler in proxy mode and the door, in memory, with the hub's clock under test control."""
import json
import os
import threading
import time

import pytest
from helpers import BEA, CAL, comment, door, rpc
from test_hub_commits import DOC, box, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)
from test_share import tick
from test_write_log import agents  # noqa: F401  (fixture)

from sheafmd import config
from sheafmd.hub import archive, loose, state
from sheafmd.hub import roots as roots_mod

DAY = 86400
TEXT = "# Notes\n\nA first page.\n\nSecond paragraph.\n"


class Clock:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now


@pytest.fixture
def clock(agents):
    agents.hub.clock = Clock()
    return agents.hub.clock


def call(agents, who, tool, **args):
    res = door(agents.door, rpc("tools/call", {"name": tool, "arguments": args}), token=agents.tokens[who], as_name=None)
    assert res.status == 200, res.text
    out = res.json()["result"]
    return out["isError"], out["content"][0]["text"]


def made(agents, who, text=TEXT, **args):
    bad, out = call(agents, who, "create", doc=args.pop("doc", "notes.md"), text=text, **args)
    assert not bad, out
    return json.loads(out)["doc"]


def age(agents, doc, days, clock):
    """The page's last write was `days` days before the clock."""
    t = clock.now - days * DAY
    os.utime(agents.hub.file(doc), (t, t))


def rows(agents, member=BEA, view=None):
    got = agents.get("/_/mount?sheaf=1" + (f"&view={view}" if view else ""), member=member)
    assert got.status == 200, got.text
    return [r for r in got.json()["sheaf"]["rows"] if not r["doc"].startswith("rectoversos/")]      # the fixture's own registered root is no loose page


def docs(agents, member=BEA, view=None):
    return [r["doc"] for r in rows(agents, member, view)]


def sweep(agents):
    archive.sweep(agents.hub)


def root_of(agents, doc):
    return agents.hub.roots.get(doc.split("/")[0])


# ── AC 1: the thirty-first day ───────────────────────────────────────────────

def test_a_quiet_page_is_archived_after_the_thirty_first_day(agents, clock):
    doc = made(agents, "bea-claude")
    sweep(agents)                                   # first seen now: nothing counts before this
    age(agents, doc, 30, clock)
    clock.now += 30 * DAY
    sweep(agents)
    assert docs(agents) == [doc]                    # day 30: not archived
    clock.now += DAY + 1
    sweep(agents)
    assert docs(agents) == []                       # day 31: out of the default view
    assert docs(agents, view="archived") == [doc]
    assert agents.get(f"/{doc}", member=BEA).status == 200      # still opens at its address


def test_an_archived_page_is_not_in_the_default_view_and_is_in_archived(agents, clock):
    doc = made(agents, "bea-claude")
    sweep(agents)
    clock.now += 31 * DAY
    sweep(agents)
    assert docs(agents) == [] and docs(agents, view="archived") == [doc]
    assert [r["archived"] for r in rows(agents, view="archived")] == [True]


def test_a_write_brings_an_archived_page_back_to_the_default_view(agents, clock):
    doc = made(agents, "bea-claude")
    sweep(agents)
    clock.now += 31 * DAY
    sweep(agents)
    assert docs(agents) == []
    t = clock.now + 5
    os.utime(agents.hub.file(doc), (t, t))          # a write after the mark
    assert docs(agents) == [doc]
    assert docs(agents, view="archived") == []
    sweep(agents)
    assert docs(agents) == [doc]                    # and the sweep does not archive it again at once


def test_a_new_comment_brings_it_back(agents, clock):
    doc = made(agents, "bea-claude")
    sweep(agents)
    clock.now += 31 * DAY
    sweep(agents)
    assert docs(agents) == []
    comment(agents.hub.file(doc))
    t = clock.now + 5
    os.utime(agents.hub.file(doc), (t, t))
    assert docs(agents) == [doc]


def test_opening_an_archived_page_does_not_bring_it_back(agents, clock):
    doc = made(agents, "bea-claude")
    sweep(agents)
    clock.now += 31 * DAY
    sweep(agents)
    before = os.stat(agents.hub.file(doc)).st_mtime_ns
    assert agents.get(f"/{doc}", member=BEA).status == 200
    assert agents.get(f"/_/mount?doc={doc}", member=BEA).status in (200, 404)
    assert os.stat(agents.hub.file(doc)).st_mtime_ns == before
    assert docs(agents) == [] and docs(agents, view="archived") == [doc]


def test_a_page_with_an_open_comment_is_never_archived_and_is_once_it_is_resolved_and_quiet(agents, clock):
    doc = made(agents, "bea-claude")
    comment(agents.hub.file(doc))
    sweep(agents)
    age(agents, doc, 90, clock)
    clock.now += 90 * DAY
    sweep(agents)
    assert docs(agents) == [doc]                    # quiet for 90 days with a comment open


def test_a_mark_is_in_the_roots_sheaf_folder_and_not_in_the_text(agents, clock):
    doc = made(agents, "bea-claude")
    before = (agents.hub.file(doc).read_bytes(), os.stat(agents.hub.file(doc)).st_mtime_ns)
    sweep(agents)
    clock.now += 31 * DAY
    sweep(agents)
    assert (agents.hub.file(doc).read_bytes(), os.stat(agents.hub.file(doc)).st_mtime_ns) == before
    marks = root_of(agents, doc).path / ".sheaf"
    assert json.loads((marks / "archived.json").read_text())
    assert json.loads((marks / "seen.json").read_text())


def test_archive_now_archives_at_once_and_restore_brings_it_back_and_it_stays_back(agents, clock):
    doc = made(agents, "bea-claude")
    assert agents.post("/_/archive", {"doc": doc}, member=BEA).status == 200
    assert docs(agents) == [] and docs(agents, view="archived") == [doc]
    assert agents.post("/_/restore", {"doc": doc}, member=BEA).status == 200
    assert docs(agents) == [doc]
    clock.now += 30 * DAY - 10
    sweep(agents)
    assert docs(agents) == [doc]                    # restoring restarted the page's own clock


def test_a_recipient_sees_a_shared_page_in_archived_when_the_owner_has_it_archived_and_has_no_archive_action(agents, clock):
    doc = made(agents, "bea-claude", text="# Shared\n\n- [ ] Share with cal\n\nA plan.\n")
    assert tick(agents, BEA, doc, "Share with").status == 200
    assert docs(agents, CAL) != []
    assert agents.post("/_/archive", {"doc": doc}, member=BEA).status == 200
    assert docs(agents, CAL) == []
    assert len(docs(agents, CAL, view="archived")) == 1
    assert agents.post("/_/archive", {"doc": doc}, member=CAL).status in (403, 404)
    assert agents.post("/_/keep", {"doc": doc, "on": True}, member=CAL).status in (403, 404)


# ── AC 2: archive_after, Keep ────────────────────────────────────────────────

def test_archive_after_in_the_roots_toml_changes_the_days(agents, clock):
    doc = made(agents, "bea-claude")
    age(agents, doc, 0, clock)                      # ticket 208: written at the clock, not seconds after it under load
    (root_of(agents, doc).path / ".sheaf.toml").write_text("archive_after = 7\n", encoding="utf-8")
    sweep(agents)
    clock.now += 7 * DAY + 1
    sweep(agents)
    assert docs(agents, view="archived") == [doc]
    (root_of(agents, doc).path / ".sheaf.toml").write_text("archive_after = 90\n", encoding="utf-8")
    assert agents.post("/_/restore", {"doc": doc}, member=BEA).status == 200
    clock.now += 89 * DAY
    sweep(agents)
    assert docs(agents) == [doc]


@pytest.mark.parametrize("bad", ["0", '"x"', "-3", "2.5"])
def test_a_bad_archive_after_warns_and_the_default_holds(tmp_path, bad):
    (tmp_path / ".sheaf.toml").write_text(f"archive_after = {bad}\n", encoding="utf-8")
    said = []
    assert config.load_root_config(tmp_path, said.append).archive_after == 30
    assert said and "archive_after" in said[0]


def test_the_default_archive_after_is_thirty_days(tmp_path):
    assert config.load_root_config(tmp_path).archive_after == 30


def test_a_kept_page_is_never_archived_however_quiet(agents, clock):
    doc = made(agents, "bea-claude")
    assert agents.post("/_/keep", {"doc": doc, "on": True}, member=BEA).status == 200
    sweep(agents)
    age(agents, doc, 400, clock)
    clock.now += 400 * DAY
    sweep(agents)
    assert docs(agents) == [doc] and [r["kept"] for r in rows(agents)] == [True]


def test_a_page_created_with_keep_through_the_door_is_never_archived(agents, clock):
    doc = made(agents, "bea-claude", keep=True)
    sweep(agents)
    clock.now += 400 * DAY
    sweep(agents)
    assert docs(agents) == [doc] and [r["kept"] for r in rows(agents)] == [True]


def test_keep_on_an_archived_page_brings_it_back(agents, clock):
    doc = made(agents, "bea-claude")
    assert agents.post("/_/archive", {"doc": doc}, member=BEA).status == 200
    assert agents.post("/_/keep", {"doc": doc, "on": True}, member=BEA).status == 200
    assert docs(agents) == [doc]


def test_keep_toggles_off_again_with_the_same_control(agents, clock):
    doc = made(agents, "bea-claude", keep=True)
    assert agents.post("/_/keep", {"doc": doc, "on": False}, member=BEA).status == 200
    assert [r["kept"] for r in rows(agents)] == [False]
    assert loose.marks(root_of(agents, doc).path) == []


def test_keep_is_the_owners_alone_on_the_row_and_the_route(agents, clock):
    doc = made(agents, "bea-claude", text="# Shared\n\n- [ ] Share\n\nA plan.\n")
    assert tick(agents, BEA, doc, "Share").status == 200
    assert agents.post("/_/keep", {"doc": doc, "on": True}, member=CAL).status in (403, 404)
    assert loose.marks(root_of(agents, doc).path) == []


def test_a_keep_file_that_cannot_be_read_stops_that_root_and_archives_nothing_of_it(agents, clock):
    doc = made(agents, "bea-claude", keep=True)
    other = made(agents, "bea-claude", doc="other.md")
    sweep(agents)
    marks = root_of(agents, doc).path / ".sheaf"
    (marks / "keep.json").write_text("{not a list", encoding="utf-8")
    clock.now += 400 * DAY
    sweep(agents)                                           # the root is refused whole and the sweep goes on
    assert not (marks / "archived.json").exists()
    assert set(docs(agents)) >= {other}


def test_a_root_whose_marks_cannot_be_read_does_not_stop_the_sweep_of_the_next_member(agents, clock):
    mine = made(agents, "bea-claude", doc="bea.md")
    theirs = made(agents, "cal-claude", doc="cal.md")
    sweep(agents)                                           # first seen of both
    (root_of(agents, mine).path / ".sheaf" / "keep.json").write_text("{not a list", encoding="utf-8")
    clock.now += 31 * DAY
    sweep(agents)
    assert docs(agents, member=CAL, view="archived") == [theirs]
    assert docs(agents, member=BEA, view="archived") == []


def test_the_sweep_covers_the_pages_past_the_listing_cap(agents, clock, monkeypatch):
    monkeypatch.setattr(roots_mod, "LIST_CAP", 2)
    made_ = [made(agents, "bea-claude", doc=f"p{i}.md") for i in range(4)]
    sweep(agents)
    clock.now += 31 * DAY
    sweep(agents)
    archived = loose.times(root_of(agents, made_[0]).path, archive.ARCHIVED)
    assert sorted(rel.rpartition("/")[2] for rel in archived) == [f"p{i}.md" for i in range(4)]


def test_the_hub_tick_runs_the_sweep_every_ten_minutes_and_at_start(agents, clock):
    doc = made(agents, "bea-claude")
    agents.hub.tick()                                       # the first tick sweeps: first seen is written
    agents.hub.archive.settle()
    assert (root_of(agents, doc).path / ".sheaf" / "seen.json").exists()
    clock.now += 31 * DAY
    agents.hub.tick()
    agents.hub.archive.settle()
    assert docs(agents, view="archived") == [doc]


def test_a_slow_sweep_does_not_delay_the_tick(agents, clock, monkeypatch):
    release, ran = threading.Event(), []

    def slow(self):
        release.wait(5)
        ran.append(threading.current_thread())
    monkeypatch.setattr(archive.Archive, "sweep", slow)
    agents.hub.tick()
    assert ran == []                                        # the tick came back with the sweep still running
    release.set()
    agents.hub.archive.settle()
    assert ran and ran[0] is not threading.current_thread()


# ── AC 5: the first boot (R18) ───────────────────────────────────────────────

def test_a_page_with_a_year_old_mtime_is_not_archived_at_first_boot(agents, clock):
    doc = made(agents, "bea-claude")
    age(agents, doc, 365, clock)
    sweep(agents)
    assert docs(agents) == [doc]


def test_it_is_archived_at_first_seen_plus_archive_after_and_not_before(agents, clock):
    doc = made(agents, "bea-claude")
    age(agents, doc, 365, clock)
    sweep(agents)
    clock.now += 30 * DAY
    sweep(agents)
    assert docs(agents) == [doc]
    clock.now += DAY
    sweep(agents)
    assert docs(agents) == []


def test_a_page_that_arrives_later_with_an_old_mtime_gets_its_own_first_seen(agents, clock):
    first = made(agents, "bea-claude")
    sweep(agents)
    clock.now += 20 * DAY
    later = made(agents, "bea-claude", doc="later.md")
    age(agents, later, 365, clock)
    sweep(agents)
    clock.now += 11 * DAY
    sweep(agents)
    assert docs(agents) == [later]                  # the first is archived at 31 days, the later one is 11 days in
    assert docs(agents, view="archived") == [first]


def test_first_seen_never_moves_once_written(agents, clock):
    doc = made(agents, "bea-claude")
    sweep(agents)
    seen = root_of(agents, doc).path / ".sheaf" / "seen.json"
    first = json.loads(seen.read_text())
    clock.now += 5 * DAY
    sweep(agents)
    assert json.loads(seen.read_text()) == first


def test_the_sweep_with_no_seen_file_writes_it_before_it_archives_anything(agents, clock):
    doc = made(agents, "bea-claude")
    age(agents, doc, 365, clock)
    seen = root_of(agents, doc).path / ".sheaf" / "seen.json"
    assert not seen.exists()
    sweep(agents)
    assert seen.exists() and docs(agents) == [doc]
    assert not (root_of(agents, doc).path / ".sheaf" / "archived.json").exists()


# ── what the Sheaf's data tells the page ─────────────────────────────────────

def test_a_row_of_the_owners_own_loose_page_says_so_and_the_counts_say_what_the_other_views_hold(agents, clock):
    doc = made(agents, "bea-claude")
    other = made(agents, "bea-claude", doc="other.md")
    assert agents.post("/_/archive", {"doc": other}, member=BEA).status == 200
    got = agents.get("/_/mount?sheaf=1", member=BEA).json()["sheaf"]
    mine = {r["doc"]: r for r in got["rows"]}
    assert mine[doc]["own"] is True and mine[doc]["archived"] is False and mine[doc]["kept"] is False
    assert got["counts"] == {"archived": 1, "trash": 0} and got["view"] == "default"
    assert agents.get("/_/mount?sheaf=1&view=archived", member=BEA).json()["sheaf"]["view"] == "archived"


def test_a_registered_root_page_is_no_ones_to_archive_or_keep_from_the_row(agents, clock):
    got = agents.get("/_/mount?sheaf=1", member=BEA).json()["sheaf"]
    assert [r["own"] for r in got["rows"] if r["doc"].startswith("rectoversos/")] == [False]
    assert agents.post("/_/archive", {"doc": "rectoversos/acme/blog/2026-10-28-plan.md"}, member=BEA).status == 404


def test_a_keep_that_comes_between_the_sweeps_read_and_its_move_leaves_the_page_not_archived(agents, clock, monkeypatch):
    doc = made(agents, "bea-claude")
    sweep(agents)
    clock.now += 31 * DAY
    root, rel = root_of(agents, doc), doc.split("/", 1)[1]
    kept, real_due = [], archive.due

    def due(*args, **kw):
        out = real_due(*args, **kw)
        racer = threading.Thread(target=lambda: agents.hub.archive.keep(root, rel, True, 0.0))
        racer.start()
        racer.join(0.3)                 # a Keep that can come in between the read and the move would be done by now
        kept.append(racer)
        return out
    monkeypatch.setattr(archive, "due", due)
    sweep(agents)
    kept[0].join(5)
    assert not kept[0].is_alive()
    assert docs(agents, view="archived") == [] and docs(agents) == [doc]
    assert rel in loose.marks(root.path)


def test_archive_now_on_a_kept_page_is_refused_with_a_line_and_never_archives_it(agents, clock):
    doc = made(agents, "bea-claude", keep=True)
    got = agents.post("/_/archive", {"doc": doc}, member=BEA)
    assert got.status == 409 and "kept" in got.text and "Keep" in got.text
    assert docs(agents) == [doc] and docs(agents, view="archived") == []
    assert agents.post("/_/keep", {"doc": doc, "on": False}, member=BEA).status == 200
    assert agents.post("/_/archive", {"doc": doc}, member=BEA).status == 200
    assert docs(agents, view="archived") == [doc]
