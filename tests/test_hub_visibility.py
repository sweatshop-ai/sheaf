"""Visibility (SPEC 9.11): a rectoverso that draws on a private source is its owner's alone until the owner ticks
Share. Through the handler in proxy mode, with two members of one root: Alice, who owns the rectoversos
below, and Bob, who is a member of the project but owns none of them."""
import os
import pwd
import time

import pytest
from helpers import FRONT, Front, call, hub_rows

from sheafmd.blocks import split_md_blocks
from sheafmd.edit import ticked_html
from sheafmd.hub import proxy, the_list
from sheafmd.hub.index import SWEEP_SECONDS
from sheafmd.hub.state import Tokens
from sheafmd.hub.visibility import front_matter
from sheafmd.mcp import MAX_TEXT
from sheafmd.source import md_hash

ALICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BOB = "2b9d7e1c-4a51-4c0e-9d1f-6f0c3a7e8b42"

PRIVATE = """---
client: acme
project: tiroir
issue: acme/agency-tiroir#9
assistant: James
owner: alice
sources: [library:doc-123]
---
# What the contract says

- [ ] Share

A quote from the contract.
"""


def members(work, bob_also=None, **tokens):
    """The `[proxy]` table of the two members, each with the door tokens `tokens` binds to their `short`.
    Both have the root `work`; Bob has `bob_also` too, when given."""
    team = {ALICE: {"name": "Alice", "short": "alice", "github": "tiroir", "roots": [str(work)]},
            BOB: {"name": "Bob", "short": "bob", "github": "bobsmith",
                   "roots": [str(work)] + ([str(bob_also)] if bob_also else [])}}
    for m in team.values():
        if m["short"] in tokens:
            m["tokens"] = tokens[m["short"]]
    return proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                        "proxy_user": pwd.getpwuid(os.getuid()).pw_name, "members": team}, "the test")


@pytest.fixture
def team(hub, browser, work, plan):
    hub.proxy = members(work)
    return Front(hub, browser.handler)


def put(team, work, rel, text):
    f = work / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    team.hub.roots.for_document(f)
    return f"work/{rel}"


DOC = "acme/tiroir/2026-10-28-contract.md"


def test_a_sheaf_from_a_private_source_answers_404_to_bob_and_200_to_its_owner(team, work):
    put(team, work, DOC, PRIVATE)
    assert team.get(f"/work/{DOC}", member=ALICE).status == 200
    got = team.get(f"/work/{DOC}", member=BOB)
    missing = team.get("/work/acme/tiroir/nothing.md", member=BOB)
    assert got.status == missing.status == 404 and got.body == missing.body


def tick(team, work, rel, word, member, **extra):
    """The page's save that ticks the first action `word` of the rectoverso, as `member`."""
    text = (work / rel).read_text(encoding="utf-8")
    n = [a[0] for a in the_list.read_rectoverso(rel, text).actions].index(word)
    edit = the_list.tick_edit(text, n, word)
    return team.post("/_/save", {"doc": f"work/{rel}", "hash": md_hash(text), "edits": [edit], **extra},
                     member=member)


