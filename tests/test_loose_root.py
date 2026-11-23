"""A member's loose root: a door `create` with no root writes into `loose-<short>`, made on the member's first
`create`, in the folder the agent named, else the month. Read at the handler seam in proxy mode, in memory."""
import dataclasses
import json
import os

import pytest
from helpers import BEA, CAL, door, rpc
from test_hub_commits import DOC, box, git, merged_on_github, rectoversos, remote  # noqa: F401  (fixtures)
from test_write_log import agents  # noqa: F401  (fixture)

from sheafmd.hub import loose
from sheafmd.source import md_hash

TEXT = "# Notes\n\nA first page.\n"


def call(agents, who, tool, **args):
    """The door's answer to one call: (is it an error, the text of its content)."""
    res = door(agents.door, rpc("tools/call", {"name": tool, "arguments": args}), token=agents.tokens[who],
               as_name=None)
    assert res.status == 200, res.text
    out = res.json()["result"]
    return out["isError"], out["content"][0]["text"]


def made(agents, who, **args):
    bad, text = call(agents, who, "create", **args)
    assert not bad, text
    return json.loads(text)


def test_the_first_create_makes_the_loose_root_and_puts_the_page_in_the_month(agents):
    out = made(agents, "bea-claude", doc="notes.md", text=TEXT)
    assert out["doc"] == f"loose-bea/{loose.month()}/notes.md"
    assert agents.hub.file(out["doc"]).read_text(encoding="utf-8").endswith("A first page.\n")
    assert agents.hub.roots.get("loose-bea") is not None


def test_a_folder_argument_puts_the_page_there_instead(agents):
    out = made(agents, "bea-claude", doc="notes.md", text=TEXT, folder="projects/blog")
    assert out["doc"] == "loose-bea/projects/blog/notes.md"
    assert agents.hub.file(out["doc"]).is_file()


def test_a_second_create_uses_the_same_root(agents):
    a = made(agents, "bea-claude", doc="a.md", text=TEXT)
    b = made(agents, "bea-claude", doc="b.md", text=TEXT, folder="x")
    assert a["doc"].split("/")[0] == b["doc"].split("/")[0] == "loose-bea"


def test_create_on_an_existing_path_is_refused_and_leaves_the_page(agents):
    first = made(agents, "bea-claude", doc="notes.md", text=TEXT)
    bad, why = call(agents, "bea-claude", "create", doc="notes.md", text="# Other\n")
    assert bad, why
    assert agents.hub.file(first["doc"]).read_text(encoding="utf-8").startswith("# Notes")


def test_update_with_a_stale_hash_is_refused_and_writes_nothing(agents):
    out = made(agents, "bea-claude", doc="notes.md", text=TEXT)
    stale = md_hash("# Not what the file holds\n")
    bad, why = call(agents, "bea-claude", "update", doc=out["doc"], text="# Replaced\n", expected_hash=stale)
    assert bad, why
    assert agents.hub.file(out["doc"]).read_text(encoding="utf-8").startswith("# Notes")
    ok, _ = call(agents, "bea-claude", "update", doc=out["doc"], text=TEXT + "More.\n", expected_hash=out["hash"])
    assert not ok


def test_the_door_has_no_delete_and_asking_for_one_is_refused(agents):
    out = made(agents, "bea-claude", doc="notes.md", text=TEXT)
    res = door(agents.door, rpc("tools/call", {"name": "delete", "arguments": {"doc": out["doc"]}}),
               token=agents.tokens["bea-claude"], as_name=None)
    assert res.json().get("error") or res.json()["result"]["isError"]
    assert agents.hub.file(out["doc"]).is_file()
    listed = door(agents.door, rpc("tools/list"), token=agents.tokens["bea-claude"], as_name=None)
    assert "delete" not in [t["name"] for t in listed.json()["result"]["tools"]]


