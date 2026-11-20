"""The Sheaf view (SPEC 8.6, 9.9): a member's tree of folders and the table of their rectoversos, as the front's loader
mounts it from `/_/mount?sheaf=1`. Through the handler in proxy mode, in memory, several members per hub. The page of it
is in tests/page/test_mount_sheaf.py."""
import json
import subprocess

import pytest
from helpers import BEA, CAL, PLAN, Front

from test_hub_visibility import BOB, ALICE, PRIVATE, put as put_team, team  # noqa: F401  (fixtures)

SESSION = "6f1c2f0e-3a55-4a0e-9d52-0c1f6a1b7d11"


def sheaf(front, member=BEA, **kw):
    r = front.get("/_/mount?sheaf=1", member=member, **kw)
    assert r.status == 200, r.text
    return r.json()


def names(nodes):
    return [(n["name"], names(n["children"])) for n in nodes]


def paths(nodes):
    return [p for n in nodes for p in [n["path"], *paths(n["children"])]]


def docs(got):
    return [r["doc"] for r in got["sheaf"]["rows"]]


def fill(front, work, other):
    for root, rel in ((work, "plan.md"), (work, "ideas/first.md"), (other, "notes.md"), (other, "secret/mine.md")):
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"# {rel}\n\ntext\n", encoding="utf-8")
        front.hub.roots.for_document(f)
    return front


@pytest.fixture
def two(front, work, other):
    """Bea's `work` holds a plan and a page in a sub-folder; Cal's `other` holds his own notes."""
    return fill(front, work, other)


@pytest.fixture
def two_git(front, work, other):
    """The same, with Bea's `work` a git work tree when it is registered: a git root lists a dot-folder's pages (8.6)."""
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    return fill(front, work, other)


# ── what each member sees ────────────────────────────────────────────────────

def test_each_member_sees_their_own_roots_and_pages_only(two):
    bea, cal = sheaf(two, BEA), sheaf(two, CAL)
    assert [n["name"] for n in bea["sheaf"]["tree"]] == ["work"] and [n["name"] for n in cal["sheaf"]["tree"]] == ["other"]
    assert sorted(docs(bea)) == ["work/ideas/first.md", "work/plan.md"]
    assert sorted(docs(cal)) == ["other/notes.md", "other/secret/mine.md"]


def test_the_answer_is_the_sheaf_of_this_hub_version(two):
    got = sheaf(two)
    assert got["kind"] == "sheaf" and got["title"] == "Sheaf" and got["version"] and got["script"] and got["assets"]


def test_the_tree_is_the_path_on_disk_below_the_root_names(two):
    assert names(sheaf(two)["sheaf"]["tree"]) == [("work", [("ideas", [])])]
    node = sheaf(two)["sheaf"]["tree"][0]
    assert node["path"] == "work" and node["children"][0]["path"] == "work/ideas"


def test_a_row_has_the_title_the_folder_the_change_and_the_open_comments(two):
    row = {r["doc"]: r for r in sheaf(two)["sheaf"]["rows"]}["work/ideas/first.md"]
    assert row["title"] == "ideas/first.md" and row["folder"] == "work/ideas" and row["open"] == 0
    assert row["url"] == "/work/ideas/first.md" and row["mtime"] > 0 and row["when"]
    assert "dot" not in row and "status" not in row            # no List status: the Sheaf says where, the List what waits


def test_every_md_of_a_root_is_listed_rendered_or_not(two, work):
    assert "work/plan.md" not in two.hub.entries              # nothing was rendered
    assert "work/plan.md" in docs(sheaf(two))


def test_the_rows_go_newest_change_first(two, work):
    import os
    os.utime(work / "plan.md", (1_000_000_000, 1_000_000_000))
    os.utime(work / "ideas/first.md", (1_900_000_000, 1_900_000_000))
    assert docs(sheaf(two)) == ["work/ideas/first.md", "work/plan.md"]


def test_a_title_is_the_first_h1_not_a_later_one(two, work):
    (work / "plan.md").write_text("Intro words\n\n# The plan\n\n## Part\n\n# Not this\n", encoding="utf-8")
    row = {r["doc"]: r for r in sheaf(two)["sheaf"]["rows"]}["work/plan.md"]
    assert row["title"] == "The plan"


def test_open_comments_are_counted(two, work):
    from helpers import thread, with_threads
    (work / "plan.md").write_text(with_threads(thread("c1", "Cal")), encoding="utf-8")
    row = {r["doc"]: r for r in sheaf(two)["sheaf"]["rows"]}["work/plan.md"]
    assert row["open"] == 1


# ── dot-folders ──────────────────────────────────────────────────────────────