def test_a_sheaf_without_private_sources_is_visible_to_the_project_at_once(team, work):
    put(team, work, DOC, PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:acme/agency-tiroir#9]"))
    assert team.get(f"/work/{DOC}", member=BOB).status == 200


def test_a_written_visibility_project_does_not_open_a_sheaf_with_a_private_source(team, work):
    put(team, work, DOC, PRIVATE.replace("owner: alice", "owner: alice\nvisibility: project"))
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def test_a_source_list_written_as_lines_is_read_too(team, work):
    put(team, work, DOC, PRIVATE.replace("sources: [library:doc-123]", "sources:\n  - web:https://x.example\n  - mail:abc"))
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def test_bob_does_not_see_an_owner_only_sheaf_in_the_index(team, work):
    put(team, work, DOC, PRIVATE)

    def docs(m):
        return [d["doc"] for r in team.get("/_/index.json", member=m).json()["roots"] for d in r["docs"]]
    assert f"work/{DOC}" in docs(ALICE)
    assert f"work/{DOC}" not in docs(BOB)


def test_the_owners_share_opens_the_sheaf_to_the_project(team, work):
    put(team, work, DOC, PRIVATE)
    assert tick(team, work, DOC, "Share", ALICE).status == 200
    fm = front_matter((work / DOC).read_text(encoding="utf-8"))
    assert fm["visibility"] == "project" and fm["shared"].startswith("alice ")
    assert "- [x] Share" in (work / DOC).read_text(encoding="utf-8")
    assert team.get(f"/work/{DOC}", member=BOB).status == 200


def test_share_ticked_by_a_member_who_is_not_the_owner_is_refused_and_writes_nothing(team, work):
    shared = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")   # Bob can open it
    put(team, work, DOC, shared.replace("- [ ] Share", "- [ ] Share\n- [ ] Done"))
    before = (work / DOC).read_text(encoding="utf-8")
    got = tick(team, work, DOC, "Share", BOB)
    assert got.status == 409 and "owner" in got.json()["error"]
    assert (work / DOC).read_text(encoding="utf-8") == before


def test_the_share_mark_names_the_signed_in_owner_whatever_the_request_says(team, work):
    put(team, work, DOC, PRIVATE)
    tick(team, work, DOC, "Share", ALICE, by="bob", author="bob", who="bob", short="bob")
    assert front_matter((work / DOC).read_text(encoding="utf-8"))["shared"].startswith("alice ")


def test_the_lists_tick_of_share_by_a_member_who_is_not_the_owner_is_refused(team, work):
    put(team, work, DOC, PRIVATE.replace("sources: [library:doc-123]", "sources: []"))
    got = team.post("/_/tick", {"doc": f"work/{DOC}", "action": 0, "word": "Share",
                                 "hash": md_hash((work / DOC).read_text(encoding="utf-8"))}, member=BOB)
    assert got.status == 409
    assert "- [ ] Share" in (work / DOC).read_text(encoding="utf-8")


DIGEST = PRIVATE.replace("assistant: James", "assistant: Mistral").replace(
    "sources: [library:doc-123]", "visibility: project\nsources: [library]")


def test_a_door_create_from_mistral_with_a_library_source_lands_owner_only(team, browser, work):
    (work / "acme/tiroir").mkdir(parents=True)
    is_error, got = call(browser, "create", token=Tokens().add("mistral", write=True), doc=f"work/{DOC}", text=DIGEST)
    assert not is_error, got
    on_disk = (work / DOC).read_text(encoding="utf-8")
    assert front_matter(on_disk)["visibility"] == "owner"
    assert got["hash"] == md_hash(on_disk)
    assert team.get(f"/work/{DOC}", member=BOB).status == 404
    assert team.get(f"/work/{DOC}", member=ALICE).status == 200


MAIL = "list/a/inbox/x.md"
MAIL_TEXT = "---\nsources: [mail]\n---\n# A mail\n\nWhat it says.\n"


def test_a_door_create_by_a_bound_token_gives_its_member_an_owner_only_sheaf_with_no_owner(team, browser, work):
    """#30: the mail module's token, bound to Alice, writes a rectoverso from a private source with no `owner`."""
    team.hub.proxy = members(work, alice=["mail"])
    (work / "list/a/inbox").mkdir(parents=True)
    token = Tokens().add("mail", write=True)
    is_error, got = call(browser, "create", token=token, doc=f"work/{MAIL}", text=MAIL_TEXT)
    assert not is_error, got
    on_disk = (work / MAIL).read_text(encoding="utf-8")
    assert front_matter(on_disk)["owner"] == "alice" and got["hash"] == md_hash(on_disk)
    is_error, got = call(browser, "read", token=token, doc=f"work/{MAIL}")
    assert not is_error and got["text"] == on_disk
    assert team.get(f"/work/{MAIL}", member=ALICE).status == 200
    assert team.get(f"/work/{MAIL}", member=BOB).status == 404


def test_a_door_create_by_an_unbound_token_of_an_owner_only_sheaf_with_no_owner_is_refused(team, browser, work):
    """#30: a token bound to nobody could not open what it made, nor could anyone else: no orphan is made."""
    (work / "list/a/inbox").mkdir(parents=True)
    is_error, got = call(browser, "create", token=Tokens().add("mail", write=True), doc=f"work/{MAIL}",
                         text=MAIL_TEXT)
    assert is_error and "owner" in got and "bind" in got, got
    assert not (work / MAIL).exists()
    assert hub_rows("door-create")[-1]["reason"] == "no owner"


def test_a_door_create_that_names_its_owner_keeps_that_owner(team, browser, work):
    team.hub.proxy = members(work, alice=["mail"])
    (work / "list/a/inbox").mkdir(parents=True)
    text = MAIL_TEXT.replace("sources:", "owner: bob\nsources:")
    for token, doc in ((Tokens().add("mail", write=True), MAIL), (Tokens().add("mistral", write=True), "list/a/y.md")):
        is_error, got = call(browser, "create", token=token, doc=f"work/{doc}", text=text)
        assert not is_error, got
        assert front_matter((work / doc).read_text(encoding="utf-8"))["owner"] == "bob"
        assert team.get(f"/work/{doc}", member=BOB).status == 200


def test_a_door_update_that_closes_a_sheaf_with_no_owner_gives_it_the_tokens_member(team, browser, work):
    put(team, work, MAIL, "---\nsources: [issue:x/y#1]\n---\n# A mail\n")
    is_error, got = door_update(team, browser, work, MAIL, lambda t: t.replace("issue:x/y#1", "mail:t-1"))
    assert not is_error, got
    assert front_matter((work / MAIL).read_text(encoding="utf-8"))["owner"] == "alice"
    assert team.get(f"/work/{MAIL}", member=ALICE).status == 200
    assert team.get(f"/work/{MAIL}", member=BOB).status == 404


def test_a_door_update_by_an_unbound_token_that_would_close_a_sheaf_with_no_owner_is_refused(team, browser, work):
    put(team, work, MAIL, "---\nsources: [issue:x/y#1]\n---\n# A mail\n")
    token = Tokens().add("mistral", write=True)
    before = (work / MAIL).read_text(encoding="utf-8")
    is_error, got = call(browser, "update", token=token, doc=f"work/{MAIL}", expected_hash=md_hash(before),
                         text=before.replace("issue:x/y#1", "mail:t-1"))
    assert is_error and "owner" in got, got
    assert (work / MAIL).read_text(encoding="utf-8") == before
    assert hub_rows("door-update")[-1]["reason"] == "no owner"


def test_a_door_create_by_a_bound_token_of_a_sheaf_its_issues_assignee_owns_names_the_assignee(team, browser, work,
                                                                                            monkeypatch):
    """The assignee stays the owner: the token's member as `owner` would have the rectoverso once the list stops
    knowing the issue, and no `owner` would leave it to nobody (#33)."""
    team.hub.proxy = members(work, alice=["mail"])
    monkeypatch.setattr(team.hub, "assignees", lambda address, fm: ["bobsmith"])
    (work / "list/a/inbox").mkdir(parents=True)
    is_error, got = call(browser, "create", token=Tokens().add("mail", write=True), doc=f"work/{MAIL}",
                         text=MAIL_TEXT.replace("sources:", "issue: x/y#1\nsources:"))
    assert not is_error, got
    assert front_matter((work / MAIL).read_text(encoding="utf-8"))["owner"] == "bob"
    assert team.get(f"/work/{MAIL}", member=BOB).status == 200


def test_a_door_write_cannot_share_a_sheaf_itself(team, browser, work):
    put(team, work, DOC, PRIVATE)
    is_error, got = door_update(team, browser, work, DOC, lambda t: t.replace(
        "owner: alice", "owner: alice\nvisibility: project\nshared: alice 2026-10-28"))
    assert not is_error, got
    fm = front_matter((work / DOC).read_text(encoding="utf-8"))
    assert fm["visibility"] == "owner" and "shared" not in fm
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def test_a_door_update_keeps_the_owners_share(team, browser, work):
    put(team, work, DOC, PRIVATE)
    tick(team, work, DOC, "Share", ALICE)
    token = Tokens().add("james", write=True)
    is_error, got = call(browser, "read", token=token, doc=f"work/{DOC}")
    is_error, got = call(browser, "update", token=token, doc=f"work/{DOC}", text=got["text"] + "\nMore.\n",
                         expected_hash=got["hash"])
    assert not is_error, got
    assert team.get(f"/work/{DOC}", member=BOB).status == 200


def test_a_door_update_that_adds_a_private_source_closes_a_shared_sheaf(team, browser, work):
    put(team, work, DOC, PRIVATE)
    tick(team, work, DOC, "Share", ALICE)
    token = Tokens().add("james", write=True)
    is_error, got = call(browser, "read", token=token, doc=f"work/{DOC}")
    more = got["text"].replace("sources: [library:doc-123]", "sources: [library:doc-123, mail:t-77]")
    is_error, got = call(browser, "update", token=token, doc=f"work/{DOC}", text=more, expected_hash=got["hash"])
    assert not is_error, got
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


STOPPABLE = PRIVATE.replace("sources: [library:doc-123]", "sources: []").replace("- [ ] Share", "- [ ] Stop James")


@pytest.fixture
def stop_dir(tmp_path, team, monkeypatch):
    d = tmp_path / "stop"
    d.mkdir()
    cfg = the_list.parse({"root": str(tmp_path / "list"), "repo": "acme/agency-tiroir", "project": 1,
                          "token_file": str(tmp_path / "token"), "stop_dir": str(d)}, "the test")
    team.hub.the_list = the_list.TheList(team.hub, cfg)
    return d


def test_stop_james_ticked_by_bob_drops_the_project_for_james_and_writes_a_row(team, work, stop_dir):
    put(team, work, DOC, STOPPABLE)
    assert tick(team, work, DOC, "Stop James", BOB).status == 200
    files = [f for f in stop_dir.iterdir()]
    assert len(files) == 1 and not files[0].name.startswith(".")
    assert files[0].read_text(encoding="utf-8") == "acme/tiroir\n"
    row, = hub_rows("stop-james")
    assert (row["project"], row["assistant"], row["by"], row["drop"]) == ("acme/tiroir", "James", "bob", "written")


def test_stop_james_on_a_sheaf_of_another_assistant_drops_nothing(team, work, stop_dir):
    put(team, work, DOC, STOPPABLE.replace("assistant: James", "assistant: Mistral"))
    assert tick(team, work, DOC, "Stop James", BOB).status == 200
    assert list(stop_dir.iterdir()) == []
    assert hub_rows("stop-james")[0]["drop"] == "not a rectoverso of James"


def test_stop_james_without_a_stop_dir_still_writes_the_row(team, work):
    put(team, work, DOC, STOPPABLE)
    assert tick(team, work, DOC, "Stop James", BOB).status == 200
    assert hub_rows("stop-james")[0]["drop"] == "no stop_dir in [list]"


def test_a_stop_dir_inside_the_lists_root_stops_the_start(tmp_path):
    with pytest.raises(the_list.ListError, match="stop_dir"):
        the_list.parse({"root": str(tmp_path), "repo": "a/b", "project": 1, "token_file": "/t",
                        "stop_dir": str(tmp_path / "stop")}, "the test")


@pytest.mark.parametrize("line, key, value", [
    ("visibility: owner   # only Nell", "visibility", "owner"),
    ("issue: a/b#7  # x", "issue", "a/b#7"),
    ("issue: a/b#7", "issue", "a/b#7"),
    ('owner: "alice"  # quoted', "owner", "alice"),
    ('title: "a # b"', "title", "a # b"),
    ("sources: [library:1, issue:a/b#2]  # two", "sources", ("library:1", "issue:a/b#2")),
    ("visibility:   # none yet", "visibility", ""),
])
def test_a_comment_after_a_value_is_not_part_of_it(line, key, value):
    assert front_matter(f"---\n{line}\n---\n# T\n")[key] == value


def test_an_owner_only_sheaf_with_a_comment_on_its_visibility_line_answers_404_to_bob(team, work):
    put(team, work, DOC, PRIVATE.replace("sources: [library:doc-123]", "visibility: owner   # Alice's alone"))
    assert team.get(f"/work/{DOC}", member=BOB).status == 404
    assert team.get(f"/work/{DOC}", member=ALICE).status == 200


def test_the_stop_file_is_readable_by_the_folders_group_whatever_the_hubs_umask(team, work, stop_dir):
    put(team, work, DOC, STOPPABLE)
    old = os.umask(0o077)
    try:
        assert tick(team, work, DOC, "Stop James", BOB).status == 200
    finally:
        os.umask(old)
    f, = stop_dir.iterdir()
    assert f.stat().st_mode & 0o777 == 0o640


def door_update(team, browser, work, rel, change):
    """James's door update of `rel` for Alice: the text it reads, changed by `change`. Its token is bound to
    Alice, who owns the rectoversos here, so it is shown them (9.11)."""
    team.hub.proxy = members(work, alice=["james"])
    token = Tokens().add("james", write=True)
    is_error, got = call(browser, "read", token=token, doc=f"work/{rel}")
    assert not is_error, got
    return call(browser, "update", token=token, doc=f"work/{rel}", text=change(got["text"]), expected_hash=got["hash"])


def test_a_door_update_that_drops_the_front_matter_leaves_an_owner_only_sheaf_its_owners(team, browser, work):
    put(team, work, DOC, PRIVATE)
    is_error, got = door_update(team, browser, work, DOC, lambda t: t.split("---\n", 2)[2])
    assert not is_error, got
    assert team.get(f"/work/{DOC}", member=BOB).status == 404
    assert team.get(f"/work/{DOC}", member=ALICE).status == 200


def test_a_door_update_cannot_hand_an_owner_only_sheaf_to_another_member(team, browser, work):
    put(team, work, DOC, PRIVATE)
    is_error, got = door_update(team, browser, work, DOC, lambda t: t.replace("owner: alice", "owner: bob"))
    assert not is_error, got
    assert team.get(f"/work/{DOC}", member=BOB).status == 404
    assert team.get(f"/work/{DOC}", member=ALICE).status == 200


def test_a_page_save_cannot_change_the_front_matter_whoever_sends_it(team, work):
    open_ = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")
    put(team, work, DOC, open_)
    text = (work / DOC).read_text(encoding="utf-8")
    got = team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text),
                                "edits": [{"i": 0, "html": "<p>visibility: owner<br>owner: bob</p>"}]}, member=BOB)
    assert got.status == 200 and got.json()["skipped"]
    assert (work / DOC).read_text(encoding="utf-8") == text
    assert team.get(f"/work/{DOC}", member=ALICE).status == 200