def test_another_member_cannot_read_the_page_through_the_door(agents):
    out = made(agents, "bea-claude", doc="notes.md", text=TEXT)
    bad, why = call(agents, "cal-claude", "read", doc=out["doc"])
    assert bad, why
    assert "A first page" not in why
    ok, _ = call(agents, "bea-claude", "read", doc=out["doc"])
    assert not ok


def test_keep_is_stored_in_the_roots_sheaf_folder_not_in_the_text(agents):
    out = made(agents, "bea-claude", doc="notes.md", text=TEXT, keep=True)
    assert agents.hub.file(out["doc"]).read_text(encoding="utf-8").count("keep") == 0
    root = agents.hub.roots.get("loose-bea")
    assert loose.kept(root.path, out["doc"].split("/", 1)[1])
    plain = made(agents, "bea-claude", doc="plain.md", text=TEXT)
    assert not loose.kept(root.path, plain["doc"].split("/", 1)[1])


def test_two_members_with_the_same_short_name_never_share_a_root(agents):
    """Cal's short is empty and his name derives to `bea`: Bea's root is Bea's, Cal gets another."""
    agents.hub.proxy.members[CAL] = dataclasses.replace(agents.hub.proxy.members[CAL], name="Bea", short="")
    a = made(agents, "bea-claude", doc="notes.md", text=TEXT)
    c = made(agents, "cal-claude", doc="notes.md", text=TEXT)
    assert a["doc"].split("/")[0] != c["doc"].split("/")[0]
    assert agents.hub.owns(agents.hub.proxy.members[BEA], agents.hub.roots.get(a["doc"].split("/")[0]))
    assert not agents.hub.owns(agents.hub.proxy.members[CAL], agents.hub.roots.get(a["doc"].split("/")[0]))
    bad, _ = call(agents, "cal-claude", "read", doc=a["doc"])
    assert bad


def test_a_renamed_member_keeps_their_root_and_the_old_short_name_is_not_theirs_to_take(agents):
    first = made(agents, "bea-claude", doc="notes.md", text=TEXT)
    root = first["doc"].split("/")[0]
    # Bea is renamed; the name she had goes to Cal, who makes his first page
    members = agents.hub.proxy.members
    members[BEA] = dataclasses.replace(members[BEA], name="Beatrice", short="beatrice")
    members[CAL] = dataclasses.replace(members[CAL], short="bea")
    agents.hub.loose.attach()
    again = made(agents, "bea-claude", doc="second.md", text=TEXT)
    assert again["doc"].split("/")[0] == root                      # still hers
    cal = made(agents, "cal-claude", doc="notes.md", text=TEXT)
    assert cal["doc"].split("/")[0] != root                        # his own, not hers
    bad, _ = call(agents, "cal-claude", "read", doc=first["doc"])
    assert bad
    ok, _ = call(agents, "bea-claude", "read", doc=first["doc"])
    assert not ok


def test_a_restart_finds_the_root_by_the_member_not_the_name(agents):
    first = made(agents, "bea-claude", doc="notes.md", text=TEXT)
    members = agents.hub.proxy.members
    members[BEA] = dataclasses.replace(members[BEA], name="Else", short="else", roots=members[BEA].roots[:1])   # as the config says it
    assert not agents.hub.owns(members[BEA], agents.hub.roots.get(first["doc"].split("/")[0]))
    agents.hub.loose.attach()
    assert agents.hub.owns(agents.hub.proxy.members[BEA], agents.hub.roots.get(first["doc"].split("/")[0]))


@pytest.mark.parametrize("folder", ["../outside", "a/../../outside", "/tmp/outside", "a//b", ".hidden", "./x/../.."])
def test_a_folder_that_leaves_the_root_is_refused_and_writes_nothing(agents, folder, tmp_path):
    bad, why = call(agents, "bea-claude", "create", doc="notes.md", text=TEXT, folder=folder)
    assert bad, why
    assert not (tmp_path / "outside").exists()
    root = agents.hub.roots.get("loose-bea")
    assert root is None or not list(root.path.rglob("notes.md"))