def test_a_dot_folder_is_no_node_of_the_tree_but_its_page_is_listed_and_opens_at_its_address(two_git, work):
    two = two_git
    f = work / ".tooling" / "n.md"
    f.parent.mkdir()
    f.write_text("# Scratch\n", encoding="utf-8")
    got = sheaf(two)
    assert names(got["sheaf"]["tree"]) == [("work", [("ideas", [])])]
    assert "work/.tooling/n.md" in docs(got)
    assert two.get("/work/.tooling/n.md").status == 200


def test_a_folder_inside_a_dot_folder_is_no_node_either(two_git, work):
    two = two_git
    f = work / ".claude" / "deep" / "n.md"
    f.parent.mkdir(parents=True)
    f.write_text("# Deep\n", encoding="utf-8")
    got = sheaf(two)
    assert names(got["sheaf"]["tree"]) == [("work", [("ideas", [])])]
    assert "work/.claude/deep/n.md" in docs(got)


# ── a folder with no page the member may see ─────────────────────────────────

def test_a_folder_that_holds_only_another_members_private_page_is_absent(team, work):
    put_team(team, work, "acme/site/2026-10-28-contract.md", PRIVATE)
    put_team(team, work, "acme/site/open.md", "# Open\n")
    put_team(team, work, "acme/hidden/2026-10-28-contract.md", PRIVATE)
    owner, bob = sheaf(team, ALICE), sheaf(team, BOB)
    assert "work/acme/hidden" in paths(owner["sheaf"]["tree"])
    assert paths(bob["sheaf"]["tree"]) == ["work", "work/acme", "work/acme/site"]
    assert sorted(docs(bob)) == ["work/acme/site/open.md", "work/plan.md"]
    assert "contract" not in str(bob)                        # nothing of the private page, nor of its folder's name


# ── the Write log on a row ───────────────────────────────────────────────────

def test_a_row_says_who_and_where_and_the_session_before_a_later_save(two):
    address = "work/plan.md"
    two.hub.writes.add(address, "Ada", "laptop", "update", session=SESSION, host="mac-mini")
    two.hub.writes.add(address, "Bea", "page", "save")
    row = {r["doc"]: r for r in sheaf(two)["sheaf"]["rows"]}[address]
    assert row["write"] == "Bea · page, before Ada"
    assert row["session"] == "Ada" and SESSION in row["session_tip"]


def test_the_machine_is_in_the_tooltip_only_when_declared(two):
    two.hub.writes.add("work/plan.md", "Ada", "laptop", "update", session=SESSION, host="mac-mini")
    two.hub.writes.add("work/ideas/first.md", "Bea", "page", "save")
    rows = {r["doc"]: r for r in sheaf(two)["sheaf"]["rows"]}
    assert rows["work/plan.md"]["write"] == "Ada · laptop" and "mac-mini" in rows["work/plan.md"]["write_tip"]
    assert rows["work/ideas/first.md"]["write_tip"] == ""
    assert "mac-mini" not in rows["work/plan.md"]["write"]


def test_a_chat_clients_write_is_its_label_alone(two):
    two.hub.writes.add("work/plan.md", "Claude.ai (Bea)", "chat client", "update")
    row = {r["doc"]: r for r in sheaf(two)["sheaf"]["rows"]}["work/plan.md"]
    assert row["write"] == "Claude.ai (Bea)" and row["session"] == ""


def test_a_page_with_no_write_says_nothing_of_one(two):
    row = {r["doc"]: r for r in sheaf(two)["sheaf"]["rows"]}["work/plan.md"]
    assert (row["write"], row["write_tip"], row["session"]) == ("", "", "")


def test_a_pull_and_a_disk_write_read_as_the_spec_names_them(two):
    two.hub.writes.add("work/plan.md", "git · Ada", "tiroir", "pull")
    two.hub.writes.add("work/ideas/first.md", "?", "tiroir", "disk")
    rows = {r["doc"]: r for r in sheaf(two)["sheaf"]["rows"]}
    assert rows["work/plan.md"]["write"] == "git · Ada" and rows["work/ideas/first.md"]["write"] == "tiroir · ?"


def test_a_write_that_is_the_session_itself_has_no_before(two):
    two.hub.writes.add("work/plan.md", "Ada", "laptop", "update", session=SESSION)
    row = {r["doc"]: r for r in sheaf(two)["sheaf"]["rows"]}["work/plan.md"]
    assert row["write"] == "Ada · laptop" and row["session"] == "Ada"


# ── the way back to the last agent session (10) ─────────────────────────────

RC = "https://rc.example.com/code/session_abc123"
CHAT = "3f2a9c1e-77aa-4b1d-9a10-5d0e8b6c2f44"


def link_of(front, address="work/plan.md"):
    return {r["doc"]: r for r in sheaf(front)["sheaf"]["rows"]}[address]["session_link"]