def test_an_open_stream_of_bob_hears_nothing_once_a_door_write_closes_the_sheaf(team, browser, work):
    open_ = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")
    put(team, work, DOC, open_)
    sub = team.get(f"/_/live?doc=work/{DOC}", member=BOB).stream
    sub.drain()
    is_error, got = door_update(team, browser, work, DOC, lambda t: t.replace("sources: [issue:x/y#1]", "sources: [mail:t-1]")
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
    assert tick(team, work, rel, "Stop James", BOB).status == 200
    assert why in hub_rows("stop-james")[0]["drop"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a folder of mode 0500")
def test_stop_james_whose_drop_fails_says_failed_and_leaves_no_dot_file(team, work, stop_dir):
    put(team, work, DOC, STOPPABLE)
    stop_dir.chmod(0o500)
    try:
        assert tick(team, work, DOC, "Stop James", BOB).status == 200
    finally:
        stop_dir.chmod(0o700)
    assert hub_rows("stop-james")[0]["drop"].startswith("failed: ")
    assert list(stop_dir.iterdir()) == []


def test_a_source_list_written_without_indent_is_read_too(team, work):
    put(team, work, DOC, PRIVATE.replace("sources: [library:doc-123]", "sources:\n- library:x"))
    assert team.get(f"/work/{DOC}", member=BOB).status == 404
    assert team.get(f"/work/{DOC}", member=ALICE).status == 200


def test_a_sheaf_whose_front_matter_follows_a_byte_order_mark_is_read_too(team, work):
    put(team, work, DOC, "﻿" + PRIVATE)
    assert team.get(f"/work/{DOC}", member=BOB).status == 404
    assert team.get(f"/work/{DOC}", member=ALICE).status == 200


@pytest.mark.parametrize("change", [
    lambda t: t.replace("sources: [library:doc-123]", '"sources": [library:doc-123]'),
    lambda t: t.replace("sources: [library:doc-123]", "sources: [library:doc-123]\nsources: []"),
    lambda t: t.replace("sources: [library:doc-123]", "sources :\n  - library:doc-123"),
    lambda t: t.replace("sources: [library:doc-123]", "visibility: >-\n  owner"),
], ids=["quoted key", "key twice", "space before colon", "folded value"])
def test_a_front_matter_line_the_hub_cannot_read_keeps_the_sheaf_its_owners(team, work, change):
    put(team, work, DOC, change(PRIVATE))
    assert team.get(f"/work/{DOC}", member=BOB).status == 404
    assert team.get(f"/work/{DOC}", member=ALICE).status == 200


def test_the_owners_share_written_with_a_plus_bullet_opens_the_sheaf_too(team, work):
    put(team, work, DOC, PRIVATE.replace("- [ ] Share", "+ [ ] Share"))
    assert tick(team, work, DOC, "Share", ALICE).status == 200
    assert team.get(f"/work/{DOC}", member=BOB).status == 200


def test_share_with_a_plus_bullet_ticked_by_a_member_who_is_not_the_owner_is_refused(team, work):
    shared = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")
    put(team, work, DOC, shared.replace("- [ ] Share", "+ [ ] Share"))
    before = (work / DOC).read_text(encoding="utf-8")
    assert tick(team, work, DOC, "Share", BOB).status == 409
    assert (work / DOC).read_text(encoding="utf-8") == before


def test_the_owners_share_nested_in_a_list_opens_the_sheaf_too(team, work):
    put(team, work, DOC, PRIVATE.replace("- [ ] Share", "- Before you share\n  - [ ] Share"))
    assert tick(team, work, DOC, "Share", ALICE).status == 200
    assert team.get(f"/work/{DOC}", member=BOB).status == 200


def test_a_door_update_cannot_give_an_owner_to_an_owner_only_sheaf_that_had_none(team, browser, work):
    put(team, work, DOC, PRIVATE.replace("owner: alice\n", ""))
    # A rectoverso with no owner is no token's to see (9.11), so only the key reaches it.
    is_error, got = call(browser, "read", as_name="James", doc=f"work/{DOC}")
    is_error, got = call(browser, "update", as_name="James", doc=f"work/{DOC}", expected_hash=got["hash"],
                         text=got["text"].replace("assistant: James", "assistant: James\nowner: bob"))
    assert not is_error, got
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def test_a_save_of_bob_that_lands_after_the_sheaf_closed_writes_nothing(team, work, monkeypatch):
    open_ = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]").replace("- [ ] Share", "- [ ] Done")
    put(team, work, DOC, open_)
    closed = open_.replace("sources: [issue:x/y#1]", "sources: [mail:t-77]")
    assert team.get(f"/work/{DOC}", member=BOB).status == 200      # the page Bob saves from
    gate = team.hub.visible

    def a_door_write_closes_it_after_the_gate(member, address):
        ok = gate(member, address)
        if member.id == BOB:
            (work / DOC).write_text(closed, encoding="utf-8")
        return ok
    monkeypatch.setattr(team.hub, "visible", a_door_write_closes_it_after_the_gate)
    got = tick(team, work, DOC, "Done", BOB)
    assert got.status == 404, got.body
    assert (work / DOC).read_text(encoding="utf-8") == closed


@pytest.mark.parametrize("how", ["replaced", "in place"])
def test_a_sheaf_closed_with_the_same_size_and_time_is_closed_at_once(team, work, how):
    open_ = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")
    closed = PRIVATE.replace("sources: [library:doc-123]", "sources: [library:ab1]")
    assert len(open_) == len(closed)
    put(team, work, DOC, open_)
    f = work / DOC
    assert team.get(f"/work/{DOC}", member=BOB).status == 200
    st = f.stat()
    if how == "replaced":
        tmp = f.with_name("next.tmp")
        tmp.write_text(closed, encoding="utf-8")
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(tmp, f)
    else:
        f.write_text(closed, encoding="utf-8")
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def test_two_stop_james_in_one_second_leave_two_drops_and_two_rows(team, work, stop_dir, monkeypatch):
    # Through work.drop, as Tell: the second takes `-1`, and never writes over a drop James has not read.
    put(team, work, DOC, STOPPABLE.replace("- [ ] Stop James", "- [ ] Stop James\n- [ ] Stop James"))
    second = time.gmtime()
    monkeypatch.setattr(time, "gmtime", lambda *_: second)
    assert tick(team, work, DOC, "Stop James", BOB).status == 200
    assert tick(team, work, DOC, "Stop James", ALICE).status == 200
    first, again = sorted(stop_dir.iterdir())
    assert again.name == first.name + "-1"
    assert first.read_text(encoding="utf-8") == again.read_text(encoding="utf-8") == "acme/tiroir\n"
    assert {f.stat().st_mode & 0o777 for f in (first, again)} == {0o640}
    assert [r["drop"] for r in hub_rows("stop-james")] == ["written", "written"]


# ── Review round 2 (PR 10), and Tariq's digest round on agency-tiroir PR 32 ─────────────────────────────

@pytest.mark.parametrize("how", ["not UTF-8", "unreadable"])
def test_an_owner_only_sheaf_its_page_cached_answers_404_to_bob_once_its_file_cannot_be_read(team, work, how):
    if how == "unreadable" and os.geteuid() == 0:
        pytest.skip("root reads a file of mode 000")
    put(team, work, DOC, PRIVATE)
    assert team.get(f"/work/{DOC}", member=ALICE).status == 200       # the hub now holds its page
    f = work / DOC
    if how == "not UTF-8":
        f.write_bytes(f.read_bytes() + b"\nlatin1 caf\xe9\n")
    else:
        os.chmod(f, 0)
    try:
        assert team.get(f"/work/{DOC}", member=BOB).status == 404
        assert team.get(f"/_/doc?doc=work/{DOC}", member=BOB).status == 404
    finally:
        os.chmod(f, 0o644)


@pytest.mark.parametrize("change", [
    lambda t: t.replace("issue: acme/agency-tiroir#9", "issue: acme/agency-tiroir#99"),
    lambda t: t.replace("issue: acme/agency-tiroir#9\n", "")], ids=["another issue", "no issue"])
def test_a_door_update_keeps_the_issue_on_disk_which_names_the_owner(team, browser, work, change):
    put(team, work, DOC, PRIVATE)
    is_error, got = door_update(team, browser, work, DOC, change)
    assert not is_error, got
    assert front_matter((work / DOC).read_text(encoding="utf-8"))["issue"] == "acme/agency-tiroir#9"


def test_a_front_matter_after_a_byte_order_mark_is_no_block_a_member_can_edit(team, work):
    shared = "﻿" + PRIVATE.replace("owner: alice", "owner: alice\nshared: alice 2026-10-28T09:00:00Z")
    put(team, work, DOC, shared)
    assert team.get(f"/work/{DOC}", member=BOB).status == 200
    text = (work / DOC).read_text(encoding="utf-8")
    team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text), "edits": [{"i": 0, "html": "<p>gone</p>"}]},
              member=BOB)
    fm = front_matter((work / DOC).read_text(encoding="utf-8"))
    assert fm["owner"] == "alice" and fm["shared"] and fm["sources"] == ("library:doc-123",)


def test_a_comment_of_bob_that_lands_after_the_sheaf_closed_writes_nothing(team, work, monkeypatch):
    from sheafmd.blocks import split_md_blocks
    open_ = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")
    put(team, work, DOC, open_)
    closed = open_.replace("sources: [issue:x/y#1]", "sources: [mail:t-77]")
    assert team.get(f"/work/{DOC}", member=BOB).status == 200
    gate = team.hub.visible

    def a_door_write_closes_it_after_the_gate(member, address):
        ok = gate(member, address)
        if member.id == BOB:
            (work / DOC).write_text(closed, encoding="utf-8")
        return ok
    monkeypatch.setattr(team.hub, "visible", a_door_write_closes_it_after_the_gate)
    i = next(i for i, b in enumerate(split_md_blocks(open_)) if b.content.startswith("A quote"))
    got = team.post("/_/comment", {"doc": f"work/{DOC}", "op": "add", "hash": md_hash(open_), "block": i, "start": 0,
                                   "end": 7, "quote": "A quote", "body": "Is this right?"}, member=BOB)
    assert got.status == 404, got.body
    assert (work / DOC).read_text(encoding="utf-8") == closed


@pytest.mark.parametrize("front,body", [("\n", "\r\n"), ("\r\n", "\n")], ids=["LF over CRLF", "CRLF over LF"])
def test_share_rewrites_the_front_matter_lines_only_never_the_bodys_line_endings(front, body):
    from sheafmd.hub import visibility
    text = front.join(["---", "owner: alice", "sources: [library:1]", "---", ""]) + \
        body.join(["line one", "```", "code", "```", ""])
    out = visibility.share(text, "alice", "T")
    assert out.endswith(body.join(["line one", "```", "code", "```", ""]))
    assert visibility.effective(visibility.front_matter(out)) == "project"


@pytest.mark.parametrize("old,new,words", [
    ("- &#9746; Share @a\n", "- [x] Share @a\n", set()),                             # a ballot, rewritten
    ("- [ ] Share\n", "- [x] Share @a\n", set()),                                      # the line changed too
    ("- [ ] Share\n- &#9746; Share\n", "- [x] Share\n", set()),                       # a line took its place
    ("- [ ] Share\n- [ ] Done\n", "- [ ] Share\n- [x] Done\n", set()),               # another box
    ("- [ ] Share\n", "- [x] Share\n", {"Share"}),
    ("* [ ] Share   \n", "* [x] Share   \n", {"Share"}),
    ("+ [ ] Stop James @x\n", "+ [X] Stop James @x\n", {"Stop James"})])
def test_a_tick_counts_only_when_a_toggled_block_ticks_that_line_alone(old, new, words):
    from sheafmd.hub import visibility
    assert visibility.newly_ticked([(old, new)]) == words
    assert visibility.newly_ticked([]) == set()


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
                    member=ALICE)
    assert got.status == 200, got.body
    assert "[x] Mark this digest as read" in (work / DOC).read_text(encoding="utf-8")   # the save went through
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def _block_html(text, word):
    """The block of `text` that holds `word`, as the page draws it (pandoc HTML), and its index."""
    from sheafmd import _pandoc
    from sheafmd.blocks import split_md_blocks
    blocks = split_md_blocks(text)
    i = next(k for k, b in enumerate(blocks) if word in b.content and b.kind != "frontmatter")
    return i, _pandoc.run(["-f", "gfm", "-t", "html5", "--no-highlight"], blocks[i].content).stdout


@pytest.mark.parametrize("ballot", ["&#9746;", "☒"])
def test_the_owner_deleting_the_open_share_box_above_a_ticked_ballot_does_not_share_the_sheaf(team, work, ballot):
    """Review 3, P1-1: the save writes the ballot as `- [x] Share` where `- [ ] Share` was; only a box the
    save toggled counts, never a line that took the place of another."""
    import re
    put(team, work, DOC, PRIVATE.replace("- [ ] Share", f"- [ ] Share\n- {ballot} Share"))
    text = (work / DOC).read_text(encoding="utf-8")
    i, html = _block_html(text, "Share")
    html = re.sub(r"<ul[^>]*>.*?</ul>\s*", "", html, count=1, flags=re.S)       # the open box's list, gone
    got = team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text), "edits": [{"i": i, "html": html}]},
                    member=ALICE)
    assert got.status == 200, got.body
    after = (work / DOC).read_text(encoding="utf-8")
    assert "- [ ] Share" in after and "- [x]" not in after and "shared" not in front_matter(after)    # the ballot's line is left unticked
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


@pytest.mark.parametrize("body", ["- one\n* [ ] Share\n- three", "+ [ ] Share", "- [ ] Share   ", "- [ ] Share\t",
                                  "- [ ] Share @alice", "- top\n  - [ ] Share\n  - other",
                                  "- one\n\n- [ ] Share\n\n- three", "- [ ] Share\n- item <!-- x -->"])