@pytest.mark.parametrize("name", ["../notes.md", "/tmp/notes.md", "a/b/../../../notes.md"])
def test_a_page_name_cannot_leave_the_root_either(agents, name):
    bad, why = call(agents, "bea-claude", "create", doc=name, text=TEXT, folder="x")
    assert bad, why


def test_a_link_inside_the_root_that_leads_out_is_refused(agents, tmp_path):
    made(agents, "bea-claude", doc="first.md", text=TEXT)
    root = agents.hub.roots.get("loose-bea")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    os.symlink(outside, root.path / "way-out")
    bad, why = call(agents, "bea-claude", "create", doc="notes.md", text=TEXT, folder="way-out")
    assert bad, why
    assert not list(outside.iterdir())
    bad, why = call(agents, "bea-claude", "create", doc="notes.md", text=TEXT, folder="way-out/deeper")
    assert bad, why
    assert not list(outside.iterdir())


def test_a_link_that_replaces_the_month_folder_is_refused(agents, tmp_path):
    made(agents, "bea-claude", doc="first.md", text=TEXT)
    root = agents.hub.roots.get("loose-bea")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (root.path / loose.month()).rename(root.path / "moved-away")
    os.symlink(outside, root.path / loose.month())
    bad, why = call(agents, "bea-claude", "create", doc="notes.md", text=TEXT)
    assert bad, why
    assert not list(outside.iterdir())


def test_a_page_that_is_already_a_link_is_never_written_through(agents, tmp_path):
    made(agents, "bea-claude", doc="first.md", text=TEXT, folder="x")
    root = agents.hub.roots.get("loose-bea")
    target = tmp_path / "target.md"
    os.symlink(target, root.path / "x" / "notes.md")
    bad, why = call(agents, "bea-claude", "create", doc="notes.md", text=TEXT, folder="x")
    assert bad, why
    assert not target.exists()


def test_a_create_the_watcher_sees_before_the_door_has_told_the_hub_leaves_no_disk_line(agents, monkeypatch):
    first = made(agents, "bea-claude", doc="notes.md", text=TEXT)
    e = agents.hub.entry(first["doc"])
    agents.hub.file(first["doc"]).unlink()                  # the hub still holds the page it knew under this name
    real = agents.hub.wrote

    def watcher_first(address, moved=False):
        agents.hub.catch_up(e)                              # the watcher looks at the file between the write and `wrote()`
        real(address, moved)

    monkeypatch.setattr(agents.hub, "wrote", watcher_first)
    made(agents, "bea-claude", doc="notes.md", text="# Again\n", folder=first["doc"].split("/")[1])
    agents.hub.catch_up(e)
    got = agents.get(f"/_/writes?doc={first['doc']}", member=BEA).json()
    assert [l["via"] for l in got["lines"]] == ["create", "create"]


# ── what a loose create may not leave behind, and where the root may stand (review round 2) ──────────────────────
def state(agents):
    from sheafmd import paths
    return paths.state_dir()


def nothing_made_for_cal(agents, members_before):
    """No loose root of Cal's: no folder, no registry entry, no hub root, no root added to the member."""
    loose_json = state(agents) / "loose.json"
    assert not loose_json.exists() or CAL not in json.loads(loose_json.read_text(encoding="utf-8"))
    assert not (state(agents) / "loose" / "loose-cal").exists()
    assert agents.hub.roots.get("loose-cal") is None
    assert agents.hub.proxy.members[CAL].roots == members_before


def test_a_state_folder_inside_a_git_work_tree_makes_no_loose_root_and_no_root_of_the_work_tree(agents):
    import subprocess
    subprocess.run(["git", "init", "-q", str(state(agents).parent)], check=True)
    roots_before = {r.name for r in agents.hub.roots.all()}
    bad, why = call(agents, "bea-claude", "create", doc="notes.md", text=TEXT)
    assert bad and "loose" in why, why
    assert {r.name for r in agents.hub.roots.all()} == roots_before         # the work tree is not taken as a root
    assert not (state(agents) / "loose" / "loose-bea").exists()
    assert agents.hub.roots.get("loose-bea") is None


