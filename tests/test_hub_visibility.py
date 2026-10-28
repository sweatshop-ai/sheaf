"""Visibility (SPEC 9.11): a sheaf that draws on a private source is its owner's alone until the owner ticks
Share. Through the handler in proxy mode, with two members of one root: Thierry, who owns the sheaves
below, and Hans, who is a member of the project but owns none of them."""
import os
import pwd
import time

import pytest
from helpers import FRONT, Front, call, hub_rows

from sheafmd.hub import proxy, the_list
from sheafmd.hub.state import Tokens
from sheafmd.hub.visibility import front_matter
from sheafmd.source import md_hash

THIERRY = "503b2f77-83de-452c-817a-a357faf85929"
HANS = "2b9d7e1c-4a51-4c0e-9d1f-6f0c3a7e8b42"

PRIVATE = """---
client: thinkingtoo
project: tiroir
issue: thinkingtoo/tt-tiroir#9
assistant: James
owner: thierry
sources: [library:doc-123]
---
# What the contract says

- [ ] Share

A quote from the contract.
"""


@pytest.fixture
def team(hub, browser, work, plan):
    hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                             "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                             "members": {THIERRY: {"name": "Thierry", "short": "thierry", "github": "tiroir",
                                                   "roots": [str(work)]},
                                         HANS: {"name": "Hans", "short": "hans", "github": "hanshermans",
                                                "roots": [str(work)]}}}, "the test")
    return Front(hub, browser.handler)


def put(team, work, rel, text):
    f = work / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    team.hub.roots.for_document(f)
    return f"work/{rel}"


DOC = "thinkingtoo/tiroir/2026-10-28-contract.md"


def test_a_sheaf_from_a_private_source_answers_404_to_hans_and_200_to_its_owner(team, work):
    put(team, work, DOC, PRIVATE)
    assert team.get(f"/work/{DOC}", member=THIERRY).status == 200
    got = team.get(f"/work/{DOC}", member=HANS)
    missing = team.get("/work/thinkingtoo/tiroir/nothing.md", member=HANS)
    assert got.status == missing.status == 404 and got.body == missing.body


def tick(team, work, rel, word, member, **extra):
    """The page's save that ticks the first action `word` of the sheaf, as `member`."""
    text = (work / rel).read_text(encoding="utf-8")
    n = [a[0] for a in the_list.read_sheaf(rel, text).actions].index(word)
    edit = the_list.tick_edit(text, n, word)
    return team.post("/_/save", {"doc": f"work/{rel}", "hash": md_hash(text), "edits": [edit], **extra},
                     member=member)