def test_the_owners_tick_in_the_page_shares_whatever_the_lists_shape(team, work, body):
    put(team, work, DOC, PRIVATE.replace("- [ ] Share", body))
    text = (work / DOC).read_text(encoding="utf-8")
    i, html = _block_html(text, "Share")
    html = html.replace('<input type="checkbox"', '<input type="checkbox" checked=""', 1)
    got = team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text), "edits": [{"i": i, "html": html}]},
                    member=ALICE)
    assert got.status == 200, got.body
    assert team.get(f"/work/{DOC}", member=BOB).status == 200


def test_the_lists_tick_of_a_star_bullet_share_shares(team, work):
    put(team, work, DOC, PRIVATE.replace("- [ ] Share", "* [ ] Share"))
    assert team.post("/_/tick", {"doc": f"work/{DOC}", "action": 0, "word": "Share",
                                 "hash": md_hash((work / DOC).read_text(encoding="utf-8"))}, member=ALICE).status == 200
    assert team.get(f"/work/{DOC}", member=BOB).status == 200


def test_a_share_ticked_in_the_same_save_as_another_edit_of_its_list_shares_nothing(team, work):
    """Review 3, P2-1, as SPEC 9.11 now says: pandoc rewrote the list, so no box was toggled alone."""
    put(team, work, DOC, PRIVATE.replace("- [ ] Share", "- teh item\n- [ ] Share"))
    text = (work / DOC).read_text(encoding="utf-8")
    i, html = _block_html(text, "Share")
    html = html.replace('<input type="checkbox"', '<input type="checkbox" checked=""', 1).replace("teh", "the")
    got = team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text), "edits": [{"i": i, "html": html}]},
                    member=ALICE)
    assert got.status == 200, got.body
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def test_the_owners_tick_saved_against_an_older_version_still_shares(team, work):
    """A save the hub merges onto a newer text (an assistant wrote another block meanwhile) keeps its toggle."""
    put(team, work, DOC, PRIVATE)
    text = (work / DOC).read_text(encoding="utf-8")
    i, html = _block_html(text, "Share")
    assert team.get(f"/work/{DOC}", member=ALICE).status == 200           # the page holds this version
    (work / DOC).write_text(text.replace("A quote from the contract.", "A quote from the contract, revised."),
                            encoding="utf-8")
    html = html.replace('<input type="checkbox"', '<input type="checkbox" checked=""', 1)
    got = team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text), "edits": [{"i": i, "html": html}]},
                    member=ALICE)
    assert got.status == 200, got.body
    assert got.json().get("merged") is True
    after = (work / DOC).read_text(encoding="utf-8")
    assert "revised" in after and "- [x] Share" in after
    assert team.get(f"/work/{DOC}", member=BOB).status == 200


@pytest.mark.parametrize("was", ["- &#9746; Share", "- [x] Share"])
def test_a_merged_save_does_not_tick_a_box_an_assistant_reopened_since_the_page_loaded(team, browser, work, was):
    """Review 3, narrow check P1: the merge compared the page's boxes with the file's block, not with the
    block the page held; a box James reopened counted as ticked by the owner's tick of Done."""
    base = PRIVATE.replace("- [ ] Share", f"{was}\n- [ ] Done")
    put(team, work, DOC, base)
    assert team.get(f"/work/{DOC}", member=ALICE).status == 200           # the page holds this version
    i, html = _block_html(base, "Done")
    html = html.replace('<input type="checkbox" />Done', '<input type="checkbox" checked="" />Done')
    cur = PRIVATE.replace("- [ ] Share", "- [ ] Share\n* [ ] Done")
    team.hub.proxy = members(work, alice=["james"])       # James works for Alice, the owner
    is_error, got = call(browser, "update", token=Tokens().add("james", write=True), doc=f"work/{DOC}",
                         text=cur, expected_hash=md_hash(base))
    assert not is_error, got
    got = team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(base), "edits": [{"i": i, "html": html}]},
                    member=ALICE)
    assert got.status == 200, got.body
    assert "shared" not in front_matter((work / DOC).read_text(encoding="utf-8"))
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def test_a_tick_that_a_later_edit_of_the_same_block_rewrites_shares_nothing(team, work):
    put(team, work, DOC, PRIVATE)
    text = (work / DOC).read_text(encoding="utf-8")
    i, html = _block_html(text, "Share")
    on = html.replace('<input type="checkbox"', '<input type="checkbox" checked=""', 1)
    got = team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text),
                                "edits": [{"i": i, "html": on}, {"i": i, "html": html.replace("Share", "Share later")}]},
                    member=ALICE)
    assert got.status == 200, got.body
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


@pytest.mark.parametrize("judged", [True, False], ids=["judged before", "never judged"])
def test_an_owner_only_sheaf_deleted_while_streams_are_open_is_told_to_its_owner_alone(team, work, monkeypatch, judged):
    now = [time.time()]
    team.hub.clock = lambda: now[0]
    monkeypatch.setattr(team.hub.index, "_start_sweep", lambda run: run())     # a sweep inside the tick
    f = work / DOC
    put(team, work, DOC, PRIVATE)
    bob, alice = (team.get("/_/live", member=m).stream for m in (BOB, ALICE))
    if judged:
        for m in (BOB, ALICE):
            team.get("/_/index.json", member=m)
    now[0] += SWEEP_SECONDS
    team.hub.tick()
    bob.drain(), alice.drain()
    f.unlink()
    now[0] += SWEEP_SECONDS
    team.hub.tick()
    assert [d for name, d in bob.drain() if name == "status"] == []
    if judged:
        assert [d["doc"] for name, d in alice.drain() if name == "status"] == [f"work/{DOC}"]


OPEN = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:acme/agency-tiroir#9]")


@pytest.mark.parametrize("line", ["date-created: 2026-10-28", "link-citations: true", "header-includes:\n  - x",
                                  "my key: a value", "document title: Ownership report", "a.b: shared visibility",
                                  "my key:\n  nested: value", "my key:\n- x\n- owner: bob"])
def test_a_front_matter_key_the_hub_does_not_enforce_leaves_an_open_sheaf_open(team, work, line):
    put(team, work, DOC, OPEN.replace("owner: alice\n", f"owner: alice\n{line}\n"))
    assert team.get(f"/work/{DOC}", member=BOB).status == 200


@pytest.mark.parametrize("line", ['"visibility": owner', "'owner': bob", '"\\x6fwner": bob', "? visibility\n: owner",
                                  "visibility : owner", "lang: en\n{kind: x,\n  visibility: owner}", "&a key: x",
                                  "lang: en\n[a, b]: x\n  visibility: owner"])
def test_a_line_that_may_spell_a_key_the_hub_enforces_still_closes_the_sheaf(team, work, line):
    put(team, work, DOC, OPEN.replace("owner: alice\n", f"owner: alice\n{line}\n"))
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def test_a_write_token_cannot_read_an_owner_only_sheaf(team, browser, work):
    put(team, work, DOC, PRIVATE)
    token = Tokens().add("mistral", write=True)
    is_error, got = call(browser, "read", token=token, doc=f"work/{DOC}")
    _, missing = call(browser, "read", token=token, doc="work/acme/tiroir/nothing.md")
    assert is_error and got == missing.replace("nothing.md", DOC.rsplit("/", 1)[1])


THREAD = ('A quote from the contract.<!-- sheaf-comment id=c1 by="Alice" at=2026-10-28T09:00 status=open '
          'quote="contract"\nThe fee?\n-->')


def test_a_token_cannot_read_the_threads_of_an_owner_only_sheaf(team, browser, work):
    put(team, work, DOC, PRIVATE.replace("A quote from the contract.", THREAD))
    token = Tokens().add("codex")
    is_error, got = call(browser, "threads", token=token, doc=f"work/{DOC}", status="all")
    assert is_error and got.startswith(f"There is no document work/{DOC} ") and "fee" not in got


@pytest.mark.parametrize("tool, args", [("reply", {"id": "c1", "text": "Noted."}), ("resolve", {"id": "c1"})])
def test_a_token_cannot_answer_or_resolve_a_thread_of_an_owner_only_sheaf(team, browser, work, tool, args):
    put(team, work, DOC, PRIVATE.replace("A quote from the contract.", THREAD))
    before = (work / DOC).read_text(encoding="utf-8")
    is_error, got = call(browser, tool, token=Tokens().add("codex"), doc=f"work/{DOC}", **args)
    assert is_error and got.startswith(f"There is no document work/{DOC} ")
    assert (work / DOC).read_text(encoding="utf-8") == before


def test_documents_does_not_list_an_owner_only_sheaf_to_a_token(team, browser, work):
    put(team, work, DOC, PRIVATE.replace("A quote from the contract.", THREAD))
    put(team, work, "acme/tiroir/open.md", "# Open\n\n" + THREAD + "\n")
    token = Tokens().add("mistral", write=True)
    for open_only in (True, False):
        is_error, got = call(browser, "documents", token=token, open_only=open_only)
        listed = [d["doc"] for d in got if "doc" in d]
        assert not is_error and "work/acme/tiroir/open.md" in listed and f"work/{DOC}" not in listed


def test_a_token_cannot_update_an_owner_only_sheaf_even_with_its_hash(team, browser, work):
    put(team, work, DOC, PRIVATE)
    before = (work / DOC).read_text(encoding="utf-8")
    is_error, got = call(browser, "update", token=Tokens().add("james", write=True), doc=f"work/{DOC}",
                         text=before.replace("A quote", "No quote"), expected_hash=md_hash(before))
    assert is_error and got.startswith(f"There is no document work/{DOC} ")
    assert (work / DOC).read_text(encoding="utf-8") == before


def test_a_tokens_update_with_a_wrong_hash_does_not_tell_an_owner_only_sheaf_from_none(team, browser, work):
    put(team, work, DOC, PRIVATE)
    token = Tokens().add("james", write=True)
    before = (work / DOC).read_text(encoding="utf-8")
    is_error, got = call(browser, "update", token=token, doc=f"work/{DOC}", text="x\n", expected_hash="0" * 16)
    assert is_error and got.startswith(f"There is no document work/{DOC} ")
    assert (work / DOC).read_text(encoding="utf-8") == before


def test_a_token_bound_to_the_owner_reads_the_owners_sheaf(team, browser, work):
    team.hub.proxy = members(work, alice=["james-alice"])
    put(team, work, DOC, PRIVATE)
    is_error, got = call(browser, "read", token=Tokens().add("james-alice", write=True), doc=f"work/{DOC}")
    assert not is_error and "A quote from the contract." in got["text"]


