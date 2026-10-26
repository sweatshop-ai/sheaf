"""A member on the proxy socket (SPEC 9.9 "The member", "The credential"; 18 Proxy mode): their roots,
matched by folder; what they write and how it is signed; their seen state and red dot; Ask and Tell
off; their streams, which carry nothing of the hub account's session and end after 5 minutes.
In memory through the handler (`front`), but for the stream's end, which a real socket shows."""
import http.client
import socket
import subprocess
import time

import pytest
from helpers import (BEA, CAL, FRONT, GIT_FAILS, PLAN, UnixHTTP, git_fails, hold_job, page_meta, thread,
                     with_threads)

import sheafmd.comments as rdc
from sheafmd import paths
from sheafmd.hub import proxy
from sheafmd.hub.index import Status
from sheafmd.hub.proxy import PROXY_LINE
from sheafmd.source import md_hash

DOC = "work/plan.md"


@pytest.fixture
def mine(front, plan, other):
    """Bea's document `work/plan.md`, and Cal's `other/notes.md`, both registered."""
    (other / "notes.md").write_text(PLAN, encoding="utf-8")
    front.hub.roots.for_document(other / "notes.md")
    return front


def text(path):
    return path.read_text(encoding="utf-8")


# ── the member's roots (9.9; 8.2) ────────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", [
    ("GET", "/other/notes.md", None), ("GET", "/_/doc?doc=other/notes.md", None),
    ("GET", "/_/live?doc=other/notes.md", None), ("POST", "/_/save", {"doc": "other/notes.md", "hash": "x", "edits": []}),
    ("POST", "/_/comment", {"doc": "other/notes.md", "op": "status", "id": "c1", "status": "resolved"}),
    ("POST", "/_/seen", {"doc": "other/notes.md", "id": "c1", "count": 1}),
    ("POST", "/_/export", {"doc": "other/notes.md", "kind": "html"})])
def test_a_document_of_another_root_answers_as_one_that_does_not_exist(mine, other, method, path, body):
    before = text(other / "notes.md")
    got = mine.request(method, path, body=body)
    missing = mine.request(method, path.replace("notes.md", "nothing.md"),
                           body=body and {**body, "doc": "other/nothing.md"})
    assert got.status == missing.status == 404 and got.body == missing.body
    assert text(other / "notes.md") == before
    assert "other/notes.md" not in mine.hub.entries          # nothing was made or rendered for it


def test_cal_sees_his_document_and_not_beas(mine):
    assert mine.get("/other/notes.md", member=CAL).status == 200
    assert mine.get("/work/plan.md", member=CAL).status == 404


def test_the_index_lists_only_the_members_roots(mine):
    roots = [r["name"] for r in mine.get("/_/index.json").json()["roots"]]
    assert roots == ["work"]
    assert mine.get("/other/").status == 404 and mine.get("/work/").status == 200
    assert mine.get("/other").status == 404 and mine.get("/work").status == 301
    page = mine.get("/").text
    assert "/work/plan.md" in page and "notes.md" not in page and "/other/" not in page


def nested(work, hub):
    """`work/sub` made its own root: a git work tree inside Bea's folder."""
    sub = work / "sub"
    sub.mkdir()
    (sub / "deep.md").write_text(PLAN, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(sub)], check=True)
    return hub.roots.for_document(sub / "deep.md")


def test_a_root_nested_inside_a_members_root_stays_another_root(mine, work):
    root = nested(work, mine.hub)
    assert root.name == "sub"
    for path in ("/work/sub/deep.md", "/sub/deep.md", "/_/doc?doc=work/sub/deep.md"):
        assert mine.get(path).status == 404, path
    docs = [d["doc"] for r in mine.get("/_/index.json").json()["roots"] for d in r["docs"]]
    assert docs == [DOC]