def test_a_sheaf_without_private_sources_is_visible_to_the_project_at_once(team, work):
    put(team, work, DOC, PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:thinkingtoo/tt-tiroir#9]"))
    assert team.get(f"/work/{DOC}", member=HANS).status == 200


def test_a_written_visibility_project_does_not_open_a_sheaf_with_a_private_source(team, work):
    put(team, work, DOC, PRIVATE.replace("owner: thierry", "owner: thierry\nvisibility: project"))
    assert team.get(f"/work/{DOC}", member=HANS).status == 404


def test_a_source_list_written_as_lines_is_read_too(team, work):
    put(team, work, DOC, PRIVATE.replace("sources: [library:doc-123]", "sources:\n  - web:https://x.example\n  - mail:abc"))
    assert team.get(f"/work/{DOC}", member=HANS).status == 404


def test_hans_does_not_see_an_owner_only_sheaf_in_the_index(team, work):
    put(team, work, DOC, PRIVATE)

    def docs(m):
        return [d["doc"] for r in team.get("/_/index.json", member=m).json()["roots"] for d in r["docs"]]
    assert f"work/{DOC}" in docs(THIERRY)
    assert f"work/{DOC}" not in docs(HANS)


def test_the_owners_share_opens_the_sheaf_to_the_project(team, work):
    put(team, work, DOC, PRIVATE)
    assert tick(team, work, DOC, "Share", THIERRY).status == 200
    fm = front_matter((work / DOC).read_text(encoding="utf-8"))
    assert fm["visibility"] == "project" and fm["shared"].startswith("thierry ")
    assert "- [x] Share" in (work / DOC).read_text(encoding="utf-8")
    assert team.get(f"/work/{DOC}", member=HANS).status == 200


def test_share_ticked_by_a_member_who_is_not_the_owner_is_refused_and_writes_nothing(team, work):
    shared = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")   # Hans can open it
    put(team, work, DOC, shared.replace("- [ ] Share", "- [ ] Share\n- [ ] Done"))
    before = (work / DOC).read_text(encoding="utf-8")
    got = tick(team, work, DOC, "Share", HANS)
    assert got.status == 409 and "owner" in got.json()["error"]
    assert (work / DOC).read_text(encoding="utf-8") == before


def test_the_share_mark_names_the_signed_in_owner_whatever_the_request_says(team, work):
    put(team, work, DOC, PRIVATE)
    tick(team, work, DOC, "Share", THIERRY, by="hans", author="hans", who="hans", short="hans")
    assert front_matter((work / DOC).read_text(encoding="utf-8"))["shared"].startswith("thierry ")


def test_the_lists_tick_of_share_by_a_member_who_is_not_the_owner_is_refused(team, work):
    put(team, work, DOC, PRIVATE.replace("sources: [library:doc-123]", "sources: []"))
    got = team.post("/_/tick", {"doc": f"work/{DOC}", "action": 0, "word": "Share"}, member=HANS)
    assert got.status == 409
    assert "- [ ] Share" in (work / DOC).read_text(encoding="utf-8")


DIGEST = PRIVATE.replace("assistant: James", "assistant: Mistral").replace(
    "sources: [library:doc-123]", "visibility: project\nsources: [library]")


def test_a_door_create_from_mistral_with_a_library_source_lands_owner_only(team, browser, work):
    (work / "thinkingtoo/tiroir").mkdir(parents=True)
    is_error, got = call(browser, "create", token=Tokens().add("mistral", write=True), doc=f"work/{DOC}", text=DIGEST)
    assert not is_error, got
    on_disk = (work / DOC).read_text(encoding="utf-8")
    assert front_matter(on_disk)["visibility"] == "owner"
    assert got["hash"] == md_hash(on_disk)
    assert team.get(f"/work/{DOC}", member=HANS).status == 404
    assert team.get(f"/work/{DOC}", member=THIERRY).status == 200


def test_a_door_write_cannot_share_a_sheaf_itself(team, browser, work):
    put(team, work, DOC, PRIVATE)
    token = Tokens().add("james", write=True)
    is_error, got = call(browser, "read", token=token, doc=f"work/{DOC}")
    forged = got["text"].replace("owner: thierry", "owner: thierry\nvisibility: project\nshared: thierry 2026-10-28")
    is_error, got = call(browser, "update", token=token, doc=f"work/{DOC}", text=forged, expected_hash=got["hash"])
    assert not is_error, got
    fm = front_matter((work / DOC).read_text(encoding="utf-8"))
    assert fm["visibility"] == "owner" and "shared" not in fm
    assert team.get(f"/work/{DOC}", member=HANS).status == 404


def test_a_door_update_keeps_the_owners_share(team, browser, work):
    put(team, work, DOC, PRIVATE)
    tick(team, work, DOC, "Share", THIERRY)
    token = Tokens().add("james", write=True)
    is_error, got = call(browser, "read", token=token, doc=f"work/{DOC}")
    is_error, got = call(browser, "update", token=token, doc=f"work/{DOC}", text=got["text"] + "\nMore.\n",
                         expected_hash=got["hash"])
    assert not is_error, got
    assert team.get(f"/work/{DOC}", member=HANS).status == 200


def test_a_door_update_that_adds_a_private_source_closes_a_shared_sheaf(team, browser, work):
    put(team, work, DOC, PRIVATE)
    tick(team, work, DOC, "Share", THIERRY)
    token = Tokens().add("james", write=True)
    is_error, got = call(browser, "read", token=token, doc=f"work/{DOC}")
    more = got["text"].replace("sources: [library:doc-123]", "sources: [library:doc-123, mail:t-77]")
    is_error, got = call(browser, "update", token=token, doc=f"work/{DOC}", text=more, expected_hash=got["hash"])
    assert not is_error, got
    assert team.get(f"/work/{DOC}", member=HANS).status == 404


STOPPABLE = PRIVATE.replace("sources: [library:doc-123]", "sources: []").replace("- [ ] Share", "- [ ] Stop James")


@pytest.fixture
def stop_dir(tmp_path, team, monkeypatch):
    d = tmp_path / "stop"
    d.mkdir()
    cfg = the_list.parse({"root": str(tmp_path / "list"), "repo": "thinkingtoo/tt-tiroir", "project": 1,
                          "token_file": str(tmp_path / "token"), "stop_dir": str(d)}, "the test")
    team.hub.the_list = the_list.TheList(team.hub, cfg)
    return d


def test_stop_james_ticked_by_hans_drops_the_project_for_james_and_writes_a_row(team, work, stop_dir):
    put(team, work, DOC, STOPPABLE)
    assert tick(team, work, DOC, "Stop James", HANS).status == 200
    files = [f for f in stop_dir.iterdir()]
    assert len(files) == 1 and not files[0].name.startswith(".")
    assert files[0].read_text(encoding="utf-8") == "thinkingtoo/tiroir\n"
    row, = hub_rows("stop-james")
    assert (row["project"], row["assistant"], row["by"], row["drop"]) == ("thinkingtoo/tiroir", "James", "hans", "written")


def test_stop_james_on_a_sheaf_of_another_assistant_drops_nothing(team, work, stop_dir):
    put(team, work, DOC, STOPPABLE.replace("assistant: James", "assistant: Mistral"))
    assert tick(team, work, DOC, "Stop James", HANS).status == 200
    assert list(stop_dir.iterdir()) == []
    assert hub_rows("stop-james")[0]["drop"] == "not a sheaf of James"


def test_stop_james_without_a_stop_dir_still_writes_the_row(team, work):
    put(team, work, DOC, STOPPABLE)
    assert tick(team, work, DOC, "Stop James", HANS).status == 200
    assert hub_rows("stop-james")[0]["drop"] == "no stop_dir in [list]"


def test_a_stop_dir_inside_the_lists_root_stops_the_start(tmp_path):
    with pytest.raises(the_list.ListError, match="stop_dir"):
        the_list.parse({"root": str(tmp_path), "repo": "a/b", "project": 1, "token_file": "/t",
                        "stop_dir": str(tmp_path / "stop")}, "the test")


@pytest.mark.parametrize("line, key, value", [
    ("visibility: owner   # only Nell", "visibility", "owner"),
    ("issue: a/b#7  # x", "issue", "a/b#7"),
    ("issue: a/b#7", "issue", "a/b#7"),
    ('owner: "thierry"  # quoted', "owner", "thierry"),
    ('title: "a # b"', "title", "a # b"),
    ("sources: [library:1, issue:a/b#2]  # two", "sources", ("library:1", "issue:a/b#2")),
    ("visibility:   # none yet", "visibility", ""),
])
def test_a_comment_after_a_value_is_not_part_of_it(line, key, value):
    assert front_matter(f"---\n{line}\n---\n# T\n")[key] == value


def test_an_owner_only_sheaf_with_a_comment_on_its_visibility_line_answers_404_to_hans(team, work):
    put(team, work, DOC, PRIVATE.replace("sources: [library:doc-123]", "visibility: owner   # Thierry's alone"))
    assert team.get(f"/work/{DOC}", member=HANS).status == 404
    assert team.get(f"/work/{DOC}", member=THIERRY).status == 200


def test_the_stop_file_is_readable_by_the_folders_group_whatever_the_hubs_umask(team, work, stop_dir):
    put(team, work, DOC, STOPPABLE)
    old = os.umask(0o077)
    try:
        assert tick(team, work, DOC, "Stop James", HANS).status == 200
    finally:
        os.umask(old)
    f, = stop_dir.iterdir()
    assert f.stat().st_mode & 0o777 == 0o640


def door_update(browser, work, rel, change):
    """An assistant's door update of `rel`: the text it reads, changed by `change`."""
    token = Tokens().add("james", write=True)
    is_error, got = call(browser, "read", token=token, doc=f"work/{rel}")
    assert not is_error, got
    return call(browser, "update", token=token, doc=f"work/{rel}", text=change(got["text"]), expected_hash=got["hash"])


def test_a_door_update_that_drops_the_front_matter_leaves_an_owner_only_sheaf_its_owners(team, browser, work):
    put(team, work, DOC, PRIVATE)
    is_error, got = door_update(browser, work, DOC, lambda t: t.split("---\n", 2)[2])
    assert not is_error, got
    assert team.get(f"/work/{DOC}", member=HANS).status == 404
    assert team.get(f"/work/{DOC}", member=THIERRY).status == 200


def test_a_door_update_cannot_hand_an_owner_only_sheaf_to_another_member(team, browser, work):
    put(team, work, DOC, PRIVATE)
    is_error, got = door_update(browser, work, DOC, lambda t: t.replace("owner: thierry", "owner: hans"))
    assert not is_error, got
    assert team.get(f"/work/{DOC}", member=HANS).status == 404
    assert team.get(f"/work/{DOC}", member=THIERRY).status == 200


def test_a_page_save_cannot_change_the_front_matter_whoever_sends_it(team, work):
    open_ = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")
    put(team, work, DOC, open_)
    text = (work / DOC).read_text(encoding="utf-8")
    got = team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text),
                                "edits": [{"i": 0, "html": "<p>visibility: owner<br>owner: hans</p>"}]}, member=HANS)
    assert got.status == 200 and got.json()["skipped"]
    assert (work / DOC).read_text(encoding="utf-8") == text
    assert team.get(f"/work/{DOC}", member=THIERRY).status == 200


