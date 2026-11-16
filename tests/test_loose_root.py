"""A member's loose root: a door `create` with no root writes into `loose-<short>`, made on the member's first
`create`, in the folder the agent named, else the month. Read at the handler seam in proxy mode, in memory."""
import dataclasses
import os
import time

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
    import json
    return json.loads(text)


def month():
    return time.strftime("%Y-%m")


def test_the_first_create_makes_the_loose_root_and_puts_the_page_in_the_month(agents):
    out = made(agents, "bea-claude", doc="notes.md", text=TEXT)
    assert out["doc"] == f"loose-bea/{month()}/notes.md"
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
    bea = agents.hub.proxy.members[BEA]
    agents.hub.proxy.members[CAL] = dataclasses.replace(agents.hub.proxy.members[CAL], name="Bea", short="")
    a = made(agents, "bea-claude", doc="notes.md", text=TEXT)
    c = made(agents, "cal-claude", doc="notes.md", text=TEXT)
    assert a["doc"].split("/")[0] != c["doc"].split("/")[0]
    assert agents.hub.owns(bea, agents.hub.roots.get(a["doc"].split("/")[0]))
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
    (root.path / month()).rename(root.path / "moved-away")
    os.symlink(outside, root.path / month())
    bad, why = call(agents, "bea-claude", "create", doc="notes.md", text=TEXT)
    assert bad, why
    assert not list(outside.iterdir())