def test_a_nested_root_that_is_the_members_too_is_theirs(front, plan, work):
    root = nested(work, front.hub)
    front.hub.proxy.members[BEA] = proxy.Member(BEA, "Bea", (str(work), str(work / "sub")))
    assert front.get("/sub/deep.md").status == 200
    assert front.get("/work/sub/deep.md").status == 404           # its root is `sub`, not `work`
    docs = {r["name"]: [d["doc"] for d in r["docs"]] for r in front.get("/_/index.json").json()["roots"]}
    assert docs == {"work": [DOC], root.name: [f"{root.name}/deep.md"]}    # the folder `sub` walked under both


def index_docs(front):
    return {d["doc"]: d for r in front.get("/_/index.json").json()["roots"] for d in r["docs"]}


GIT_DIR_DOCS = [".git/x.md", ".git/info/x.md", "keep.git/x.md", "keep.git/refs/x.md"]


@pytest.fixture
def git_dir_docs(front, plan, work):
    """A git repo `work/sub` inside Bea's folder, with a bare repo `sub/keep.git`, and a document at
    each path of GIT_DIR_DOCS."""
    sub = work / "sub"
    sub.mkdir()
    subprocess.run(["git", "init", "-q", str(sub)], check=True)
    subprocess.run(["git", "init", "-q", "--bare", str(sub / "keep.git")], check=True)
    for inside in GIT_DIR_DOCS:
        (sub / inside).parent.mkdir(parents=True, exist_ok=True)
        (sub / inside).write_text(PLAN, encoding="utf-8")
    return front


def answers_as_missing(front, path, nothing):
    """`path` answers `404` with the very body of `nothing`, a document that does not exist."""
    got, missing = front.get(path), front.get(nothing)
    return got.status == missing.status == 404 and got.body == missing.body


# Git runs, or fails as 8.2 says and names neither a work tree nor a git directory: the path tells one then.
WHETHER_GIT_RUNS = ["runs", *GIT_FAILS]


def as_git(how, monkeypatch, tmp_path):
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)


@pytest.mark.parametrize("how", WHETHER_GIT_RUNS)
@pytest.mark.parametrize("inside", GIT_DIR_DOCS)
def test_a_document_in_a_git_directory_of_a_nested_repo_answers_as_one_that_does_not_exist(git_dir_docs, monkeypatch,
                                                                                         tmp_path, how, inside):
    as_git(how, monkeypatch, tmp_path)
    assert answers_as_missing(git_dir_docs, f"/work/sub/{inside}", f"/work/sub/{inside.replace('x.md', 'nothing.md')}")


@pytest.mark.parametrize("how", WHETHER_GIT_RUNS)
def test_the_index_leaves_out_a_document_in_a_git_directory_of_a_nested_repo(git_dir_docs, monkeypatch, tmp_path,
                                                                           how):
    as_git(how, monkeypatch, tmp_path)
    assert list(index_docs(git_dir_docs)) == [DOC]


@pytest.mark.parametrize("how", WHETHER_GIT_RUNS)
def test_a_document_in_a_bare_repo_of_the_members_own_root_is_not_theirs(front, plan, work, monkeypatch, tmp_path,
                                                                      how):
    subprocess.run(["git", "init", "-q", "--bare", str(work / "keep.git")], check=True)
    (work / "keep.git" / "x.md").write_text(PLAN, encoding="utf-8")
    as_git(how, monkeypatch, tmp_path)
    assert answers_as_missing(front, "/work/keep.git/x.md", "/work/keep.git/nothing.md")
    assert list(index_docs(front)) == [DOC]


@pytest.mark.parametrize("how", GIT_FAILS)
def test_where_git_fails_a_nested_repos_work_tree_is_the_members_as_before(git_dir_docs, work, monkeypatch,
                                                                        tmp_path, how):
    (work / "sub" / "tree.md").write_text(PLAN, encoding="utf-8")
    git_fails(how, monkeypatch, tmp_path)
    assert git_dir_docs.get("/work/sub/tree.md").status == 200
    assert {DOC, "work/sub/tree.md"} <= set(index_docs(git_dir_docs))