def test_an_open_stream_of_hans_hears_nothing_once_a_door_write_closes_the_sheaf(team, browser, work):
    open_ = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")
    put(team, work, DOC, open_)
    sub = team.get(f"/_/live?doc=work/{DOC}", member=HANS).stream
    sub.drain()
    is_error, got = door_update(browser, work, DOC, lambda t: t.replace("sources: [issue:x/y#1]", "sources: [mail:t-1]")
                                + "\nA line from the mail.\n")
    assert not is_error, got
    team.hub.entry(f"work/{DOC}").live.refresh(force=True)
    assert sub.drain() == []


@pytest.mark.parametrize("where, why", [("missing", "is not a folder"), ("top", "no <client>/<project> folder")])
def test_stop_james_that_cannot_drop_says_why_in_its_row(team, work, stop_dir, where, why):
    rel = DOC
    if where == "missing":
        stop_dir.rmdir()
    else:
        rel = "contract.md"
    put(team, work, rel, STOPPABLE)
    assert tick(team, work, rel, "Stop James", HANS).status == 200
    assert why in hub_rows("stop-james")[0]["drop"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a folder of mode 0500")
def test_stop_james_whose_drop_fails_says_failed_and_leaves_no_dot_file(team, work, stop_dir):
    put(team, work, DOC, STOPPABLE)
    stop_dir.chmod(0o500)
    try:
        assert tick(team, work, DOC, "Stop James", HANS).status == 200
    finally:
        stop_dir.chmod(0o700)
    assert hub_rows("stop-james")[0]["drop"].startswith("failed: ")
    assert list(stop_dir.iterdir()) == []


def test_a_source_list_written_without_indent_is_read_too(team, work):
    put(team, work, DOC, PRIVATE.replace("sources: [library:doc-123]", "sources:\n- library:x"))
    assert team.get(f"/work/{DOC}", member=HANS).status == 404
    assert team.get(f"/work/{DOC}", member=THIERRY).status == 200


def test_a_sheaf_whose_front_matter_follows_a_byte_order_mark_is_read_too(team, work):
    put(team, work, DOC, "﻿" + PRIVATE)
    assert team.get(f"/work/{DOC}", member=HANS).status == 404
    assert team.get(f"/work/{DOC}", member=THIERRY).status == 200


@pytest.mark.parametrize("change", [
    lambda t: t.replace("sources: [library:doc-123]", '"sources": [library:doc-123]'),
    lambda t: t.replace("sources: [library:doc-123]", "sources: [library:doc-123]\nsources: []"),
    lambda t: t.replace("sources: [library:doc-123]", "sources :\n  - library:doc-123"),
    lambda t: t.replace("sources: [library:doc-123]", "visibility: >-\n  owner"),
], ids=["quoted key", "key twice", "space before colon", "folded value"])
def test_a_front_matter_line_the_hub_cannot_read_keeps_the_sheaf_its_owners(team, work, change):
    put(team, work, DOC, change(PRIVATE))
    assert team.get(f"/work/{DOC}", member=HANS).status == 404
    assert team.get(f"/work/{DOC}", member=THIERRY).status == 200


def test_the_owners_share_written_with_a_plus_bullet_opens_the_sheaf_too(team, work):
    put(team, work, DOC, PRIVATE.replace("- [ ] Share", "+ [ ] Share"))
    assert tick(team, work, DOC, "Share", THIERRY).status == 200
    assert team.get(f"/work/{DOC}", member=HANS).status == 200


def test_share_with_a_plus_bullet_ticked_by_a_member_who_is_not_the_owner_is_refused(team, work):
    shared = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")
    put(team, work, DOC, shared.replace("- [ ] Share", "+ [ ] Share"))
    before = (work / DOC).read_text(encoding="utf-8")
    assert tick(team, work, DOC, "Share", HANS).status == 409
    assert (work / DOC).read_text(encoding="utf-8") == before


def test_the_owners_share_nested_in_a_list_opens_the_sheaf_too(team, work):
    put(team, work, DOC, PRIVATE.replace("- [ ] Share", "- Before you share\n  - [ ] Share"))
    assert tick(team, work, DOC, "Share", THIERRY).status == 200
    assert team.get(f"/work/{DOC}", member=HANS).status == 200


def test_a_door_update_cannot_give_an_owner_to_an_owner_only_sheaf_that_had_none(team, browser, work):
    put(team, work, DOC, PRIVATE.replace("owner: thierry\n", ""))
    is_error, got = door_update(browser, work, DOC, lambda t: t.replace("assistant: James", "assistant: James\nowner: hans"))
    assert not is_error, got
    assert team.get(f"/work/{DOC}", member=HANS).status == 404


def test_a_save_of_hans_that_lands_after_the_sheaf_closed_writes_nothing(team, work, monkeypatch):
    open_ = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]").replace("- [ ] Share", "- [ ] Done")
    put(team, work, DOC, open_)
    closed = open_.replace("sources: [issue:x/y#1]", "sources: [mail:t-77]")
    assert team.get(f"/work/{DOC}", member=HANS).status == 200      # the page Hans saves from
    gate = team.hub.visible

    def a_door_write_closes_it_after_the_gate(member, address):
        ok = gate(member, address)
        if member.id == HANS:
            (work / DOC).write_text(closed, encoding="utf-8")
        return ok
    monkeypatch.setattr(team.hub, "visible", a_door_write_closes_it_after_the_gate)
    got = tick(team, work, DOC, "Done", HANS)
    assert got.status == 404, got.body
    assert (work / DOC).read_text(encoding="utf-8") == closed