def test_a_token_bound_to_another_member_does_not_see_the_owners_sheaf(team, browser, work):
    team.hub.proxy = members(work, alice=["james-alice"], bob=["james-bob"])
    put(team, work, DOC, PRIVATE.replace("A quote from the contract.", THREAD))
    put(team, work, "acme/tiroir/open.md", "# Open\n\n" + THREAD + "\n")
    token = Tokens().add("james-bob", write=True)
    is_error, got = call(browser, "read", token=token, doc=f"work/{DOC}")
    assert is_error and got.startswith(f"There is no document work/{DOC} ")
    listed = [d["doc"] for d in call(browser, "documents", token=token)[1] if "doc" in d]
    assert listed == ["work/acme/tiroir/open.md"]


def test_a_token_bound_to_the_owner_lists_and_answers_the_owners_sheaf(team, browser, work):
    team.hub.proxy = members(work, alice=["james-alice"])
    put(team, work, DOC, PRIVATE.replace("A quote from the contract.", THREAD))
    token = Tokens().add("james-alice")
    assert f"work/{DOC}" in [d["doc"] for d in call(browser, "documents", token=token)[1] if "doc" in d]
    is_error, got = call(browser, "reply", token=token, doc=f"work/{DOC}", id="c1", text="The fee is fixed.")
    assert not is_error and got["replies"][-1]["text"] == "The fee is fixed."


@pytest.mark.parametrize("tool, args", [
    ("reply", {"id": "c1", "text": " "}),
    ("update", {"text": "x\n", "expected_hash": "not a hash"}),
    ("update", {"text": "x" * (1024 * 1024 + 1), "expected_hash": "0" * 16})],
    ids=["empty reply", "malformed hash", "text too long"])
def test_a_wrong_argument_does_not_tell_a_hidden_sheaf_from_none(team, browser, work, tool, args):
    put(team, work, DOC, PRIVATE.replace("A quote from the contract.", THREAD))
    token = Tokens().add("james", write=True)
    _, hidden = call(browser, tool, token=token, doc=f"work/{DOC}", **args)
    _, missing = call(browser, tool, token=token, doc="work/acme/tiroir/nothing.md", **args)
    assert hidden == missing.replace("nothing.md", DOC.rsplit("/", 1)[1])


@pytest.mark.parametrize("tool, args", [("reply", {"id": "c1", "text": "Noted."}), ("resolve", {"id": "c1"})])
@pytest.mark.parametrize("open_tab", [False, True], ids=["no tab", "open tab"])
def test_a_reply_that_lands_after_the_sheaf_closed_writes_nothing(team, browser, work, monkeypatch, tool, args,
                                                                  open_tab):
    shared = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")
    put(team, work, DOC, shared.replace("A quote from the contract.", THREAD))
    if open_tab:
        assert team.get(f"/work/{DOC}", member=ALICE).status == 200
    door = browser.handler.door
    checked = door._comment

    def a_door_write_closes_it_after_the_check(*a, **kw):
        got = checked(*a, **kw)
        f = work / DOC
        f.write_text(f.read_text(encoding="utf-8").replace("sources: [issue:x/y#1]", "sources: [mail:t-1]"),
                     encoding="utf-8")
        return got
    monkeypatch.setattr(door, "_comment", a_door_write_closes_it_after_the_check)
    before_close = (work / DOC).read_text(encoding="utf-8")
    is_error, got = call(browser, tool, token=Tokens().add("james"), doc=f"work/{DOC}", **args)
    assert is_error and got.startswith(f"There is no document work/{DOC} ")
    after = (work / DOC).read_text(encoding="utf-8")
    assert after == before_close.replace("sources: [issue:x/y#1]", "sources: [mail:t-1]")


def test_an_update_that_lands_after_the_sheaf_closed_writes_nothing(team, browser, work, monkeypatch):
    shared = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")
    put(team, work, DOC, shared)
    token = Tokens().add("james", write=True)
    _, got = call(browser, "read", token=token, doc=f"work/{DOC}")
    door, named = browser.handler.door, browser.handler.door._address
    closed = shared.replace("sources: [issue:x/y#1]", "sources: [mail:t-1]")

    def a_door_write_closes_it_after_the_check(*a, **kw):
        address = named(*a, **kw)
        (work / DOC).write_text(closed, encoding="utf-8")
        return address
    monkeypatch.setattr(door, "_address", a_door_write_closes_it_after_the_check)
    is_error, said = call(browser, "update", token=token, doc=f"work/{DOC}", text=got["text"] + "\nMore.\n",
                          expected_hash=got["hash"])
    assert is_error and said.startswith(f"There is no document work/{DOC} ")
    assert (work / DOC).read_text(encoding="utf-8") == closed


@pytest.fixture
def bob_root(team, work):
    """A root of Bob's alone, with an open page in it (no front matter, so open to the project)."""
    root = work.parent / "bobroot"
    root.mkdir()
    f = root / "notes.md"
    f.write_text("# Bob's notes\n\n" + THREAD + "\n", encoding="utf-8")
    name = team.hub.roots.for_document(f).name
    return root, f"{name}/notes.md"


def test_a_door_create_whose_owner_cannot_reach_its_root_is_refused(team, browser, work, bob_root):
    """An owner who is a member but not of the rectoverso's root could not open it either (9.9): an orphan all the
    same (#30)."""
    root, notes = bob_root
    team.hub.proxy = members(work, bob_also=root, bob=["mail-bob"])
    name = notes.split("/", 1)[0]
    is_error, got = call(browser, "create", token=Tokens().add("mail-bob", write=True), doc=f"{name}/x.md",
                         text=MAIL_TEXT.replace("sources:", "owner: alice\nsources:"))
    assert is_error and "owner" in got, got
    assert not (root / "x.md").exists()


def test_a_refused_create_over_a_hidden_sheaf_answers_only_that_its_name_is_taken(team, browser, work,
                                                                                monkeypatch):
    """Whether a create has an owner reads the list's row for its address: over a rectoverso the token may not see,
    the answer is the taken name's alone, whatever issue the text guesses (#30)."""
    put(team, work, DOC, PRIVATE)
    monkeypatch.setattr(team.hub, "assignees", lambda address, fm: ["tiroir"] if "issue" in fm else None)
    token = Tokens().add("mistral", write=True)
    answers = {call(browser, "create", token=token, doc=f"work/{DOC}", text=text)[1]
               for text in (MAIL_TEXT, MAIL_TEXT.replace("sources:", "issue: acme/agency-tiroir#9\nsources:"))}
    assert answers == {f"work/{DOC} exists already; `create` makes a new page, and `update` changes one."}


def test_a_create_over_a_hidden_sheaf_near_the_limit_answers_only_that_its_name_is_taken(team, browser, work,
                                                                                        monkeypatch):
    """The owner line `_owned` adds depends on the list's row for the address; over a rectoverso the token may not
    see, a text near the limit must not tell by its size answer which issue that rectoverso names (#30)."""
    put(team, work, DOC, PRIVATE)
    team.hub.proxy = members(work, bob=["mail-bob"])
    monkeypatch.setattr(team.hub, "assignees",
                        lambda address, fm: ["tiroir"] if fm.get("issue") == "acme/agency-tiroir#9" else None)
    token = Tokens().add("mail-bob", write=True)
    answers = set()
    for guess in ("acme/agency-tiroir#9", "acme/agency-tiroir#8"):
        head = f"---\nvisibility: owner\nsources: [mail]\nissue: {guess}\n---\n"
        answers.add(call(browser, "create", token=token, doc=f"work/{DOC}",
                         text=head + "x" * (MAX_TEXT - len(head) - 6) + "\n")[1])
    assert answers == {f"work/{DOC} exists already; `create` makes a new page, and `update` changes one."}


def test_a_create_refused_for_no_owner_through_a_link_tells_nothing_of_what_is_behind_it(team, browser, work,
                                                                                       tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("# Secret\n", encoding="utf-8")
    (work / "alias").symlink_to(outside)
    token = Tokens().add("mistral", write=True)
    answers = {call(browser, "create", token=token, doc=f"work/alias/{name}", text=MAIL_TEXT)[1].replace(name, "N")
               for name in ("secret.md", "none.md")}
    assert len(answers) == 1 and "link" in answers.pop()


def test_a_bound_tokens_create_that_its_owner_line_takes_past_the_limit_is_refused(team, browser, work):
    team.hub.proxy = members(work, alice=["mail"])
    (work / "list/a/inbox").mkdir(parents=True)
    text = MAIL_TEXT + "x" * (MAX_TEXT - len(MAIL_TEXT.encode("utf-8")) - 1) + "\n"
    is_error, got = call(browser, "create", token=Tokens().add("mail", write=True), doc=f"work/{MAIL}", text=text)
    assert is_error and "1 MiB" in got, got
    assert not (work / MAIL).exists()


def test_whose_a_document_is_is_judged_with_one_lookup_of_its_root_for_every_member(team, work, monkeypatch):
    lookups = []
    lookup = team.hub.roots.lookup
    monkeypatch.setattr(team.hub.roots, "lookup", lambda p: lookups.append(p) or lookup(p))
    everyone = list(team.hub.proxy.members.values())
    assert team.hub.members_owning(everyone, f"work/{DOC}") == everyone and len(lookups) == 1


def test_a_token_bound_to_a_member_reaches_only_that_members_roots(team, browser, work, bob_root):
    root, doc = bob_root
    team.hub.proxy = members(work, bob_also=root, alice=["james-alice"])
    put(team, work, "acme/tiroir/open.md", "# Open\n\n" + THREAD + "\n")
    token = Tokens().add("james-alice", write=True)
    assert not call(browser, "read", token=token, doc="work/acme/tiroir/open.md")[0]   # inside its roots
    is_error, got = call(browser, "read", token=token, doc=doc)
    assert is_error and got.startswith(f"There is no document {doc} ")
    is_error, got = call(browser, "threads", token=token, doc=str(root / "notes.md"))
    assert is_error and got == "A token cannot add a root, and the hub has no root that holds that file."
    assert doc not in [d.get("doc") for d in call(browser, "documents", token=token)[1]]
    is_error, got = call(browser, "documents", token=token, root=doc.split("/")[0])
    assert is_error and got == f"There is no root named {doc.split('/')[0]}."
    is_error, got = call(browser, "create", token=token, doc=doc.replace("notes", "copy"), text="# Copy\n")
    assert is_error and "is not inside a root of this hub" in got and not (root / "copy.md").exists()


def test_an_unbound_token_still_reaches_every_root(team, browser, work, bob_root):
    root, doc = bob_root
    team.hub.proxy = members(work, bob_also=root, alice=["james-alice"])
    is_error, got = call(browser, "read", token=Tokens().add("codex", write=True), doc=doc)
    assert not is_error and "Bob's notes" in got["text"]


def test_documents_stops_listing_a_sheaf_that_closed_with_the_same_size_and_time(team, browser, work):
    shared = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]")
    put(team, work, DOC, shared.replace("A quote from the contract.", THREAD))
    token = Tokens().add("codex")
    assert f"work/{DOC}" in [d.get("doc") for d in call(browser, "documents", token=token)[1]]
    f = work / DOC
    st = f.stat()
    f.write_text(f.read_text(encoding="utf-8").replace("sources: [issue:x/y#1]", "sources: [mail:t-1234]"),
                 encoding="utf-8")
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))            # as `cp -p` or a sync tool leaves it
    assert f.stat().st_size == st.st_size
    assert f"work/{DOC}" not in [d.get("doc") for d in call(browser, "documents", token=token)[1]]