@pytest.mark.parametrize("how", GIT_FAILS)
def test_where_git_fails_the_members_own_repo_a_document_in_its_git_directory_is_not_theirs(front, plan, work,
                                                                                          monkeypatch, tmp_path,
                                                                                          how):
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    (work / ".git" / "x.md").write_text(PLAN, encoding="utf-8")
    git_fails(how, monkeypatch, tmp_path)
    assert answers_as_missing(front, "/work/.git/x.md", "/work/.git/nothing.md")
    assert front.get("/work/plan.md").status == 200


@pytest.mark.parametrize("link", ["zz.md", "aa.md"])       # listed after the member's own file, and before it
def test_a_link_in_a_members_folder_to_a_nested_root_is_judged_by_where_it_points(front, plan, work, link):
    nested(work, front.hub)
    (work / "sub" / "deep.md").write_text(with_threads(thread("c1", "Zed"), thread("c2", "Zed")), encoding="utf-8")
    (work / link).symlink_to(work / "sub" / "deep.md")
    docs = index_docs(front)
    assert list(docs) == [DOC]                       # the link's document is `sub`'s, not hers; hers stays
    assert front.get(f"/work/{link}").status == 404


def test_a_root_forgotten_and_its_name_taken_by_another_folder_is_not_theirs(mine, work, tmp_path):
    assert mine.hub.forget_root("work") is not None
    elsewhere = tmp_path / "x" / "work"
    elsewhere.mkdir(parents=True)
    (elsewhere / "plan.md").write_text(PLAN, encoding="utf-8")
    assert mine.hub.roots.address(elsewhere / "plan.md") == DOC        # the name went to another folder
    assert mine.get("/work/plan.md").status == 404
    assert mine.get("/_/index.json").json()["roots"] == []


def test_a_folder_of_theirs_not_registered_yet_is_theirs_from_its_first_render(front, plan, tmp_path):
    later = tmp_path / "later"
    later.mkdir()
    (later / "a.md").write_text(PLAN, encoding="utf-8")
    front.hub.proxy.members[BEA] = proxy.Member(BEA, "Bea", (str(plan.parent), str(later)))
    assert front.get("/later/a.md").status == 404
    front.hub.render(later / "a.md", {}, None)
    assert front.get("/later/a.md").status == 200
    assert "later" in [r["name"] for r in front.get("/_/index.json").json()["roots"]]


# ── what a member writes (9.9; 8.6, 8.7) ─────────────────────────────────────

def add(front, quote="Second paragraph", body="Why pears?", **extra):
    md = front.hub.roots.resolve(DOC).read_text(encoding="utf-8")
    blk, s, e = rdc.find_quote(md, quote)
    return front.post("/_/comment", {"doc": DOC, "op": "add", "hash": md_hash(md), "block": blk,
                                     "start": s, "end": e, "quote": quote, "body": body, **extra})


def test_a_members_comment_and_reply_are_signed_with_their_name(front, plan):
    r = add(front)
    assert r.status == 200
    cid = r.json()["id"]
    assert front.post("/_/comment", {"doc": DOC, "op": "reply", "id": cid, "body": "And?"}).status == 200
    c = [c for c in front.get(f"/_/doc?doc={DOC}").json()["comments"] if c["id"] == cid][0]
    assert c["by"] == "Bea" and [r["by"] for r in c["replies"]] == ["Bea"]


@pytest.mark.parametrize("flag", ["ask", "tell"])
@pytest.mark.parametrize("op", ["add", "reply"])
def test_a_comment_with_ask_or_tell_is_400_and_writes_nothing(front, plan, flag, op):
    plan.write_text(with_threads(thread("c1", "Bea")), encoding="utf-8")
    before = text(plan)
    if op == "add":
        r = add(front, **{flag: True})
    else:
        r = front.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "body": "x", flag: True})
    assert r.status == 400 and r.json()["error"] == PROXY_LINE
    assert text(plan) == before