def test_a_state_folder_under_a_registered_root_makes_no_loose_root_and_writes_nothing_into_that_root(agents):
    enclosing = agents.hub.roots.for_document(state(agents).parent / "x.md")      # a non-git root above the state folder
    bad, why = call(agents, "bea-claude", "create", doc="notes.md", text=TEXT)
    assert bad and "loose" in why, why
    assert not (state(agents) / "loose" / "loose-bea").exists()
    assert list(enclosing.path.glob("*/notes.md")) == []
    assert agents.hub.roots.get("loose-bea") is None


def test_a_corrupt_keep_mark_file_is_refused_never_read_as_empty_and_is_left_as_it_is(agents):
    first = made(agents, "bea-claude", doc="first.md", text=TEXT, keep=True)
    root = agents.hub.roots.get("loose-bea")
    marks = root.path / ".sheaf" / "keep.json"
    marks.write_text("{ not json", encoding="utf-8")
    bad, why = call(agents, "bea-claude", "create", doc="second.md", text=TEXT, keep=True)
    assert bad, why
    assert marks.read_text(encoding="utf-8") == "{ not json"
    assert not (root.path / loose.month() / "second.md").exists()                   # not left there unmarked
    assert (root.path / first["doc"].split("/", 1)[1]).is_file()
    assert [p.name for p in marks.parent.iterdir()] == ["keep.json"]                # no temp file left


def test_a_keep_mark_is_written_whole_by_a_replace(agents, monkeypatch):
    made(agents, "bea-claude", doc="first.md", text=TEXT, keep=True)
    root = agents.hub.roots.get("loose-bea")
    marks = root.path / ".sheaf" / "keep.json"
    seen = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b, *k, **kw: (seen.append(os.fspath(b)), real(a, b, *k, **kw))[1])
    made(agents, "bea-claude", doc="second.md", text=TEXT, keep=True)
    assert str(marks) in seen
    assert sorted(json.loads(marks.read_text(encoding="utf-8"))) == sorted(
        [f"{loose.month()}/first.md", f"{loose.month()}/second.md"])


@pytest.mark.parametrize("args", [
    {"doc": "notes.txt", "text": TEXT},
    {"doc": "..", "text": TEXT},
    {"doc": ".hidden.md", "text": TEXT},
    {"doc": "notes.md", "text": "x" * (1024 * 1024 + 1)},
    {"doc": "notes.md", "text": 'A.<!-- sheaf-comment id=c9 by="Zoe" at=2026-10-16T10:00 status=open quote="A"\nHi.\n-->\n'},
    {"doc": "notes.md", "text": TEXT, "folder": "../out"},
])
def test_a_refused_create_leaves_no_loose_root_no_registry_entry_no_folder(agents, args):
    before = agents.hub.proxy.members[CAL].roots
    bad, why = call(agents, "cal-claude", "create", **args)
    assert bad, why
    nothing_made_for_cal(agents, before)


def test_a_create_refused_after_the_root_is_made_takes_back_the_root_it_made(agents, monkeypatch):
    before = agents.hub.proxy.members[CAL].roots
    from sheafmd import mcp

    def refuse(self, *a, **k):
        raise mcp.ToolError("refused late", "path")
    monkeypatch.setattr(mcp.Door, "_make", refuse)
    bad, why = call(agents, "cal-claude", "create", doc="notes.md", text=TEXT)
    assert bad and "refused late" in why, why
    nothing_made_for_cal(agents, before)