@pytest.mark.parametrize("how", ["replaced", "in place"])
def test_a_sheaf_closed_with_the_same_size_and_time_is_closed_at_once(team, work, how):
    open_ = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")
    closed = PRIVATE.replace("sources: [library:doc-123]", "sources: [library:ab1]")
    assert len(open_) == len(closed)
    put(team, work, DOC, open_)
    f = work / DOC
    assert team.get(f"/work/{DOC}", member=HANS).status == 200
    st = f.stat()
    if how == "replaced":
        tmp = f.with_name("next.tmp")
        tmp.write_text(closed, encoding="utf-8")
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(tmp, f)
    else:
        f.write_text(closed, encoding="utf-8")
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert team.get(f"/work/{DOC}", member=HANS).status == 404


def test_two_stop_james_in_one_second_leave_one_drop_and_two_rows(team, work, stop_dir, monkeypatch):
    put(team, work, DOC, STOPPABLE.replace("- [ ] Stop James", "- [ ] Stop James\n- [ ] Stop James"))
    second = time.gmtime()
    monkeypatch.setattr(time, "gmtime", lambda *_: second)
    assert tick(team, work, DOC, "Stop James", HANS).status == 200
    assert tick(team, work, DOC, "Stop James", THIERRY).status == 200
    f, = stop_dir.iterdir()
    assert f.read_text(encoding="utf-8") == "thinkingtoo/tiroir\n"
    assert [r["drop"] for r in hub_rows("stop-james")] == ["written", "written"]