@pytest.mark.parametrize("op,body", [("edit", {"body": "changed"}), ("delete", {})])
def test_a_member_cannot_edit_or_delete_a_comment_signed_by_another_name(front, plan, op, body):
    plan.write_text(with_threads(thread("c1", "Ada")), encoding="utf-8")
    before = text(plan)
    r = front.post("/_/comment", {"doc": DOC, "op": op, "id": "c1", **body})
    assert r.status == 403 and text(plan) == before


def test_a_member_cannot_delete_their_comment_once_another_name_replied(front, plan):
    plan.write_text(with_threads(thread("c1", "Bea", "Ada")), encoding="utf-8")
    before = text(plan)
    assert front.post("/_/comment", {"doc": DOC, "op": "delete", "id": "c1"}).status == 403
    assert text(plan) == before
    assert front.post("/_/comment", {"doc": DOC, "op": "edit", "id": "c1", "body": "fixed"}).status == 200


def test_a_member_edits_and_deletes_their_own_and_resolves_anyones(front, plan):
    plan.write_text(with_threads(thread("c1", "Bea", "Bea"), thread("c2", "Ada")), encoding="utf-8")
    assert front.post("/_/comment", {"doc": DOC, "op": "edit", "id": "c1", "body": "fixed"}).status == 200
    assert front.post("/_/comment", {"doc": DOC, "op": "status", "id": "c2", "status": "resolved"}).status == 200
    assert front.post("/_/comment", {"doc": DOC, "op": "delete", "id": "c1"}).status == 200
    assert [c["id"] for c in front.get(f"/_/doc?doc={DOC}").json()["comments"]] == ["c2"]


def test_the_hubs_person_still_edits_and_deletes_any_comment(front, browser, plan):
    plan.write_text(with_threads(thread("c1", "Bea", "Cal")), encoding="utf-8")
    assert browser.post("/_/comment", {"doc": DOC, "op": "delete", "id": "c1"}).status == 200


def test_a_members_seen_state_and_red_dot_are_their_own(front, browser, plan):
    plan.write_text(with_threads(thread("c1", "Ada")), encoding="utf-8")       # by the hub's person
    def row(who):
        return who.get("/_/index.json").json()["roots"][0]["docs"][0]
    assert row(front)["unread"] == 1 and row(front)["dot"] == "red"
    assert row(browser)["unread"] == 0                                        # the person's own message
    assert front.post("/_/seen", {"doc": DOC, "id": "c1", "count": 1}).status == 200
    assert row(front)["unread"] == 0 and row(front)["dot"] == "blue"
    assert front.get(f"/_/doc?doc={DOC}").json()["seen"] == {"c1": 1}
    assert browser.get(f"/_/doc?doc={DOC}").json()["seen"] == {}
    assert front.hub.seen.get(DOC) == {}
    assert (paths.state_dir() / "seen-members.json").exists()


def test_a_members_index_rows_name_the_page_on_the_fronts_origin(front, browser, plan):
    assert front.get("/_/index.json").json()["roots"][0]["docs"][0]["url"] == f"/{DOC}"
    assert browser.get("/_/index.json").json()["roots"][0]["docs"][0]["url"] == browser.hub.url(DOC)


@pytest.mark.parametrize("page", ["/", "/work/"])
def test_a_members_index_page_names_the_fronts_origin_and_no_port_or_folder(front, browser, plan, work, page):
    mine, own = front.get(page).text, browser.get(page).text
    assert str(work) not in mine and f"port {front.hub.port}" not in mine
    assert f"· {FRONT}</span>" in mine and '<span class="path">' not in mine
    assert str(work) in own and f"port {front.hub.port}" in own


def test_a_members_index_json_has_no_folder(front, browser, plan, work):
    assert "path" not in front.get("/_/index.json").json()["roots"][0]
    assert browser.get("/_/index.json").json()["roots"][0]["path"] == str(work)