@pytest.mark.parametrize("tool, doc, args", [
    ("create", "{root}/x.txt", {"text": "# X\n"}),
    ("read", "{path}/nope.md", {})], ids=["create", "read by path"])
def test_a_bound_token_cannot_tell_another_members_root_from_none(team, browser, work, bob_root, tool, doc, args):
    root, address = bob_root
    team.hub.proxy = members(work, bob_also=root, alice=["james-alice"])
    token = Tokens().add("james-alice", write=True)
    name = address.split("/")[0]
    nowhere = work.parent / "nowhere"
    _, theirs = call(browser, tool, token=token, doc=doc.format(root=name, path=root), **args)
    _, none = call(browser, tool, token=token, doc=doc.format(root="nosuchroot", path=nowhere), **args)
    assert theirs == none.replace("nosuchroot", name).replace(str(nowhere), str(root))


def test_a_bound_token_cannot_tell_another_members_root_from_none_through_a_link(team, browser, work, bob_root):
    """`create` by an absolute path through a link: one into Bob's root answers as one into no root (#68)."""
    root, _ = bob_root
    team.hub.proxy = members(work, bob_also=root, alice=["james-alice"])
    token = Tokens().add("james-alice", write=True)
    links, nowhere = work.parent / "links", work.parent / "nowhere"
    links.mkdir()
    nowhere.mkdir()
    (links / "lnk").symlink_to(root.parent)
    (links / "lnk2").symlink_to(nowhere)
    theirs, none = links / "lnk" / root.name / "x.md", links / "lnk2" / "x.md"
    is_error, got = call(browser, "create", token=token, doc=str(theirs), text="# X\n")
    _, expected = call(browser, "create", token=token, doc=str(none), text="# X\n")
    assert is_error and got == expected.replace(str(none), str(theirs))
    assert not (root / "x.md").exists()


def test_documents_for_a_bound_token_asks_git_once_per_folder_not_once_per_file(team, browser, work, monkeypatch):
    # Whether a file is the member's asks git of its folder: a large root must not start a git per file.
    import subprocess
    team.hub.proxy = members(work, bob=["james-bob"])
    for i in range(6):
        put(team, work, f"acme/tiroir/{i}.md", "# Open\n\n" + THREAD + "\n")
    run, asked = subprocess.run, []

    def counting(cmd, *a, **k):
        if cmd[:2] == ["git", "-C"]:
            asked.append(cmd)
        return run(cmd, *a, **k)
    monkeypatch.setattr(subprocess, "run", counting)
    listed = [d["doc"] for d in call(browser, "documents", token=Tokens().add("james-bob"))[1] if "doc" in d]
    assert len(listed) == 6
    folders = [cmd[2] for cmd in asked]
    assert len(folders) == len(set(folders)), folders      # no folder asked twice, whatever its files


# ── A file the hub cannot read, to a door token: told from none only to a token that saw it ───────────────

UNREADABLE = "{} cannot be read."


def spoil(f, how):
    """The file `f` made one the hub cannot read: bytes that are not UTF-8, or mode 000."""
    if how == "not UTF-8":
        f.write_bytes(f.read_bytes() + b"\nlatin1 caf\xe9\n")
    else:
        os.chmod(f, 0)


@pytest.mark.parametrize("how", ["not UTF-8", "unreadable"])
@pytest.mark.parametrize("tool, args", [("read", {}), ("threads", {"status": "all"}),
                                        ("reply", {"id": "c1", "text": "Noted."})])
def test_a_token_that_saw_a_sheaf_is_told_when_its_file_cannot_be_read(team, browser, work, how, tool, args):
    if how == "unreadable" and os.geteuid() == 0:
        pytest.skip("root reads a file of mode 000")
    team.hub.proxy = members(work, alice=["james-alice"])
    put(team, work, DOC, PRIVATE.replace("A quote from the contract.", THREAD))
    token = Tokens().add("james-alice", write=True)
    assert not call(browser, "read", token=token, doc=f"work/{DOC}")[0]
    f = work / DOC
    spoil(f, how)
    try:
        assert call(browser, tool, token=token, doc=f"work/{DOC}", **args) == (True, UNREADABLE.format(f"work/{DOC}"))
    finally:
        os.chmod(f, 0o644)


def test_an_unbound_token_is_told_when_the_file_of_an_open_sheaf_it_saw_cannot_be_read(team, browser, work):
    put(team, work, DOC, OPEN)
    assert team.get(f"/work/{DOC}", member=BOB).status == 200      # what the hub last read of it: open
    spoil(work / DOC, "not UTF-8")
    got = call(browser, "read", token=Tokens().add("codex", write=True), doc=f"work/{DOC}")
    assert got == (True, UNREADABLE.format(f"work/{DOC}"))


@pytest.mark.parametrize("token_of", ["bob", "nobody"])
def test_a_token_that_may_not_see_a_sheaf_is_told_nothing_of_its_unreadable_file(team, browser, work, token_of):
    team.hub.proxy = members(work, alice=["james-alice"], bob=["james-bob"])
    put(team, work, DOC, PRIVATE)
    assert not call(browser, "read", token=Tokens().add("james-alice", write=True), doc=f"work/{DOC}")[0]   # the hub read it
    spoil(work / DOC, "not UTF-8")
    token = Tokens().add("james-bob" if token_of == "bob" else "codex", write=True)
    is_error, got = call(browser, "read", token=token, doc=f"work/{DOC}")
    _, missing = call(browser, "read", token=token, doc="work/acme/tiroir/nothing.md")
    assert is_error and got == missing.replace("nothing.md", DOC.rsplit("/", 1)[1])


def test_an_unreadable_file_the_hub_never_read_is_told_as_none_even_to_its_owners_token(team, browser, work):
    # Without a good read since the hub started, nothing says the token may see it.
    team.hub.proxy = members(work, alice=["james-alice"])
    put(team, work, DOC, PRIVATE)
    spoil(work / DOC, "not UTF-8")
    token = Tokens().add("james-alice", write=True)
    is_error, got = call(browser, "read", token=token, doc=f"work/{DOC}")
    _, missing = call(browser, "read", token=token, doc="work/acme/tiroir/nothing.md")
    assert is_error and got == missing.replace("nothing.md", DOC.rsplit("/", 1)[1])
    assert missing.startswith("There is no document work/acme/tiroir/nothing.md ")


@pytest.mark.parametrize("tool, args", [("resolve", {"id": "c1"}), ("update", {"text": "x\n", "expected_hash": "0" * 16})])
def test_the_other_tools_tell_a_token_that_saw_a_sheaf_its_file_cannot_be_read(team, browser, work, tool, args):
    team.hub.proxy = members(work, alice=["james-alice"])
    put(team, work, DOC, PRIVATE.replace("A quote from the contract.", THREAD))
    token = Tokens().add("james-alice", write=True)
    assert not call(browser, "read", token=token, doc=f"work/{DOC}")[0]
    spoil(work / DOC, "not UTF-8")
    assert call(browser, tool, token=token, doc=f"work/{DOC}", **args) == (True, UNREADABLE.format(f"work/{DOC}"))


def test_a_token_whose_project_no_longer_names_its_member_is_told_nothing_of_the_unreadable_file(team, browser,
                                                                                                    work):
    team.hub.proxy = members(work, bob=["james-bob"])
    put(team, work, DOC, OPEN)
    token = Tokens().add("james-bob", write=True)
    assert not call(browser, "read", token=token, doc=f"work/{DOC}")[0]
    (work / "projects.toml").write_text('[projects."acme/tiroir"]\nmembers = ["Alice"]\n', encoding="utf-8")
    spoil(work / DOC, "not UTF-8")
    is_error, got = call(browser, "read", token=token, doc=f"work/{DOC}")
    _, missing = call(browser, "read", token=token, doc="work/acme/tiroir/nothing.md")
    assert is_error and got == missing.replace("nothing.md", DOC.rsplit("/", 1)[1])


def test_an_unreadable_file_that_replaced_the_one_a_token_saw_is_told_as_none(team, browser, work):
    # The last good read was of another file: what it said is nothing about this one.
    put(team, work, DOC, OPEN)
    token = Tokens().add("codex", write=True)
    assert not call(browser, "read", token=token, doc=f"work/{DOC}")[0]
    f = work / DOC
    os.rename(f, work / "kept.md")              # kept, so the new file cannot take its inode
    f.write_bytes(PRIVATE.encode("utf-8") + b"\nlatin1 caf\xe9\n")
    is_error, got = call(browser, "read", token=token, doc=f"work/{DOC}")
    _, missing = call(browser, "read", token=token, doc="work/acme/tiroir/nothing.md")
    assert is_error and got == missing.replace("nothing.md", DOC.rsplit("/", 1)[1])


OPEN = PRIVATE.replace("sources: [library:doc-123]\n", "")


def bob_door(team, browser, work, rel):
    """The door update of `rel` by Bob's assistant, over a rectoverso Alice owns that is open to the project:
    a function of the change to the text."""
    team.hub.proxy = members(work, bob=["bobdoor"])
    token = Tokens().add("bobdoor", write=True)

    def update(change):
        is_error, got = call(browser, "read", token=token, doc=f"work/{rel}")
        assert not is_error, got
        return call(browser, "update", token=token, doc=f"work/{rel}", text=change(got["text"]),
                    expected_hash=got["hash"])
    return update


@pytest.mark.parametrize("change", [
    lambda t: t.split("---\n", 2)[2],
    lambda t: "---\n---\n" + t.split("---\n", 2)[2],
    lambda t: "---\nclient: acme\n" + t.split("---\n", 2)[2]], ids=["no front matter", "empty", "no closing line"])
def test_a_door_update_of_an_open_sheaf_keeps_its_owner_and_issue_whatever_the_text_says(team, browser, work, change):
    put(team, work, DOC, OPEN)
    is_error, got = door_update(team, browser, work, DOC, change)
    assert not is_error, got
    fm = front_matter((work / DOC).read_text(encoding="utf-8"))
    assert (fm.get("owner"), fm.get("issue")) == ("alice", "acme/agency-tiroir#9")