def test_an_own_laptop_session_is_the_id_the_log_recorded_and_its_remote_control_link(two):
    two.hub.writes.add("work/plan.md", "Claude Code (Bea)", "laptop", "update", session=SESSION, host="mac-mini", link=RC)
    assert link_of(two) == {"kind": "laptop", "provider": "claude", "session": SESSION, "remote": RC}


def test_a_codex_session_is_asked_of_the_laptop_as_codex(two):
    two.hub.writes.add("work/plan.md", "Codex (Bea)", "laptop", "update", session=SESSION)
    assert link_of(two) == {"kind": "laptop", "provider": "codex", "session": SESSION, "remote": ""}


def test_an_own_laptop_session_without_remote_control_has_the_id_alone(two):
    two.hub.writes.add("work/plan.md", "Claude Code (Bea)", "laptop", "update", session=SESSION)
    assert link_of(two) == {"kind": "laptop", "provider": "claude", "session": SESSION, "remote": ""}


def test_another_members_laptop_session_is_never_asked_of_this_members_laptop(two):
    two.hub.writes.add("work/plan.md", "Claude Code (Cal)", "laptop", "update", session=SESSION, link=RC)
    assert link_of(two) == {"kind": "remote", "href": RC}
    two.hub.writes.add("work/ideas/first.md", "Claude Code (Cal)", "laptop", "update", session=SESSION)
    assert link_of(two, "work/ideas/first.md") is None


def test_a_session_of_the_box_has_its_remote_control_link_or_none(two):
    two.hub.writes.add("work/plan.md", "Claude Code (Bea)", "tiroir", "update", session=SESSION, link=RC)
    assert link_of(two) == {"kind": "remote", "href": RC}
    two.hub.writes.add("work/ideas/first.md", "Claude Code (Bea)", "tiroir", "update", session=SESSION)
    assert link_of(two, "work/ideas/first.md") is None


def test_an_open_webui_write_links_to_its_chat_on_the_same_origin(two):
    two.hub.writes.add("work/plan.md", "Assistant (Bea)", "chat client", "update", chat=CHAT)
    row = {r["doc"]: r for r in sheaf(two)["sheaf"]["rows"]}["work/plan.md"]
    assert row["session_link"] == {"kind": "chat", "href": f"/c/{CHAT}"}
    assert row["session"] == "Assistant (Bea)"


def test_a_chat_client_without_a_chat_id_shows_its_label_and_no_link(two):
    two.hub.writes.add("work/plan.md", "Claude.ai (Bea)", "chat client", "update")
    assert link_of(two) is None


def test_a_page_with_no_session_has_no_link(two):
    assert link_of(two) is None


def test_the_writer_must_be_exactly_a_known_client_of_this_member(two):
    for writer in ("Claude Code (Cal (Bea))", "Other (Bea)"):
        two.hub.writes.add("work/plan.md", writer, "laptop", "update", session=SESSION)
        assert link_of(two) is None, writer


def test_a_bad_id_gives_no_link_even_with_a_remote_control_link(two):
    two.hub.writes.add("work/plan.md", "Claude Code (Bea)", "laptop", "update", session="../x", link=RC)
    assert link_of(two) is None


@pytest.mark.parametrize("bad", ["../x", "a b", "a/b", "x" * 65, "-lead", "claude:abc", "a\nb"])
def test_a_session_id_that_is_not_a_plain_id_is_not_carried(two, bad):
    two.hub.writes.add("work/plan.md", "Claude Code (Bea)", "laptop", "update", session=bad)
    assert link_of(two) is None


@pytest.mark.parametrize("bad", ["../x", "a b", "a?b=1", "a#b", "x" * 101, "-lead", "a/../b"])
def test_a_chat_id_that_is_not_a_plain_id_is_not_carried(two, bad):
    two.hub.writes.add("work/plan.md", "Assistant (Bea)", "chat client", "update", chat=bad)
    assert link_of(two) is None


def test_a_link_that_is_not_a_web_address_never_reaches_the_row(two):
    two.hub.writes.add("work/plan.md", "Claude Code (Bea)", "tiroir", "update", session=SESSION, link="javascript:alert(1)")
    assert link_of(two) is None


def test_the_id_is_in_no_answer_to_a_member_who_may_not_see_the_page(two):
    two.hub.writes.add("work/plan.md", "Claude Code (Bea)", "laptop", "update", session=SESSION)
    assert SESSION in json.dumps(sheaf(two, BEA)) and SESSION not in json.dumps(sheaf(two, CAL))


# ── who may ask ──────────────────────────────────────────────────────────────

def test_the_hubs_own_person_has_no_sheaf_on_the_loopback_port(two, browser):
    assert browser.get("/_/mount?sheaf=1").status == 404