def test_forgetting_a_root_in_loopback_mode_writes_no_seen_state_of_members(browser, plan):
    assert browser.hub.forget_root("work") is not None
    assert not (paths.state_dir() / "seen-members.json").exists()


def dot(who):
    return who.get("/_/index.json").json()["roots"][0]["docs"][0]["dot"]


def test_a_member_gets_no_dot_of_the_hub_accounts_session(front, browser, plan, monkeypatch):
    plan.write_text(with_threads(thread("c1", "Bea", status="resolved")), encoding="utf-8")
    e = front.hub.entry(DOC)
    monkeypatch.setattr(e.live, "peek", lambda: (True, "Which file?"))       # told, and it asks its person
    assert dot(browser) == "red" and dot(front) == "green"
    monkeypatch.setattr(e.live, "peek", lambda: (True, ""))                  # told, and working
    assert dot(browser) == "orange" and dot(front) == "green"


def test_a_member_gets_no_orange_dot_while_the_hub_accounts_ask_runs(front, browser, plan):
    plan.write_text(with_threads(thread("c1", "Bea", status="resolved")), encoding="utf-8")
    _, release = hold_job(front.hub, DOC)
    try:
        assert dot(browser) == "orange" and dot(front) == "green"
        assert 'data-dot="orange"' not in front.get("/work/").text
    finally:
        release.set()


def test_doc_carries_nothing_of_the_hub_accounts_session(front, browser, plan, monkeypatch):
    e = front.hub.entry(DOC)
    monkeypatch.setattr(e.live, "session_question", lambda: "Which file?")
    got = front.get(f"/_/doc?doc={DOC}").json()
    assert got["question"] == "" and got["capabilities"] == [] and got["target"] is None
    assert got["lines"] == {"ask": PROXY_LINE, "tell": PROXY_LINE}
    assert browser.get(f"/_/doc?doc={DOC}").json()["question"] == "Which file?"


def test_doc_does_not_say_whether_the_hub_accounts_ask_runs(front, browser, plan):
    _, release = hold_job(front.hub, DOC)
    try:
        assert browser.get(f"/_/doc?doc={DOC}").json()["asking"] == ["c1"]
        assert front.get(f"/_/doc?doc={DOC}").json()["asking"] == []
    finally:
        release.set()


@pytest.fixture
def told(front, plan):
    """Thread c1, by the hub's person, told to the hub account's session and waiting for its reply."""
    plan.write_text(with_threads(thread("c1", "Ada")), encoding="utf-8")
    assert front.hub.entry(DOC).live.await_reply("c1")


def test_no_answer_says_which_threads_wait_for_the_hub_accounts_session(told, front, browser):
    assert browser.get(f"/_/doc?doc={DOC}").json()["telling"] == ["c1"]
    assert front.get(f"/_/doc?doc={DOC}").json()["telling"] == []
    r = add(front)
    assert r.status == 200 and r.json()["telling"] == []


def test_the_page_meta_block_is_the_members(front, browser, plan):
    meta = page_meta(front.get("/work/plan.md").text)
    assert meta["me"] == "Bea" and meta["can"] == [] and meta["agent"] is None
    assert meta["proxy"] is True and meta["member"] == BEA
    assert meta["lines"] == {"ask": PROXY_LINE, "tell": PROXY_LINE}
    own = page_meta(browser.get("/work/plan.md").text)
    assert own["me"] == "Ada" and "proxy" not in own and "member" not in own


# ── the streams (9.9 "The credential"; 8.8) ──────────────────────────────────

JOB_EVENTS = [("ask-started", {"id": "c1"}),
              ("ask-failed", {"id": "c1", "error": "claude exited with 1: Error: cannot read /home/ada/.claude.json"}),
              ("ask-cancelled", {"id": "c1"}), ("tell-sent", {"id": "c1"}),
              ("tell-waiting", {"ids": ["c1"], "question": "Which file?"}), ("tell-working", {"ids": ["c1"]}),
              ("tell-failed", {"id": "c1", "error": "the tmux pane %3 of session ada-main is gone"}),
              ("tell-cancelled", {"id": "c1", "sent": True})]


