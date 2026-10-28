"""Visibility (SPEC 9.11): a sheaf that draws on a private source is its owner's alone until the owner ticks
Share. Through the handler in proxy mode, with two members of one root: Thierry, who owns the sheaves
below, and Hans, who is a member of the project but owns none of them."""
import os
import pwd

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
    docs = lambda m: [d["doc"] for r in team.get("/_/index.json", member=m).json()["roots"] for d in r["docs"]]
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