# ── Review round 2 (PR 10), and Tariq's digest round on tt-tiroir PR 32 ─────────────────────────────

@pytest.mark.parametrize("how", ["not UTF-8", "unreadable"])
def test_an_owner_only_sheaf_its_page_cached_answers_404_to_hans_once_its_file_cannot_be_read(team, work, how):
    if how == "unreadable" and os.geteuid() == 0:
        pytest.skip("root reads a file of mode 000")
    put(team, work, DOC, PRIVATE)
    assert team.get(f"/work/{DOC}", member=THIERRY).status == 200       # the hub now holds its page
    f = work / DOC
    if how == "not UTF-8":
        f.write_bytes(f.read_bytes() + b"\nlatin1 caf\xe9\n")
    else:
        os.chmod(f, 0)
    try:
        assert team.get(f"/work/{DOC}", member=HANS).status == 404
        assert team.get(f"/_/doc?doc=work/{DOC}", member=HANS).status == 404
    finally:
        os.chmod(f, 0o644)


@pytest.mark.parametrize("change", [
    lambda t: t.replace("issue: thinkingtoo/tt-tiroir#9", "issue: thinkingtoo/tt-tiroir#99"),
    lambda t: t.replace("issue: thinkingtoo/tt-tiroir#9\n", "")], ids=["another issue", "no issue"])