def test_a_members_document_stream_carries_no_job_of_the_hub_accounts_session_and_no_sign_out(told, front, browser):
    mine = front.get(f"/_/live?doc={DOC}").stream
    own = browser.get(f"/_/live?doc={DOC}").stream
    bus = front.hub.entry(DOC).bus
    for name, data in JOB_EVENTS:
        bus.publish(name, data)
    front.hub.rotate()
    assert [e for e in mine.drain() if e[0] != "hello"] == []
    assert [e[0] for e in own.drain() if e[0] != "hello"] == [n for n, _ in JOB_EVENTS] + ["signed-out"]


def test_a_members_document_stream_is_told_when_its_root_is_forgotten(front, plan):
    mine = front.get(f"/_/live?doc={DOC}").stream
    assert [n for n, _ in mine.drain()] == ["hello"]
    assert front.hub.forget_root("work") is not None
    assert mine.drain() == [("gone", {"doc": DOC})]


def test_a_member_is_told_the_id_of_their_own_roots_and_of_no_other(mine):
    """A member's page carries the id of the root it was served from, and their `/_/doc` names it, as the
    person's do (10.7): it is random, and names no folder (9.9). Of a root that is not theirs they are told
    nothing: the 404 of an address under its name names no root, as for a name that no root holds."""
    work_id, other_id = mine.hub.roots.get("work").id, mine.hub.roots.get("other").id
    assert page_meta(mine.get(f"/{DOC}").text)["root"] == work_id
    assert mine.get(f"/_/doc?doc={DOC}").json()["root"] == work_id
    assert mine.get("/_/doc?doc=work/nothing.md").json()["root"] == work_id
    theirs, nobody = mine.get("/_/doc?doc=other/notes.md"), mine.get("/_/doc?doc=nobody/notes.md")
    assert theirs.status == nobody.status == 404 and theirs.body == nobody.body
    assert theirs.json()["root"] is None
    for path in ("/", "/work/", "/_/index.json", f"/{DOC}", f"/_/doc?doc={DOC}", "/_/doc?doc=other/notes.md"):
        assert other_id not in mine.get(path).text, path
    assert page_meta(mine.get("/other/notes.md", member=CAL).text)["root"] == other_id


def test_a_members_doc_names_another_root_once_another_folder_of_theirs_takes_the_name(front, plan, tmp_path):
    """The page's look at a reconnect (10.7) through the proxy socket: the folder of theirs that took the
    name after a forget is another root, and their own root forgotten with nothing in its place is none."""
    later = tmp_path / "x" / "work"
    later.mkdir(parents=True)
    (later / "plan.md").write_text(PLAN, encoding="utf-8")
    front.hub.proxy.members[BEA] = proxy.Member(BEA, "Bea", (str(plan.parent), str(later)))
    first = front.get(f"/_/doc?doc={DOC}").json()["root"]
    assert first == front.hub.roots.get("work").id
    assert front.hub.forget_root("work") is not None
    gone = front.get(f"/_/doc?doc={DOC}")
    assert gone.status == 404 and gone.json()["root"] is None
    assert front.hub.roots.address(later / "plan.md") == DOC
    got = front.get(f"/_/doc?doc={DOC}").json()
    assert got["hash"] == md_hash(PLAN) and got["root"] == front.hub.roots.get("work").id != first


def test_the_changes_a_member_is_sent_do_not_name_the_threads_told(told, front, browser, plan):
    mine = front.get(f"/_/live?doc={DOC}").stream
    own = browser.get(f"/_/live?doc={DOC}").stream
    live = front.hub.entry(DOC).live
    plan.write_text(text(plan).replace("about pears", "about plums"), encoding="utf-8")
    live.refresh()
    live.reply_as("c1", "Plums.", "Claude", "answer", "ask-done")
    for stream, telling in ((own, ["c1"]), (mine, [])):
        got = [e for e in stream.drain() if e[0] != "hello"]
        assert [n for n, _ in got] == ["changed", "ask-done"]
        assert [d["telling"] for _, d in got] == [telling, telling]