def test_what_the_listing_cap_left_out_of_a_root_is_said(two, monkeypatch):
    from sheafmd.hub import roots
    monkeypatch.setattr(roots, "LIST_CAP", 1)
    got = sheaf(two)["sheaf"]
    assert got["more"] == two.get("/_/index.json").json()["more"] and got["more"]


# ── the byline of an opened page (8.6, 11) ───────────────────────────────────

def opened(front, address="work/plan.md", member=BEA):
    r = front.get(f"/_/mount?doc={address}", member=member)
    assert r.status == 200, r.text
    return r.json()["config"]["way_back"]


def test_an_opened_page_carries_the_way_back_the_row_has(two):
    two.hub.writes.add("work/plan.md", "Claude Code (Bea)", "laptop", "update", session=SESSION, host="mac-mini", link=RC)
    assert opened(two) == {"name": "Claude Code (Bea)", "tip": f"{SESSION} on mac-mini",
                           "link": {"kind": "laptop", "provider": "claude", "session": SESSION, "remote": RC}}
    assert opened(two) == {"name": "Claude Code (Bea)", "tip": f"{SESSION} on mac-mini", "link": link_of(two)}


def test_an_opened_page_with_no_session_has_no_way_back(two):
    assert opened(two) is None
    two.hub.writes.add("work/plan.md", "Claude.ai (Bea)", "chat client", "update")
    assert opened(two) is None


def test_an_opened_page_asks_only_the_asking_members_laptop(two):
    two.hub.writes.add("work/plan.md", "Claude Code (Cal)", "laptop", "update", session=SESSION)
    assert opened(two)["link"] is None
    two.hub.writes.add("work/plan.md", "Claude Code (Cal)", "laptop", "update", session=SESSION, link=RC)
    assert opened(two)["link"] == {"kind": "remote", "href": RC}


def test_an_opened_page_names_an_open_webui_chat(two):
    two.hub.writes.add("work/plan.md", "Assistant (Bea)", "chat client", "update", chat=CHAT)
    assert opened(two) == {"name": "Assistant (Bea)", "tip": "", "link": {"kind": "chat", "href": f"/c/{CHAT}"}}


def test_the_answer_of_doc_carries_the_way_back_so_an_open_page_follows_a_new_session(two):
    two.hub.writes.add("work/plan.md", "Claude Code (Bea)", "laptop", "update", session=SESSION)
    r = two.get("/_/doc?doc=work/plan.md", member=BEA)
    assert r.status == 200, r.text
    assert r.json()["way_back"]["link"] == {"kind": "laptop", "provider": "claude", "session": SESSION, "remote": ""}


# ── a caller that has gone ───────────────────────────────────────────────────

def test_a_listing_whose_caller_has_gone_stops_reading_pages(two, monkeypatch):
    """The server asks `gone()` of the connection; the data run of the Sheaf checks it between pages and ends, so a reload
    leaves no thread reading every page of every root for a caller that is not there."""
    read = []
    from sheafmd.hub import sheaf_view
    titles = sheaf_view.Titles.read
    monkeypatch.setattr(sheaf_view.Titles, "read", lambda self, *a: read.append(a) or titles(self, *a))
    for i in range(40):
        (two.hub.roots.get("work").path / f"p{i}.md").write_text(f"# p{i}\n", encoding="utf-8")
    asked = two.get("/_/mount?sheaf=1", member=BEA, gone=lambda: False)
    assert asked.status == 200
    full = len(read)
    read.clear()
    r = two.get("/_/mount?sheaf=1", member=BEA, gone=lambda: True)
    assert r.status == 499 and len(read) < full // 2, (r.status, len(read), full)


def test_a_clear_by_another_thread_between_the_store_and_the_return_does_not_lose_the_answer(tmp_path):
    from sheafmd.hub.sheaf_view import Titles

    class Clearing(dict):
        def __setitem__(self, k, v):
            super().__setitem__(k, v)
            self.clear()          # what another thread's full-cache start-over does at that moment

    p = tmp_path / "a.md"
    p.write_text("# Hello\n", encoding="utf-8")
    t = Titles()
    t._kept = Clearing()
    assert t.of(p, "a.md") == "Hello"


def test_the_team_overlay_leaves_a_page_whose_meta_is_not_json_as_it_is():
    from types import SimpleNamespace

    from sheafmd.hub.handler import Handler
    body = '<p>x</p><script id="rd-edit-meta" type="application/json">{not json</script>'
    me = SimpleNamespace(hub=SimpleNamespace(team=SimpleNamespace(list=lambda doc: [])))
    assert Handler._with_team(me, "page", body, "r/a.md", "bea") == body