def test_a_door_update_keeps_the_issue_on_disk_which_names_the_owner(team, browser, work, change):
    put(team, work, DOC, PRIVATE)
    is_error, got = door_update(browser, work, DOC, change)
    assert not is_error, got
    assert front_matter((work / DOC).read_text(encoding="utf-8"))["issue"] == "thinkingtoo/tt-tiroir#9"


def test_a_front_matter_after_a_byte_order_mark_is_no_block_a_member_can_edit(team, work):
    shared = "﻿" + PRIVATE.replace("owner: thierry", "owner: thierry\nshared: thierry 2026-10-28T09:00:00Z")
    put(team, work, DOC, shared)
    assert team.get(f"/work/{DOC}", member=HANS).status == 200
    text = (work / DOC).read_text(encoding="utf-8")
    team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text), "edits": [{"i": 0, "html": "<p>gone</p>"}]},
              member=HANS)
    fm = front_matter((work / DOC).read_text(encoding="utf-8"))
    assert fm["owner"] == "thierry" and fm["shared"] and fm["sources"] == ("library:doc-123",)


def test_a_comment_of_hans_that_lands_after_the_sheaf_closed_writes_nothing(team, work, monkeypatch):
    from sheafmd.blocks import split_md_blocks
    open_ = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")
    put(team, work, DOC, open_)
    closed = open_.replace("sources: [issue:x/y#1]", "sources: [mail:t-77]")
    assert team.get(f"/work/{DOC}", member=HANS).status == 200
    gate = team.hub.visible

    def a_door_write_closes_it_after_the_gate(member, address):
        ok = gate(member, address)
        if member.id == HANS:
            (work / DOC).write_text(closed, encoding="utf-8")
        return ok
    monkeypatch.setattr(team.hub, "visible", a_door_write_closes_it_after_the_gate)
    i = next(i for i, b in enumerate(split_md_blocks(open_)) if b.content.startswith("A quote"))
    got = team.post("/_/comment", {"doc": f"work/{DOC}", "op": "add", "hash": md_hash(open_), "block": i, "start": 0,
                                   "end": 7, "quote": "A quote", "body": "Is this right?"}, member=HANS)
    assert got.status == 404, got.body
    assert (work / DOC).read_text(encoding="utf-8") == closed