def test_a_create_refused_after_its_folders_were_walked_leaves_none_of_the_folders_it_made(agents, monkeypatch):
    from sheafmd import mcp
    made(agents, "bea-claude", doc="first.md", text=TEXT, folder="x")
    root = agents.hub.roots.get("loose-bea")

    def refuse(self, *a, **k):
        raise mcp.ToolError("refused late", "path")
    monkeypatch.setattr(mcp.Door, "_make", refuse)
    bad, why = call(agents, "bea-claude", "create", doc="notes.md", text=TEXT, folder="x/deeper/still")
    assert bad and "refused late" in why, why
    assert (root.path / "x").is_dir() and not (root.path / "x" / "deeper").exists()
    bad, why = call(agents, "bea-claude", "create", doc="notes.md", text=TEXT, folder="new/chain")
    assert bad, why
    assert not (root.path / "new").exists()


def test_a_keep_mark_never_follows_a_link_for_its_folder_or_its_file(agents, tmp_path):
    made(agents, "bea-claude", doc="first.md", text=TEXT)
    root = agents.hub.roots.get("loose-bea")
    out = tmp_path / "out"
    out.mkdir()
    os.symlink(out, root.path / ".sheaf")
    bad, why = call(agents, "bea-claude", "create", doc="second.md", text=TEXT, keep=True)
    assert bad, why
    assert list(out.iterdir()) == []
    assert not (root.path / loose.month() / "second.md").exists()                   # no page left unmarked
    os.unlink(root.path / ".sheaf")
    (root.path / ".sheaf").mkdir()
    target = tmp_path / "target.json"
    os.symlink(target, root.path / ".sheaf" / "keep.json")
    bad, why = call(agents, "bea-claude", "create", doc="third.md", text=TEXT, keep=True)
    assert bad, why
    assert not target.exists()
    assert not (root.path / loose.month() / "third.md").exists()