def test_a_members_index_stream_names_only_their_documents(mine, other):
    sub = mine.get("/_/live").stream
    mine.hub.index_bus.publish("status", Status({"doc": "other/notes.md", "root": "other", "dot": "red",
                                                 "open": 1, "changed": 1.0}, files=True))
    mine.hub.index_bus.publish("status", Status({"doc": DOC, "root": "work", "dot": "red", "open": 1,
                                                 "changed": 1.0}, files=True))
    mine.hub.rotate()
    assert [e for e in sub.drain() if e[0] != "hello"] == [("status", {"doc": DOC, "root": "work"})]


def statuses(stream):
    return [d for n, d in stream.drain() if n == "status"]


def test_a_members_index_stream_is_not_told_when_the_hub_accounts_ask_starts(front, browser, plan):
    plan.write_text(with_threads(thread("c1", "Bea", status="resolved")), encoding="utf-8")
    mine, own = front.get("/_/live").stream, browser.get("/_/live").stream
    _, release = hold_job(front.hub, DOC)
    try:
        front.hub.index.touch(DOC)
        assert [d["dot"] for d in statuses(own)] == ["orange"]
        assert statuses(mine) == []
        plan.write_text(text(plan) + "\nA third paragraph.\n", encoding="utf-8")    # the file moves
        front.hub.index.touch(DOC)
        assert len(statuses(own)) == 1 and statuses(mine) == [{"doc": DOC, "root": "work"}]
    finally:
        release.set()


def test_a_members_index_stream_is_not_told_when_the_hubs_person_reads_a_thread(front, browser, plan):
    plan.write_text(with_threads(thread("c1", "Bea")), encoding="utf-8")
    mine, own = front.get("/_/live").stream, browser.get("/_/live").stream
    assert browser.post("/_/seen", {"doc": DOC, "id": "c1", "count": 1}).status == 200
    assert [d["dot"] for d in statuses(own)] == ["blue"]
    assert statuses(mine) == []


def test_a_member_of_a_git_root_is_told_when_a_document_goes_with_its_folder(front, work):
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    doc = work / "a" / "x.md"
    doc.parent.mkdir()
    doc.write_text(PLAN, encoding="utf-8")
    front.hub.roots.for_document(doc)
    mine = front.get("/_/live").stream
    doc.unlink()
    doc.parent.rmdir()
    front.hub.index.touch("work/a/x.md")
    assert statuses(mine) == [{"doc": "work/a/x.md", "root": "work"}]


@pytest.fixture
def served(proxy_served, monkeypatch):
    """The hub on a real port and a real proxy socket, with streams of the socket ending after 1 s."""
    monkeypatch.setattr(proxy, "STREAM_SECONDS", 1.0)
    return proxy_served


def test_a_stream_of_the_proxy_socket_ends_after_its_time_and_one_of_the_port_does_not(served):
    hub = served
    c = UnixHTTP(hub.proxy.socket)
    c.request("GET", f"/_/live?doc={DOC}", headers={"Host": hub.proxy.host, "X-Sheaf-Member": BEA})
    r = c.getresponse()
    t0 = time.monotonic()
    assert r.status == 200
    r.read()                                     # to the end of the stream
    assert 0.9 <= time.monotonic() - t0 < 5
    port = http.client.HTTPConnection("127.0.0.1", hub.port, timeout=10)
    port.request("GET", f"/_/live?doc={DOC}",
                 headers={"Cookie": f"{hub.auth.cookie_name}={hub.auth.cookie_value()}"})
    pr = port.getresponse()
    pr.fp.raw._sock.settimeout(2.5)
    with pytest.raises((TimeoutError, socket.timeout)):
        pr.read()                                # still open after 2.5 s
    port.close()