@pytest.mark.parametrize("front,body", [("\n", "\r\n"), ("\r\n", "\n")], ids=["LF over CRLF", "CRLF over LF"])
def test_share_rewrites_the_front_matter_lines_only_never_the_bodys_line_endings(front, body):
    from sheafmd.hub import visibility
    text = front.join(["---", "owner: thierry", "sources: [library:1]", "---", ""]) + \
        body.join(["line one", "```", "code", "```", ""])
    out = visibility.share(text, "thierry", "T")
    assert out.endswith(body.join(["line one", "```", "code", "```", ""]))
    assert visibility.effective(visibility.front_matter(out)) == "project"


@pytest.mark.parametrize("old,new,words", [
    ("- &#9746; Share @a\n- &#9744; Mark this read\n", "- [x] Share @a\n- [x] Mark this read\n", set()),  # a decoy
    ("- <input type=\"checkbox\" checked> Share @a\n- teh other\n", "- [x] Share @a\n- the other\n", set()),  # a typo
    ("\\- [x] Share @a\\\nteh rest\n", "- [x] Share @a\n  the rest\n", set()),            # a paragraph edited
    ("- [ ] Share\n", "- [x] Share @a\n", set()),                                      # the line changed too
    ("- [ ] Share\n- &#9746; Share\n", "- [x] Share\n- [x] Share\n", {"Share"}),       # the owner's own box
    ("- [ ] Share\n", "- [x] Share\n", {"Share"}),
    ("+ [ ] Stop James @x\n", "+ [X] Stop James @x\n", {"Stop James"})])
def test_a_tick_counts_only_when_its_own_line_goes_from_open_to_ticked(old, new, words):
    from sheafmd.hub import visibility
    head = "---\nowner: thierry\n---\n# A\n\n"
    assert visibility.newly_ticked(head + old, head + new) == words


def test_the_owners_tick_of_a_decoy_box_beside_a_ballot_share_does_not_share_the_sheaf(team, work):
    from sheafmd import _pandoc
    from sheafmd.blocks import split_md_blocks
    put(team, work, DOC, PRIVATE.replace("A quote from the contract.",
                                         "- &#9746; Share @a\n- &#9744; Mark this digest as read"))
    text = (work / DOC).read_text(encoding="utf-8")
    i = next(k for k, b in enumerate(split_md_blocks(text)) if "Mark this" in b.content)
    html = _pandoc.run(["-f", "gfm", "-t", "html5", "--no-highlight"], split_md_blocks(text)[i].content).stdout
    k = html.rfind('<input type="checkbox"', 0, html.index("Mark this"))
    html = html[:k] + '<input type="checkbox" checked=""' + html[k + len('<input type="checkbox"'):]
    got = team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text), "edits": [{"i": i, "html": html}]},
                    member=THIERRY)
    assert got.status == 200, got.body
    assert "[x] Mark this digest as read" in (work / DOC).read_text(encoding="utf-8")   # the save went through
    assert team.get(f"/work/{DOC}", member=HANS).status == 404