# ── what a create takes back (ticket 28) ──────────────────────────────────────────────────────────────────────────
def test_a_create_that_fails_after_the_hub_expected_it_leaves_no_expectation_behind(agents, monkeypatch):
    from sheafmd import mcp

    def full(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(mcp, "create_file", full)
    bad, why = call(agents, "bea-claude", "create", doc="notes.md", text=TEXT)
    assert bad, why
    assert agents.hub.writes._own == {}


def test_a_keep_refused_after_the_page_was_made_leaves_no_expectation_behind(agents, monkeypatch):
    def refuse(*a, **k):
        raise loose.Refused("no marks today")
    monkeypatch.setattr(loose, "keep", refuse)
    bad, why = call(agents, "bea-claude", "create", doc="notes.md", text=TEXT, keep=True)
    assert bad, why
    assert agents.hub.writes._own == {}


def test_a_loose_root_is_taken_back_when_the_state_folder_is_reached_through_a_link(agents, tmp_path):
    member = agents.hub.proxy.members[CAL]
    root, fresh = agents.hub.loose.root_for(member)
    assert fresh
    link = tmp_path / "via-link"
    link.symlink_to(state(agents))
    loose_json = state(agents) / "loose.json"
    held = json.loads(loose_json.read_text(encoding="utf-8"))
    held[CAL] = str(link / "loose" / root.path.name)                # the same folder, named through a link
    loose_json.write_text(json.dumps(held), encoding="utf-8")
    agents.hub.loose.drop(member, root)
    assert not root.path.exists()
    assert CAL not in json.loads(loose_json.read_text(encoding="utf-8"))


def test_keep_false_on_an_ordinary_create_is_no_keep_and_no_refusal(agents):
    out = made(agents, "bea-claude", doc="rectoversos/acme/blog/2026-11-16-new.md", text=TEXT, keep=False)
    assert agents.hub.file(out["doc"]).is_file()


def test_keep_true_on_an_ordinary_create_is_still_refused(agents):
    bad, why = call(agents, "bea-claude", "create", doc="rectoversos/acme/blog/2026-11-16-new.md", text=TEXT, keep=True)
    assert bad and "keep" in why, why


def test_a_keep_that_fails_after_the_sheaf_folder_was_made_on_a_fresh_root_takes_the_root_back(agents, monkeypatch):
    before = agents.hub.proxy.members[CAL].roots

    real = loose.state.write_text_private

    def full(path, *a, **k):
        if os.path.basename(path) != "keep.json":
            return real(path, *a, **k)
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(loose.state, "write_text_private", full)
    bad, why = call(agents, "cal-claude", "create", doc="notes.md", text=TEXT, keep=True)
    assert bad and "keep" in why, why
    nothing_made_for_cal(agents, before)


def test_a_page_name_with_spaces_around_it_is_the_name_without_them(agents):
    out = made(agents, "bea-claude", doc="  notes.md ", text=TEXT)
    assert out["doc"] == f"loose-bea/{loose.month()}/notes.md"


def test_a_page_name_of_spaces_is_refused_as_empty(agents):
    bad, why = call(agents, "bea-claude", "create", doc="   ", text=TEXT, folder="x")
    assert bad and "empty" in why, why


def test_a_loose_root_whose_folder_is_a_link_is_left_as_it_is_and_the_drop_raises_nothing(agents, tmp_path):
    member = agents.hub.proxy.members[CAL]
    root, fresh = agents.hub.loose.root_for(member)
    assert fresh
    folder = root.path
    moved = tmp_path / "real-folder"
    folder.rename(moved)
    folder.symlink_to(moved)                        # the folder loose.json holds is a link to the root's own path
    agents.hub.loose.drop(member, root)
    assert agents.hub.roots.get(root.name) is not None
    assert str(folder) in json.loads((state(agents) / "loose.json").read_text(encoding="utf-8")).values()


def test_a_refused_create_whose_drop_fails_still_raises_its_own_refusal(agents, monkeypatch):
    def refuse(*a, **k):
        raise loose.Refused("no marks today")

    def fail(*a, **k):
        raise OSError("disk says no")
    monkeypatch.setattr(loose, "keep", refuse)
    monkeypatch.setattr(agents.hub.loose, "drop", fail)
    bad, why = call(agents, "cal-claude", "create", doc="notes.md", text=TEXT, keep=True)
    assert bad and "no marks today" in why and "disk says no" not in why, why


def test_a_drop_lets_go_of_the_moves_lock_before_it_waits_for_a_document_of_the_root(agents):
    """Ticket 182 line 54: `drop` forgets the root it took back, and the forget waits for each document's lock, which a
    render holds for up to 120 s. That wait comes after the moves' lock is let go, as in `forget_root` (SPEC 8.2)."""
    import threading
    import time

    from sheafmd.hub import moves
    member = agents.hub.proxy.members[CAL]
    root, fresh = agents.hub.loose.root_for(member)
    assert fresh
    page = root.path / "a.md"
    page.write_text("# A\n", encoding="utf-8")
    e = agents.hub.entry(f"{root.name}/a.md")
    page.unlink()                       # the root is empty again; the hub still holds the page's entry
    held, release = threading.Event(), threading.Event()

    def render():
        with e.live.exclusive():
            held.set()
            release.wait(15)
    renderer = threading.Thread(target=render, daemon=True)
    renderer.start()
    assert held.wait(5)
    dropping = threading.Thread(target=lambda: agents.hub.loose.drop(member, root), daemon=True)
    dropping.start()
    try:
        end = time.monotonic() + 5
        while time.monotonic() < end and f"{root.name}/a.md" in agents.hub.entries:
            time.sleep(0.01)
        assert f"{root.name}/a.md" not in agents.hub.entries
        got = moves._LOCK.acquire(timeout=3)
        if got:
            moves._LOCK.release()
        assert got, "the moves' lock is held while the drop waits for a render"
        assert dropping.is_alive()      # the drop itself still waits for the document
    finally:
        release.set()
        renderer.join(5)
        dropping.join(5)
    assert not dropping.is_alive()
    assert agents.hub.roots.get(root.name) is None