def test_a_door_write_that_drops_the_front_matter_cannot_give_an_open_sheaf_to_another_members_assistant(team, browser, work):
    put(team, work, DOC, OPEN)
    update = bob_door(team, browser, work, DOC)
    is_error, got = update(lambda t: t.split("---\n", 2)[2])
    assert not is_error, got
    is_error, got = update(lambda t: "---\nsources: [mail:x]\n---\n" + t)
    assert not is_error, got
    fm = front_matter((work / DOC).read_text(encoding="utf-8"))
    assert fm.get("owner") == "alice" and fm.get("issue") == "acme/agency-tiroir#9"
    assert team.get(f"/work/{DOC}", member=BOB).status == 404
    assert team.get(f"/work/{DOC}", member=ALICE).status == 200


# ── the tick box's own words, "Shared with the team" (action-buttons 03) ──────────────────────────────────────

LABELLED = PRIVATE.replace("- [ ] Share", "- [ ] Shared with the team")


def test_the_owners_tick_of_the_labelled_box_shares_the_sheaf_as_share_does(team, work):
    put(team, work, DOC, LABELLED)
    assert tick(team, work, DOC, "Share", ALICE).status == 200
    text = (work / DOC).read_text(encoding="utf-8")
    fm = front_matter(text)
    assert fm["visibility"] == "project" and fm["shared"].startswith("alice ")
    assert "- [x] Shared with the team" in text
    assert team.get(f"/work/{DOC}", member=BOB).status == 200


def test_the_labelled_box_ticked_by_a_member_who_is_not_the_owner_is_refused_and_writes_nothing(team, work):
    put(team, work, DOC, LABELLED.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]"))
    before = (work / DOC).read_text(encoding="utf-8")
    got = tick(team, work, DOC, "Share", BOB)
    assert got.status == 409 and "owner" in got.json()["error"]
    assert (work / DOC).read_text(encoding="utf-8") == before


def test_the_list_reads_the_labelled_box_as_the_share_action_and_gives_the_word_share(team, work):
    sheaf = the_list.read_rectoverso(DOC, LABELLED)
    assert [a[0] for a in sheaf.actions] == ["Share"]
    assert [a[0] for a in the_list.read_rectoverso(DOC, LABELLED.replace("[ ]", "[x]")).pressed] == ["Share"]


def test_the_owners_release_of_the_labelled_box_makes_the_sheaf_their_own_alone_again(team, work):
    put(team, work, DOC, LABELLED)
    assert tick(team, work, DOC, "Share", ALICE).status == 200
    text = (work / DOC).read_text(encoding="utf-8")
    edit = the_list.tick_edit(text, 0, "Share", release=True)
    got = team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text), "edits": [edit]}, member=BOB)
    assert got.status == 409 and "owner" in got.json()["error"]
    assert (work / DOC).read_text(encoding="utf-8") == text
    got = team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text), "edits": [edit]}, member=ALICE)
    assert got.status == 200
    text = (work / DOC).read_text(encoding="utf-8")
    assert "- [ ] Shared with the team" in text and front_matter(text)["visibility"] == "owner"
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def test_the_hub_never_writes_the_new_label_into_a_file_that_holds_the_old_line(team, work):
    """An existing file keeps `- [ ] Share` through every write the hub makes (share, release): the agency-tiroir
    record routine reads only the old word, so the new label must come from a file's author, never from the hub."""
    put(team, work, DOC, PRIVATE)
    assert tick(team, work, DOC, "Share", ALICE).status == 200
    text = (work / DOC).read_text(encoding="utf-8")
    assert "- [x] Share\n" in text and "Shared with the team" not in text
    edit = the_list.tick_edit(text, 0, "Share", release=True)
    assert team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text), "edits": [edit]}, member=ALICE).status == 200
    text = (work / DOC).read_text(encoding="utf-8")
    assert "- [ ] Share\n" in text and "Shared with the team" not in text


def rename_and_tick(team, work, rel, member, label="Shared with the team"):
    """The page's save that renames the first unticked `Share` box to `label` and ticks it in one edit: a line that
    becomes a ticked Share from anything else than the owner's tick of it, which the page never sends."""
    text = (work / rel).read_text(encoding="utf-8")
    edit = the_list.tick_edit(text, 0, "Share")
    edit["html"] = edit["html"].replace("/>Share<", f"/>{label}<")
    assert label in edit["html"]
    return team.post("/_/save", {"doc": f"work/{rel}", "hash": md_hash(text), "edits": [edit]}, member=member)


# ── a ticked Share box on a sheaf that is not shared (SPEC 9.11) ──────────────────────────────────────────

def test_the_owners_save_that_renames_and_ticks_share_in_one_edit_leaves_the_box_unticked(team, work):
    put(team, work, DOC, PRIVATE)
    assert rename_and_tick(team, work, DOC, ALICE).status == 200
    text = (work / DOC).read_text(encoding="utf-8")
    assert "- [ ] Shared with the team" in text and "- [x]" not in text
    assert "shared" not in front_matter(text)
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def test_a_member_who_is_not_the_owner_cannot_rename_and_tick_share_and_nothing_is_written(team, work):
    put(team, work, DOC, PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:x/y#1]"))   # Bob can open it
    before = (work / DOC).read_text(encoding="utf-8")
    got = rename_and_tick(team, work, DOC, BOB)
    assert got.status == 409 and "Only the owner of this rectoverso can change who it is shared with" in got.json()["error"]
    assert (work / DOC).read_text(encoding="utf-8") == before


def test_the_owners_save_that_ticks_share_and_adds_an_item_in_the_same_block_leaves_the_box_unticked(team, work):
    put(team, work, DOC, PRIVATE)
    text = (work / DOC).read_text(encoding="utf-8")
    edit = the_list.tick_edit(text, 0, "Share")
    edit["html"] = edit["html"].replace("</ul>", "<li>Another item</li>\n</ul>")
    assert "Another item" in edit["html"]
    assert team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text), "edits": [edit]}, member=ALICE).status == 200
    after = (work / DOC).read_text(encoding="utf-8")
    assert "- [ ] Share" in after and "Another item" in after and "- [x]" not in after and "shared" not in front_matter(after)
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def test_a_door_create_with_a_ticked_labelled_box_on_an_owner_only_sheaf_leaves_it_unticked(team, browser, work):
    (work / "acme/tiroir").mkdir(parents=True)
    text = PRIVATE.replace("- [ ] Share", "- [x] Shared with the team")
    is_error, got = call(browser, "create", token=Tokens().add("mistral", write=True), doc=f"work/{DOC}", text=text)
    assert not is_error, got
    on_disk = (work / DOC).read_text(encoding="utf-8")
    assert "- [ ] Shared with the team" in on_disk and "- [x]" not in on_disk
    assert front_matter(on_disk)["visibility"] == "owner"
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


MIXED = PRIVATE.replace("- [ ] Share\n", "- [ ] Share\n- [ ] Shared with the team\n")


def test_a_page_with_a_box_of_each_spelling_is_shared_by_either_and_withdrawn_by_neither_alone(team, work):
    put(team, work, DOC, MIXED)
    assert tick(team, work, DOC, "Share", ALICE).status == 200
    assert tick(team, work, DOC, "Share", ALICE).status == 200      # the other spelling, now the first unticked
    text = (work / DOC).read_text(encoding="utf-8")
    assert "- [x] Share\n- [x] Shared with the team" in text and front_matter(text)["visibility"] == "project"
    edit = the_list.tick_edit(text, 0, "Share", release=True)
    assert team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text), "edits": [edit]}, member=ALICE).status == 200
    text = (work / DOC).read_text(encoding="utf-8")
    assert front_matter(text)["visibility"] == "project" and team.get(f"/work/{DOC}", member=BOB).status == 200
    edit = the_list.tick_edit(text, 0, "Share", release=True)
    assert team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text), "edits": [edit]}, member=ALICE).status == 200
    assert front_matter((work / DOC).read_text(encoding="utf-8"))["visibility"] == "owner"
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def test_a_plain_ticked_task_that_says_shared_with_the_team_is_shares_control_and_bob_cannot_untick_it(team, work):
    """The words are Share's, wherever a document has them, so a member who is not the owner is refused."""
    shared = PRIVATE.replace("sources: [library:doc-123]", "visibility: project").replace("- [ ] Share", "- [x] Shared with the team")
    put(team, work, DOC, shared)
    text = (work / DOC).read_text(encoding="utf-8")
    edit = the_list.tick_edit(text, 0, "Share", release=True)
    got = team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text), "edits": [edit]}, member=BOB)
    assert got.status == 409 and "withdraw its Share" in got.json()["error"]
    assert (work / DOC).read_text(encoding="utf-8") == text


def tick_names(team, work, rel, member):
    """The page's save that ticks the `Share with <names>` line, which the list does not read as an action."""
    text = (work / rel).read_text(encoding="utf-8")
    n = next(k for k, ln in enumerate(text.split("\n")) if ln.startswith("- [ ] Share with"))
    at = the_list._place(text, n, split_md_blocks(text))
    edit = {"i": at[0], "html": ticked_html(split_md_blocks(text)[at[0]], at[1], at=at[2])}
    return team.post("/_/save", {"doc": f"work/{rel}", "hash": md_hash(text), "edits": [edit]}, member=member)


# ── Share with <names> on a repo page opens it to the named members only (PR 394, round 2) ──

def test_share_with_a_name_on_a_project_sheaf_opens_it_to_that_member_and_not_to_the_project(team, work):
    put(team, work, DOC, PRIVATE.replace("- [ ] Share", "- [ ] Share with carol"))
    assert tick_names(team, work, DOC, ALICE).status == 200
    assert "- [x] Share with carol" in (work / DOC).read_text(encoding="utf-8")
    got = team.get(f"/work/{DOC}", member=BOB)
    assert got.status == 404 and got.body == team.get("/work/acme/site/nothing.md", member=BOB).body
    docs = [d["doc"] for r in team.get("/_/index.json", member=BOB).json()["roots"] for d in r["docs"]]
    assert f"work/{DOC}" not in docs
    assert team.get(f"/work/{DOC}", member=ALICE).status == 200


def test_share_with_bob_on_a_project_sheaf_opens_it_to_bob(team, work):
    put(team, work, DOC, PRIVATE.replace("- [ ] Share", "- [ ] Share with bob"))
    assert tick_names(team, work, DOC, ALICE).status == 200
    assert team.get(f"/work/{DOC}", member=BOB).status == 200
    (work / DOC).write_text((work / DOC).read_text(encoding="utf-8").replace("Share with bob", "Share with carol"), encoding="utf-8")
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def test_a_ticked_share_with_does_not_open_a_page_that_holds_a_private_source_unless_its_owner_shared_it(team, work):
    put(team, work, DOC, PRIVATE.replace("- [ ] Share", "- [x] Share with bob"))      # written by hand: no `shared` mark
    assert team.get(f"/work/{DOC}", member=BOB).status == 404
    # the owner's own tick writes the mark, and opens it
    (work / DOC).write_text(PRIVATE.replace("- [ ] Share", "- [ ] Share with bob"), encoding="utf-8")
    assert tick_names(team, work, DOC, ALICE).status == 200
    assert front_matter((work / DOC).read_text(encoding="utf-8"))["shared"].startswith("alice ")
    assert team.get(f"/work/{DOC}", member=BOB).status == 200


def test_a_door_update_that_adds_a_private_source_closes_a_named_share(team, browser, work):
    put(team, work, DOC, PRIVATE.replace("- [ ] Share", "- [ ] Share with bob"))
    assert tick_names(team, work, DOC, ALICE).status == 200
    assert team.get(f"/work/{DOC}", member=BOB).status == 200
    text = (work / DOC).read_text(encoding="utf-8")
    fm = front_matter(text)
    assert fm["visibility"] == "owner" and fm["shared"].startswith("alice ")
    is_error, got = door_update(team, browser, work, DOC,
                                lambda t: t.replace("sources: [library:doc-123]", "sources: [library:doc-123, mail:t-1]"))
    assert not is_error, got
    assert team.get(f"/work/{DOC}", member=BOB).status == 404


def test_a_door_update_keeps_the_mark_of_a_named_share_on_a_page_with_a_private_source(team, browser, work):
    put(team, work, DOC, PRIVATE.replace("- [ ] Share", "- [ ] Share with bob"))
    assert tick_names(team, work, DOC, ALICE).status == 200
    assert team.get(f"/work/{DOC}", member=BOB).status == 200
    is_error, got = door_update(team, browser, work, DOC, lambda t: t + "\nMore.\n")
    assert not is_error, got
    text = (work / DOC).read_text(encoding="utf-8")
    assert "More." in text and front_matter(text)["shared"].startswith("alice ")
    assert team.get(f"/work/{DOC}", member=BOB).status == 200


# ── Narrowing the audience closes the page at once to every member no longer named (PR 394, round 13) ──

CAROL = "9a1f3c52-6d0e-4b7a-8c25-1e4f7b3d9a60"
OPEN_SOURCE = PRIVATE.replace("sources: [library:doc-123]", "sources: [issue:acme/agency-tiroir#9]")


def three(team, work, **tokens):
    """The `[proxy]` table of Alice, Bob and Carol, members of one project root."""
    table = {ALICE: {"name": "Alice", "short": "alice", "github": "tiroir", "roots": [str(work)]},
             BOB: {"name": "Bob", "short": "bob", "github": "bobsmith", "roots": [str(work)]},
             CAROL: {"name": "Carol", "short": "carol", "github": "carolx", "roots": [str(work)]}}
    for m in table.values():
        if m["short"] in tokens:
            m["tokens"] = tokens[m["short"]]
    team.hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                                  "proxy_user": pwd.getpwuid(os.getuid()).pw_name, "members": table}, "the test")


def untick(team, work, rel, line, member):
    """The page's save that unticks the box of the line that reads `line`."""
    text = (work / rel).read_text(encoding="utf-8")
    n = next(k for k, ln in enumerate(text.split("\n")) if ln.endswith(line))
    at = the_list._place(text, n, split_md_blocks(text))
    edit = {"i": at[0], "html": ticked_html(split_md_blocks(text)[at[0]], at[1], tick=False, at=at[2])}
    return team.post("/_/save", {"doc": f"work/{rel}", "hash": md_hash(text), "edits": [edit]}, member=member)


def reads(team, rel):
    return {name: team.get(f"/work/{rel}", member=m).status for name, m in (("alice", ALICE), ("bob", BOB), ("carol", CAROL))}


def test_unticking_the_plain_share_while_a_named_share_stays_closes_the_page_to_the_member_not_named(team, work):
    three(team, work)
    put(team, work, DOC, OPEN_SOURCE.replace("- [ ] Share\n", "- [ ] Share\n- [ ] Share with bob\n"))
    assert tick(team, work, DOC, "Share", ALICE).status == 200
    assert tick_names(team, work, DOC, ALICE).status == 200
    assert reads(team, DOC) == {"alice": 200, "bob": 200, "carol": 200}
    assert untick(team, work, DOC, "- [x] Share", ALICE).status == 200
    assert reads(team, DOC) == {"alice": 200, "bob": 200, "carol": 404}
    fm = front_matter((work / DOC).read_text(encoding="utf-8"))
    assert fm["visibility"] == "owner" and "shared" not in fm       # a page with no private source holds no mark, and narrowing makes none


def test_naming_fewer_members_closes_the_page_to_the_one_no_longer_named(team, work):
    three(team, work)
    shared = OPEN_SOURCE.replace("owner: alice", "owner: alice\nvisibility: project\nshared: alice 2026-11-01T00:00:00Z")
    put(team, work, DOC, shared.replace("- [ ] Share\n", "- [x] Share with bob\n- [x] Share with carol\n"))
    assert reads(team, DOC) == {"alice": 200, "bob": 200, "carol": 200}
    assert untick(team, work, DOC, "- [x] Share with carol", ALICE).status == 200
    assert reads(team, DOC) == {"alice": 200, "bob": 200, "carol": 404}


def test_a_door_update_that_unticks_the_plain_share_while_a_named_share_stays_closes_the_page_to_the_member_not_named(team, browser, work):
    three(team, work, alice=["james"])
    shared = OPEN_SOURCE.replace("owner: alice", "owner: alice\nvisibility: project\nshared: alice 2026-11-01T00:00:00Z")
    put(team, work, DOC, shared.replace("- [ ] Share\n", "- [x] Share\n- [x] Share with bob\n"))
    assert reads(team, DOC) == {"alice": 200, "bob": 200, "carol": 200}
    token = Tokens().add("james", write=True)
    is_error, got = call(browser, "read", token=token, doc=f"work/{DOC}")
    assert not is_error, got
    is_error, got = call(browser, "update", token=token, doc=f"work/{DOC}", expected_hash=got["hash"],
                         text=got["text"].replace("- [x] Share\n", "- [ ] Share\n"))
    assert not is_error, got
    assert reads(team, DOC) == {"alice": 200, "bob": 200, "carol": 404}


# ── Narrowing never makes a `shared` mark (PR 394, round 14) ──

def test_a_door_update_that_narrows_the_share_and_adds_a_private_source_leaves_the_page_closed_to_the_member_named(team, browser, work):
    three(team, work, alice=["james"])
    shared = OPEN_SOURCE.replace("owner: alice", "owner: alice\nvisibility: project\nshared: alice 2026-11-01T00:00:00Z")
    put(team, work, DOC, shared.replace("- [ ] Share\n", "- [x] Share\n"))
    token = Tokens().add("james", write=True)
    is_error, got = call(browser, "read", token=token, doc=f"work/{DOC}")
    assert not is_error, got
    text = got["text"].replace("issue:acme/agency-tiroir#9", "library:doc-123").replace("- [x] Share\n", "- [x] Share with bob\n")
    is_error, got = call(browser, "update", token=token, doc=f"work/{DOC}", expected_hash=got["hash"], text=text)
    assert not is_error, got
    assert "shared" not in front_matter((work / DOC).read_text(encoding="utf-8"))
    assert not team.hub.opened_by_line(team.hub.proxy.members[BOB], f"work/{DOC}")
    assert reads(team, DOC) == {"alice": 200, "bob": 404, "carol": 404}


def test_a_save_that_narrows_the_share_keeps_the_mark_the_page_holds(team, work):
    three(team, work)
    shared = OPEN_SOURCE.replace("owner: alice", "owner: alice\nvisibility: project\nshared: alice 2026-11-01T00:00:00Z")
    put(team, work, DOC, shared.replace("- [ ] Share\n", "- [x] Share\n- [x] Share with bob\n"))
    assert untick(team, work, DOC, "- [x] Share", ALICE).status == 200
    fm = front_matter((work / DOC).read_text(encoding="utf-8"))
    assert fm["visibility"] == "owner" and fm["shared"] == "alice 2026-11-01T00:00:00Z"
    assert reads(team, DOC) == {"alice": 200, "bob": 200, "carol": 404}


def test_a_save_that_narrows_the_share_of_a_page_with_a_private_source_and_no_mark_makes_none(team, work):
    three(team, work)
    shared = PRIVATE.replace("owner: alice", "owner: alice\nvisibility: project")        # a private source, no mark
    put(team, work, DOC, shared.replace("- [ ] Share\n", "- [x] Share\n- [x] Share with bob\n"))
    assert untick(team, work, DOC, "- [x] Share", ALICE).status == 200
    assert "shared" not in front_matter((work / DOC).read_text(encoding="utf-8"))
    assert reads(team, DOC) == {"alice": 200, "bob": 404, "carol": 404}


def test_editing_share_with_names_into_a_plain_share_while_the_box_is_ticked_opens_the_page_to_the_project(team, work):
    """The box stays ticked, so it is no new tick: the owner's save still writes `visibility: project` (9.11)."""
    put(team, work, DOC, PRIVATE.replace("- [ ] Share", "- [ ] Share with carol"))
    assert tick_names(team, work, DOC, ALICE).status == 200
    assert team.get(f"/work/{DOC}", member=BOB).status == 404                      # named carol only
    text = (work / DOC).read_text(encoding="utf-8")
    i = next(n for n, b in enumerate(split_md_blocks(text)) if "Share with" in b.content)
    got = team.post("/_/save", {"doc": f"work/{DOC}", "hash": md_hash(text),
                                "edits": [{"i": i, "html": '<ul class="task-list"><li><input type="checkbox" checked disabled>'
                                                           ' Share</li></ul>'}]}, member=ALICE)
    assert got.status == 200, got.text
    after = (work / DOC).read_text(encoding="utf-8")
    assert "- [x] Share\n" in after and front_matter(after)["visibility"] == "project"
    assert team.get(f"/work/{DOC}", member=BOB).status == 200


@pytest.mark.parametrize("by, seen_by_hub", [("Bob", False), ("Alice", True)])
def test_the_doors_dot_for_a_member_is_the_one_of_their_index(team, browser, work, by, seen_by_hub):
    """One dot for both (8.6, 9.9): a member's own thread is not unread to them, and what the hub account has seen is
    not what the member has."""
    team.hub.proxy = members(work, bob=["james-bob"])
    address = put(team, work, "acme/tiroir/open.md", "# Open\n\n" + THREAD.replace('by="Alice"', f'by="{by}"') + "\n")
    if seen_by_hub:
        team.hub.seen.mark(address, "c1", 1)
    [row] = [d for r in team.get("/_/index.json", member=BOB).json()["roots"] for d in r["docs"] if d["doc"] == address]
    [mine] = [d for d in call(browser, "documents", token=Tokens().add("james-bob"))[1] if d.get("doc") == address]
    assert (mine["dot"], mine["unread"]) == (row["dot"], row["unread"])
