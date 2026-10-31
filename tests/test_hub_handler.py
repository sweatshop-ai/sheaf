"""The hub's request handler, in memory: no socket, no subprocess, no thread (SPEC 8.5, 18).

Every route of a hub for one root and every 4xx it answers. The security matrix (Host, Origin,
cookie, key, CSP, traversal) is in test_hub_security.py."""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

import sheafmd.comments as rdc
from helpers import GIT_FAILS, PLAN, git_dirs_in, git_fails, page_meta, writes_from_outside
from sheafmd import diagnostics, paths
from sheafmd.blocks import split_md_blocks
from sheafmd.hub import live, state
from sheafmd.hub.core import Hub
from sheafmd.hub.handler import NO_AGENT, Handler
from sheafmd.source import md_hash, update_file

DOC = "work/plan.md"
URL = "/work/plan.md"


def block_of(text, prefix):
    return next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith(prefix))


def edit(text, prefix, html):
    return [{"i": block_of(text, prefix), "html": html}]


def rows(kind=None):
    got = diagnostics.read()
    return [r for r in got if kind is None or r["kind"] == kind]


# ── the page ─────────────────────────────────────────────────────────────────

def test_a_document_is_served_as_a_page_with_its_meta(browser, plan):
    r = browser.get(URL)
    assert r.status == 200 and r.headers["Content-Type"] == "text/html; charset=utf-8"
    html = r.text
    assert "<h1" in html and "about apples" in html
    meta = page_meta(html)
    assert meta["doc"] == DOC and meta["name"] == "plan.md"
    assert meta["hash"] == md_hash(PLAN) and meta["edit"] is True
    assert meta["me"] == "Ada" and meta["boot"] == browser.hub.boot
    assert meta["version"] == browser.hub.version and meta["service"] is False
    assert meta["agent"] is None and meta["can"] == []
    assert meta["seen"] == {} and meta["comments"] == [] and meta["malformed"] == []
    assert "token" not in meta


def test_the_page_script_carries_the_nonce_of_its_own_csp(browser, plan):
    r = browser.get(URL)
    nonce = r.headers["Content-Security-Policy"].split("script-src 'nonce-")[1].split("'")[0]
    assert f'<script nonce="{nonce}">' in r.text
    assert r.text.count("<script") == 2          # the meta block and the page script, nothing else
    assert browser.get(URL).headers["Content-Security-Policy"] != r.headers["Content-Security-Policy"]


def test_a_url_with_encoded_characters_finds_its_document(browser, work):
    f = work / "a b" / "ünï #1.md"
    f.parent.mkdir()
    f.write_text("# T\n\nBody.\n", encoding="utf-8")
    r = browser.post("/_/render", {"path": str(f)}, key=True, cookie=False)
    assert r.status == 200
    assert r.json()["doc"] == "a-b/ünï #1.md"
    assert r.json()["url"] == f"http://127.0.0.1:{browser.hub.port}/a-b/%C3%BCn%C3%AF%20%231.md"
    assert browser.get("/a-b/%C3%BCn%C3%AF%20%231.md").status == 200


def test_a_document_that_was_never_rendered_opens_with_the_defaults(browser, plan):
    assert page_meta(browser.get(URL).text)["name"] == "plan.md"
    assert browser.hub.docs.get(DOC) == {}


def test_a_document_that_does_not_exist_is_404(browser, plan):
    plan.unlink()
    r = browser.get(URL)
    assert r.status == 404 and r.json() == {"ok": False, "error": "no such document"}


def test_the_index_is_a_page_and_a_root_is_a_page_of_its_own(browser, plan):
    assert browser.get("/").status == 200
    assert browser.get("/work/").status == 200
    assert browser.get("/nothere/").status == 404


# ── a document in a git directory is no document of the root around it (8.2) ─

def answers(browser, doc):
    """What each route of a document says to the person about `doc`, by route: (status, body)."""
    h = md_hash(PLAN)
    got = {"page": browser.get("/" + doc), "doc": browser.get(f"/_/doc?doc={doc}"),
           "live": browser.get(f"/_/live?doc={doc}"),
           "save": browser.post("/_/save", {"doc": doc, "hash": h, "edits": []}),
           "comment": browser.post("/_/comment", {"doc": doc, "op": "add", "hash": h, "block": 0,
                                                  "quote": "Second", "body": "Why?"}),
           "ask": browser.post("/_/ask", {"doc": doc, "id": "c1"}),
           "tell": browser.post("/_/tell", {"doc": doc, "id": "c1"}),
           "cancel": browser.post("/_/cancel", {"doc": doc, "id": "c1", "what": "ask"}),
           "seen": browser.post("/_/seen", {"doc": doc, "id": "c1", "count": 1}),
           "export": browser.post("/_/export", {"doc": doc, "kind": "html"})}
    return {route: (r.status, r.body) for route, r in got.items()}


@pytest.mark.parametrize("how", ["runs", *GIT_FAILS])
@pytest.mark.parametrize("inside, own", [("sub/.git/x.md", "git/x.md"), ("sub/keep.git/x.md", "keep.git/x.md")])
def test_a_document_in_a_git_directory_answers_the_person_as_one_that_does_not_exist(browser, plan, work, monkeypatch,
                                                                                   tmp_path, how, inside, own):
    """As the door (12) and a member (9.9) are answered: a Tell from such a page would name an address the door
    refuses. The file is its own folder's root's (rule 3), and served there."""
    git_dirs_in(work, PLAN)
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)
    said = answers(browser, f"work/{inside}")
    assert said == answers(browser, f"work/{inside.replace('x.md', 'gone.md')}")
    assert said.pop("cancel")[0] == 200            # asks nothing of the file: a quiet ok for any address
    assert {status for status, _ in said.values()} == {404}
    [root] = [r for r in browser.get("/_/index.json").json()["roots"] if r["name"] == "work"]
    assert sorted(d["doc"] for d in root["docs"]) == [DOC, "work/sub/b.md"]
    assert browser.hub.roots.address(work / inside) == own
    assert browser.get("/" + own).status == 200


@pytest.mark.parametrize("how", ["runs", *GIT_FAILS])
def test_a_link_into_a_git_directory_is_no_document_of_the_root_either(browser, plan, work, monkeypatch, tmp_path,
                                                                     how):
    """A link is judged where it points, as the door and a member's index judge it."""
    git_dirs_in(work, PLAN)
    (work / "link.md").symlink_to(work / "sub" / "keep.git" / "x.md")
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)
    assert answers(browser, "work/link.md") == answers(browser, "work/gone.md")
    [root] = [r for r in browser.get("/_/index.json").json()["roots"] if r["name"] == "work"]
    assert sorted(d["doc"] for d in root["docs"]) == [DOC, "work/sub/b.md"]


def test_the_routes_of_a_document_ask_git_nothing_where_no_folder_is_shaped_like_a_git_directory(browser, plan,
                                                                                                monkeypatch):
    """Every request of a page asks whether its file lies in a git directory (8.3); for an ordinary folder that is
    a look at the path, not a run of git."""
    assert browser.get(URL).status == 200
    asked, run = [], subprocess.run

    def spy(argv, *args, **kw):
        if "rev-parse" in argv:
            asked.append(argv)
        return run(argv, *args, **kw)
    monkeypatch.setattr(subprocess, "run", spy)
    assert {status for status, _ in list(answers(browser, DOC).values())[:2]} == {200}
    assert asked == []


@pytest.mark.parametrize("how", ["runs", *GIT_FAILS])
def test_the_work_tree_of_a_repo_nested_in_a_root_is_served_to_the_person_as_before(browser, plan, work, monkeypatch,
                                                                                  tmp_path, how):
    git_dirs_in(work, PLAN)
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)
    assert browser.get("/work/sub/b.md").status == browser.get(URL).status == 200
    assert browser.get("/_/doc?doc=work/sub/b.md").status == 200


# ── /_/doc ───────────────────────────────────────────────────────────────────

def test_doc_gives_what_a_page_needs_on_load(browser, plan):
    browser.get(URL)
    got = browser.get(f"/_/doc?doc={DOC}").json()
    assert got == {"ok": True, "hash": md_hash(PLAN), "telling": [], "comments": [],
                   "malformed": [], "seen": {}, "asking": [], "question": "", "target": None,
                   "capabilities": [], "lines": {"ask": NO_AGENT, "tell": NO_AGENT},
                   "root": browser.hub.roots.get("work").id, "rids": []}


def test_doc_names_the_request_ids_the_document_took(browser, plan):
    browser.get(URL)
    browser.hub.entry(DOC).live.comment("add", {"block": 0, "start": 0, "end": 4, "quote": "Plan",
                                                 "body": "Why?"}, "", rid="r0123456789abcdef")
    assert browser.get(f"/_/doc?doc={DOC}").json()["rids"] == ["r0123456789abcdef"]


def test_doc_answers_the_key_too(browser, plan):
    assert browser.get(f"/_/doc?doc={DOC}", cookie=False, key=True).status == 200


@pytest.mark.parametrize("doc", ["", "work/missing.md", "nowhere/plan.md", "work/../x.md",
                                 "work/plan.txt", "../plan.md", "work"])
def test_doc_of_a_document_that_is_not_there_is_404(browser, plan, doc):
    assert browser.get("/_/doc?doc=" + doc).status == 404


def test_doc_without_a_doc_is_400(browser, plan):
    assert browser.get("/_/doc").status == 400


# ── /_/save ──────────────────────────────────────────────────────────────────

def test_a_save_without_the_hash_it_was_made_against_is_400_and_touches_nothing(browser, plan):
    # Block numbers mean something only against one version of the file (SPEC 8.5: `{doc, hash, edits}`).
    r = browser.post("/_/save", {"doc": DOC, "edits": edit(PLAN, "Second paragraph", "<p>Second, saved.</p>")})
    assert r.status == 400 and "hash" in r.json()["error"]
    assert plan.read_text(encoding="utf-8") == PLAN


def test_a_save_lands_in_the_md(browser, plan):
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN),
                                 "edits": edit(PLAN, "Second paragraph", "<p>Second, saved.</p>")})
    got = r.json()
    text = plan.read_text(encoding="utf-8")
    assert r.status == 200 and got["ok"] is True and got["changed"] and got["merged"] is False
    assert "Second, saved." in text and "about pears" not in text
    assert got["hash"] == md_hash(text) and got["conflicts"] == [] and got["remap"] is False
    assert page_meta(browser.get(URL).text)["hash"] == got["hash"]


def test_a_saves_answer_names_the_buttons_of_the_text_it_wrote(browser, plan):
    # The page draws its action buttons from the text it holds (10.11): a save that adds an action, here a list
    # item rewritten as a box, hands the page the buttons it numbers by from now on.
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN),
                                 "edits": edit(PLAN, "- one", '<ul><li><input type="checkbox">Run it</li></ul>')})
    got = r.json()
    assert r.status == 200 and "- [ ] Run it" in plan.read_text(encoding="utf-8")
    assert [(a["label"], a["n"], a["toggle"], a["box"]) for a in got["actions"]] == [
        ("Run it", 0, False, [block_of(PLAN, "- one"), 0])]


@pytest.mark.parametrize("swap", [True, False], ids=["swapped", "control"])
def test_a_save_whose_sibling_is_swapped_for_a_link_is_not_acknowledged(browser, plan, work, tmp_path, monkeypatch,
                                                                       swap):
    """A user who can write the folder swaps `.plan.md.sheaf-tmp` for a link to a file outside it
    while the save writes (the fsync between the open and the replace). The save used to answer 200
    with the new hash while the document had become the link and the person's text was in a file
    nobody could find. It fails, the page keeps its edits (it mirrors them when a save fails), and
    the document is left as it was."""
    victim = tmp_path / "note.txt"
    victim.write_text("personal\n", encoding="utf-8")
    sibling = work / ".plan.md.sheaf-tmp"
    real_fsync = os.fsync

    def plant(fd):
        if swap and os.path.lexists(sibling) and not sibling.is_symlink():
            os.unlink(sibling)
            sibling.symlink_to(victim)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", plant)
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN),
                                 "edits": edit(PLAN, "Second paragraph", "<p>Second, saved.</p>")})
    assert not plan.is_symlink() and victim.read_text(encoding="utf-8") == "personal\n"
    if swap:
        assert r.status == 500 and r.json()["ok"] is False
        assert plan.read_text(encoding="utf-8") == PLAN
        assert rows("request-failed")[0]["endpoint"] == "/_/save"
    else:
        assert r.status == 200 and r.json()["ok"] is True
        assert "Second, saved." in plan.read_text(encoding="utf-8")
    assert not sibling.exists() and not sibling.is_symlink()


def test_a_save_against_an_older_version_is_merged(browser, plan):
    browser.get(URL)
    update_file(plan, lambda t: t.replace("about apples", "about apples, from outside"))
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN),
                                 "edits": edit(PLAN, "Second paragraph", "<p>Second, saved.</p>")})
    got, text = r.json(), plan.read_text(encoding="utf-8")
    assert r.status == 200 and got["merged"] is True and got["conflicts"] == []
    assert "from outside" in text and "Second, saved." in text
    assert any(x["kind"] == "save-merged" and x["source"] == "hub" for x in rows())


def test_a_save_against_a_version_only_on_disk_merges_after_a_restart(browser, plan, work):
    browser.get(URL)
    update_file(plan, lambda t: t.replace("about apples", "about apples, from outside"))
    browser.hub.tick()                                       # the open page is told (no tab: nothing)
    fresh = Hub(port=27419, key=paths.ensure_key(), started_by="test")      # the hub restarts
    again = type(browser)(fresh, Handler(fresh))
    r = again.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN),
                               "edits": edit(PLAN, "Second paragraph", "<p>Second, saved.</p>")})
    assert r.status == 200 and r.json()["merged"] is True
    assert "from outside" in plan.read_text(encoding="utf-8")


def test_a_save_against_a_version_nobody_knows_is_409(browser, plan):
    browser.get(URL)
    update_file(plan, lambda t: t + "\nMore.\n")
    r = browser.post("/_/save", {"doc": DOC, "hash": "0" * 16,
                                 "edits": edit(PLAN, "Second paragraph", "<p>X</p>")})
    assert r.status == 409
    assert r.json() == {"ok": False, "error": "the .md changed on disk and this page's version "
                        "is no longer known to the hub. Copy your edit, then reload"}
    assert "X" not in plan.read_text(encoding="utf-8")


def test_a_save_with_a_path_as_its_hash_never_touches_the_disk(browser, plan):
    browser.get(URL)
    update_file(plan, lambda t: t + "\nMore.\n")
    r = browser.post("/_/save", {"doc": DOC, "hash": "../../hub.key",
                                 "edits": edit(PLAN, "Second paragraph", "<p>X</p>")})
    assert r.status == 409


# More writes than the hub keeps versions of, in memory and on disk (SPEC 7.4).
MANY = max(live.VERSIONS, state.VERSIONS_KEPT) + 1


@pytest.mark.parametrize("held", ["served", "merged"])
def test_a_page_that_pinned_its_version_saves_after_more_writes_than_the_hub_keeps(browser, plan, held):
    """A form holds the reload a change from outside needs, so the page keeps the hash of the text on
    screen: the one it was served at, or the base of a save the hub merged, until that save's reload. It
    tells the hub so (`/_/pin`), and its save is merged however much was written meanwhile."""
    browser.get(URL)
    writes_from_outside(plan, browser.hub.entry(DOC).live, 1)
    if held == "merged":
        r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN),
                                     "edits": edit(PLAN, "Second paragraph", "<p>Second, saved.</p>")})
        assert r.json()["merged"] is True
    pinned = browser.post("/_/pin", {"doc": DOC, "hash": md_hash(PLAN)})
    writes_from_outside(plan, browser.hub.entry(DOC).live, MANY)
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN),
                                 "edits": edit(PLAN, "First paragraph", "<p>First, saved.</p>")})
    assert r.status == 200, r.json()
    text = plan.read_text(encoding="utf-8")
    assert r.json()["merged"] is True and "First, saved." in text and f"From outside {MANY - 1}." in text
    assert pinned.status == 200 and pinned.json() == {"ok": True}


@pytest.mark.parametrize("writes, status", [(MANY, 409), (min(live.VERSIONS, state.VERSIONS_KEPT) - 1, 200)])
def test_a_page_that_pinned_nothing_saves_after_fewer_writes_than_the_hub_keeps_and_not_after_more(
        browser, plan, writes, status):
    """The bound holds for a version no page pinned, as before."""
    browser.get(URL)
    writes_from_outside(plan, browser.hub.entry(DOC).live, writes)
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN),
                                 "edits": edit(PLAN, "First paragraph", "<p>First, saved.</p>")})
    assert r.status == status, r.json()
    assert ("First, saved." in plan.read_text(encoding="utf-8")) is (status == 200)


def test_a_reply_from_a_page_that_pinned_its_version_is_written_after_more_writes_than_the_hub_keeps(browser, plan):
    """The reply sent from the very form that held the reload."""
    blk, s, e = rdc.find_quote(PLAN, "Second paragraph")
    r = browser.post("/_/comment", {"doc": DOC, "op": "add", "hash": md_hash(PLAN), "block": blk, "start": s,
                                    "end": e, "quote": "Second paragraph", "body": "Why pears?"})
    held = r.json()["hash"]
    writes_from_outside(plan, browser.hub.entry(DOC).live, 1)
    pinned = browser.post("/_/pin", {"doc": DOC, "hash": held})
    writes_from_outside(plan, browser.hub.entry(DOC).live, MANY)
    r = browser.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "hash": held, "body": "Because."})
    assert r.status == 200, r.json()
    assert [x.text for x in rdc.parse(plan.read_text(encoding="utf-8")).by_id("c1").replies] == ["Because."]
    assert pinned.status == 200


@pytest.mark.parametrize("body, status", [
    ({}, 400), ({"hash": 12}, 400), ({"hash": ""}, 400),
    ({"hash": "0" * 16}, 409), ({"hash": "../../hub.key"}, 409),
    ({"hash": md_hash(PLAN), "doc": "work/nothing.md"}, 404)])
def test_a_pin_names_a_version_the_document_knows(browser, plan, body, status):
    browser.get(URL)
    r = browser.post("/_/pin", {"doc": DOC, **body})
    assert r.status == status and r.json()["ok"] is False
    if status == 409:
        assert r.json()["error"] == "the .md changed on disk and this page's version is no longer known to the hub"
    assert not (paths.state_dir() / "versions" / state.doc_key(DOC) / "pins").exists()


def test_an_edit_that_cannot_convert_is_skipped_with_its_reason_and_writes_nothing(browser, plan):
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN),
                                 "edits": edit(PLAN, "Second paragraph", "<p><svg></svg></p>")})
    got = r.json()
    assert r.status == 200 and got["changed"] == [] and "chart" in got["skipped"][0][1]
    assert plan.read_text(encoding="utf-8") == PLAN


def test_an_edit_of_a_block_that_is_not_there_is_skipped_not_refused(browser, plan):
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN),
                                 "edits": [{"i": 999, "html": "<p>X</p>"}]})
    assert r.status == 200 and r.json()["skipped"] == [[999, "no such block"]]
    assert r.json()["changed"] == [] and plan.read_text(encoding="utf-8") == PLAN


@pytest.mark.parametrize("body", [
    {"hash": "x", "edits": []}, {"doc": 5, "hash": "x", "edits": []}, {"doc": DOC, "hash": 5,
                                                                     "edits": []},
    {"doc": DOC, "hash": "x", "edits": "no"}, {"doc": DOC, "hash": "x", "edits": [5]},
    {"doc": DOC, "hash": "x", "edits": [{"i": "a", "html": "x"}]},
    {"doc": DOC, "hash": "x", "edits": [{"i": 1}]},
    {"doc": DOC, "hash": "x", "edits": [{"i": True, "html": "x"}]},
    {"doc": DOC, "hash": "x", "edits": [{"i": 1, "html": 7}]},
    {"doc": DOC, "hash": "x", "edits": [{"i": 1, "html": "x", "saved": 7}]}])
def test_a_save_with_a_body_of_the_wrong_shape_is_400(browser, plan, body):
    r = browser.post("/_/save", body)
    assert r.status == 400 and r.json()["ok"] is False


@pytest.mark.parametrize("rid", [7, "short", "not a request id at all", ""])
def test_a_save_with_a_request_id_that_is_not_one_is_400_and_touches_nothing(browser, plan, rid):
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN), "rid": rid,
                                 "edits": edit(PLAN, "Second paragraph", "<p>Second, saved.</p>")})
    assert r.status == 400 and "request id" in r.json()["error"]
    assert plan.read_text(encoding="utf-8") == PLAN


# A save the page gave up after 120 s and sends again with its request id is written once (SPEC 8.5).
def test_a_save_sent_again_with_its_request_id_is_written_once_and_says_so(browser, plan):
    body = {"doc": DOC, "hash": md_hash(PLAN), "rid": "s0123456789abcdef",
            "edits": edit(PLAN, "Second paragraph", "<p>Second, saved.</p>")}
    first = browser.post("/_/save", body).json()
    once = plan.read_text(encoding="utf-8")
    r = browser.post("/_/save", body)
    assert r.status == 200 and r.json() == {**first, "again": True} and "again" not in first
    assert plan.read_text(encoding="utf-8") == once
    assert browser.get(f"/_/doc?doc={DOC}").json()["rids"] == ["s0123456789abcdef"]


def test_a_save_without_a_request_id_still_lands_and_is_not_remembered(browser, plan):
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN),
                                 "edits": edit(PLAN, "Second paragraph", "<p>Second, saved.</p>")})
    assert r.status == 200 and "again" not in r.json()
    assert browser.get(f"/_/doc?doc={DOC}").json()["rids"] == []


@pytest.mark.parametrize("raw", [b"not json", b"[1]", b'"s"', b"5", b"null", b"\xff\xfe"])
def test_a_body_that_is_not_a_json_object_is_400(browser, plan, raw):
    for route in ("/_/save", "/_/comment", "/_/seen", "/_/export", "/_/diag", "/_/ask"):
        assert browser.post(route, raw=raw).status == 400, route


def test_a_body_over_the_limit_is_413(browser, plan):
    big = b'{"doc": "' + b"x" * (9 * 1024 * 1024) + b'"}'
    assert browser.post("/_/save", raw=big).status == 413


def test_a_save_of_a_document_that_is_not_there_is_404(browser, plan):
    r = browser.post("/_/save", {"doc": "work/none.md", "hash": "x", "edits": []})
    assert r.status == 404


# ── /_/comment ───────────────────────────────────────────────────────────────

def add(browser, quote="Second paragraph", body="Why pears?", **extra):
    text = Path(browser.hub.roots.resolve(DOC)).read_text(encoding="utf-8")
    blk, s, e = rdc.find_quote(text, quote)
    return browser.post("/_/comment", {"doc": DOC, "op": "add", "hash": md_hash(text),
                                       "block": blk, "start": s, "end": e, "quote": quote,
                                       "body": body, **extra})


def test_a_comment_lands_in_the_md_signed_by_the_reader(browser, plan):
    r = add(browser)
    got = r.json()
    assert r.status == 200 and got["ok"] is True and got["id"] == "c1" and got["textSame"] is True
    c = rdc.parse(plan.read_text(encoding="utf-8")).by_id("c1")
    assert c.by == "Ada" and c.body == "Why pears?" and c.quote == "Second paragraph"
    assert got["comments"][0]["id"] == "c1" and got["hash"] == md_hash(plan.read_text())
    assert page_meta(browser.get(URL).text)["comments"][0]["body"] == "Why pears?"


def test_a_reply_a_status_an_edit_and_a_delete_find_their_thread(browser, plan):
    add(browser)
    h = lambda: md_hash(plan.read_text(encoding="utf-8"))          # noqa: E731
    r = browser.post("/_/comment", {"doc": DOC, "op": "reply", "hash": h(), "id": "c1",
                                    "body": "Because.", "resolve": True})
    assert r.status == 200
    c = rdc.parse(plan.read_text()).by_id("c1")
    assert c.replies[0].text == "Because." and c.replies[0].by == "Ada" and c.status == "resolved"
    r = browser.post("/_/comment", {"doc": DOC, "op": "status", "hash": h(), "id": "c1",
                                    "status": "open"})
    assert r.status == 200 and rdc.parse(plan.read_text()).by_id("c1").status == "open"
    r = browser.post("/_/comment", {"doc": DOC, "op": "edit", "hash": h(), "id": "c1",
                                    "body": "Why pears, really?"})
    assert r.status == 200 and rdc.parse(plan.read_text()).by_id("c1").body == "Why pears, really?"
    r = browser.post("/_/comment", {"doc": DOC, "op": "delete", "hash": h(), "id": "c1"})
    assert r.status == 200 and rdc.parse(plan.read_text()).comments == []


def test_a_comment_follows_its_paragraph_after_an_outside_write(browser, plan):
    browser.get(URL)
    old = plan.read_text(encoding="utf-8")
    update_file(plan, lambda t: "# Plan\n\nInserted above.\n\n" + t.split("\n\n", 1)[1])
    blk, s, e = rdc.find_quote(old, "Second paragraph")
    r = browser.post("/_/comment", {"doc": DOC, "op": "add", "hash": md_hash(old), "block": blk,
                                    "start": s, "end": e, "quote": "Second paragraph",
                                    "body": "Moved?"})
    assert r.status == 200 and r.json()["textSame"] is False
    assert rdc.parse(plan.read_text()).by_id("c1").quote == "Second paragraph"


def test_a_comment_on_a_paragraph_that_changed_is_409(browser, plan):
    browser.get(URL)
    old = plan.read_text(encoding="utf-8")
    update_file(plan, lambda t: t.replace("First paragraph, about apples", "First, changed"))
    blk, s, e = rdc.find_quote(old, "First paragraph")
    r = browser.post("/_/comment", {"doc": DOC, "op": "add", "hash": md_hash(old), "block": blk,
                                    "start": s, "end": e, "quote": "First paragraph",
                                    "body": "Gone?"})
    assert r.status == 409 and "select the text again" in r.json()["error"]
    assert r.json()["code"] == "select-again"
    assert rdc.parse(plan.read_text()).comments == []


@pytest.mark.parametrize("body", [
    {"op": "frobnicate"}, {"op": "add"},
    {"op": "add", "block": "a", "start": 0, "end": 1}, {"op": "add", "block": None,
                                                        "start": 0, "end": 1},
    {"op": "status", "id": "c1", "status": "weird"}, {}, {"op": 7},
    {"op": "reply", "id": "c1", "body": "x", "rid": 7},
    {"op": "reply", "id": "c1", "body": "x", "rid": "short"},
    {"op": "reply", "id": "c1", "body": "x", "rid": "not a request id at all"}])
def test_a_comment_request_that_makes_no_sense_is_400(browser, plan, body):
    add(browser)
    r = browser.post("/_/comment", {"doc": DOC, "hash": md_hash(plan.read_text()), **body})
    assert r.status == 400 and r.json()["ok"] is False


# A thread deleted elsewhere while a page's reply, edit, status or delete of it was out: the answer says it is
# gone, so the page gives the form back as text to copy before it has heard of the deletion.
@pytest.mark.parametrize("body", [{"op": "reply", "id": "c9", "body": "x"}, {"op": "edit", "id": "c9", "body": "x"},
                                  {"op": "status", "id": "c9", "status": "resolved"}, {"op": "delete", "id": "c9"}])
def test_a_comment_request_on_a_thread_that_is_not_there_is_410(browser, plan, body):
    add(browser)
    before = plan.read_text()
    r = browser.post("/_/comment", {"doc": DOC, "hash": md_hash(before), **body})
    assert r.status == 410 and r.json() == {"ok": False, "error": "no comment c9 in this document"}
    assert plan.read_text() == before


def test_a_save_whose_html_holds_a_lone_surrogate_is_400_and_writes_nothing(browser, plan):
    """A browser's JSON can carry half of an emoji (JSON.stringify writes it as \\ud83d); the file
    cannot hold it. Nothing was written either way, but the answer was a 500 and a failure row."""
    before = plan.read_text()
    i = next(i for i, b in enumerate(split_md_blocks(before)) if b.content.startswith("Second"))
    raw = ('{"doc": "work/plan.md", "hash": "%s", "edits": [{"i": %d, "html": "<p>half \\ud83d</p>"}]}'
           % (md_hash(before), i)).encode()
    r = browser.post("/_/save", raw=raw)
    assert r.status == 400 and r.json()["ok"] is False
    assert plan.read_text() == before and rows("request-failed") == []


@pytest.mark.parametrize("field", ["block", "start", "end"])
@pytest.mark.parametrize("value", ["1e400", "-1e400", "1.5", "true", '"2"', "null", "[1]"])
def test_a_comment_add_with_a_position_that_is_not_a_whole_number_is_400_and_writes_nothing(
        browser, plan, field, value):
    """`"block": 1e400` is a float that `int()` cannot take (OverflowError): a 500 and a
    `request-failed` row until the fields were checked by type, as a save's `i` is."""
    before = plan.read_text()
    fields = {"block": "1", "start": "0", "end": "5"}
    fields[field] = value
    raw = ('{"doc": "work/plan.md", "op": "add", "hash": "%s", "body": "x", "quote": "x", %s}' % (
        md_hash(before), ", ".join(f'"{k}": {v}' for k, v in fields.items()))).encode()
    r = browser.post("/_/comment", raw=raw)
    assert r.status == 400 and r.json()["ok"] is False
    assert plan.read_text() == before
    assert rows("request-failed") == [], "a refusal is not a failure of the hub"


def test_ask_and_tell_on_a_comment_say_there_is_no_agent_and_still_write_it(browser, plan):
    got = add(browser, ask=True, tell=True).json()
    assert got["ok"] is True and got["askError"] == NO_AGENT and got["tellError"] == NO_AGENT
    assert got["telling"] == [] and rdc.parse(plan.read_text()).by_id("c1") is not None


# ── ask, tell, cancel: no agent in this build ────────────────────────────────

def test_ask_and_tell_are_409_without_an_agent(browser, plan):
    add(browser)
    for route in ("/_/ask", "/_/tell"):
        r = browser.post(route, {"doc": DOC, "id": "c1"})
        assert r.status == 409 and r.json() == {"ok": False, "error": NO_AGENT}


def test_cancel_with_nothing_running_is_a_quiet_ok(browser, plan):
    for what in ("ask", "tell"):
        assert browser.post("/_/cancel", {"doc": DOC, "id": "c1", "what": what}).json() == {"ok": True}


def test_cancel_of_neither_is_400(browser, plan):
    assert browser.post("/_/cancel", {"doc": DOC, "id": "c1", "what": "both"}).status == 400


# ── /_/seen ──────────────────────────────────────────────────────────────────

def test_seen_is_kept_by_the_hub_and_shows_on_the_next_load(browser, plan):
    assert browser.post("/_/seen", {"doc": DOC, "id": "c1", "count": 2}).json() == {"ok": True}
    assert page_meta(browser.get(URL).text)["seen"] == {"c1": 2}
    assert browser.get(f"/_/doc?doc={DOC}").json()["seen"] == {"c1": 2}
    assert state.Seen().get(DOC) == {"c1": 2}


@pytest.mark.parametrize("body", [{"count": 1}, {"id": 3, "count": 1},
                                  {"id": "c1", "count": "1"}, {"id": "c1", "count": -1},
                                  {"id": "c1", "count": True}, {"id": "c1", "count": 1.5},
                                  {"id": "", "count": 1}, {"id": "x" * 100, "count": 1},
                                  {"id": "c1", "count": 10 ** 9}])
def test_seen_of_nonsense_is_400(browser, plan, body):
    assert browser.post("/_/seen", {"doc": DOC, **body}).status == 400
    assert state.Seen().get(DOC) == {}


# ── /_/export ────────────────────────────────────────────────────────────────

def test_the_html_export_is_the_share_copy_as_an_attachment(browser, plan):
    add(browser, body="PRIVATE NOTE")
    r = browser.post("/_/export", {"doc": DOC, "kind": "html"})
    assert r.status == 200 and r.headers["Content-Type"] == "text/html; charset=utf-8"
    assert r.headers["Content-Disposition"].startswith('attachment; filename="plan.html"')
    assert "about pears" in r.text and "PRIVATE NOTE" not in r.text
    assert "<script" not in r.text and "rd-comment" not in r.text and "sheaf-comment" not in r.text
    assert "Content-Security-Policy" in r.headers


def test_the_export_filename_of_an_odd_stem_is_safe(browser, work):
    f = work / 'a"b\r\nc ü.md'
    f.write_text("# T\n\nBody.\n", encoding="utf-8")
    r = browser.post("/_/export", {"doc": browser.hub.roots.address(f), "kind": "html"})
    disp = r.headers["Content-Disposition"]
    assert "\r" not in disp and "\n" not in disp and disp.count('"') == 2
    assert "filename*=UTF-8''" in disp


def test_the_pdf_export_is_made_from_the_share_copy(browser, plan, monkeypatch):
    made = {}

    def fake(html, out):
        made["html"] = html
        Path(out).write_bytes(b"%PDF-fake")
    monkeypatch.setattr("sheafmd.pdf.write_pdf", fake)
    r = browser.post("/_/export", {"doc": DOC, "kind": "pdf"})
    assert r.status == 200 and r.body == b"%PDF-fake" and r.headers["Content-Type"] == "application/pdf"
    assert r.headers["Content-Disposition"].startswith('attachment; filename="plan.pdf"')
    assert "<script" not in made["html"]


def test_a_pdf_that_cannot_be_made_is_503_with_the_reason_in_one_line(browser, plan, monkeypatch):
    from sheafmd.pdf import PdfError

    def fail(html, out):
        raise PdfError("Chrome is not installed.\nsudo apt install google-chrome-stable")
    monkeypatch.setattr("sheafmd.pdf.write_pdf", fail)
    r = browser.post("/_/export", {"doc": DOC, "kind": "pdf"})
    assert r.status == 503
    assert r.json() == {"ok": False, "error": "Chrome is not installed. sudo apt install google-chrome-stable"}


def test_an_export_of_a_document_whose_comment_never_closes_says_why(browser, plan):
    update_file(plan, lambda t: t + "\n<!-- sheaf-comment id=c1 by=\"A\" at=2026-01-01T00:00 status=open quote=\"x\"\nnever closed\n")
    r = browser.post("/_/export", {"doc": DOC, "kind": "html"})
    assert r.status == 409 and r.json()["ok"] is False and "line" in r.json()["error"]


@pytest.mark.parametrize("kind", ["", "docx", None, 7])
def test_an_export_of_another_kind_is_400(browser, plan, kind):
    assert browser.post("/_/export", {"doc": DOC, "kind": kind}).status == 400


# ── /_/diag ──────────────────────────────────────────────────────────────────

def test_a_row_from_the_page_goes_to_the_diagnostics_log(browser, plan):
    r = browser.post("/_/diag", {"doc": DOC, "kind": "toast", "error": "Save failed",
                                 "source": "hub", "pid": 1})
    assert r.status == 204 and r.body == b""
    row = rows("toast")[0]
    assert row["source"] == "page" and row["doc"] == DOC and row["error"] == "Save failed"
    assert row["pid"] != 1


def test_a_page_cannot_say_it_is_the_hub_or_write_huge_rows(browser, plan):
    browser.post("/_/diag", {"doc": DOC, "kind": "k" * 500, "error": "e" * 10000})
    row = rows()[-1]
    assert row["source"] == "page" and len(row["kind"]) <= 40 and len(row["error"]) <= 2001


def test_a_diag_row_needs_a_kind(browser, plan):
    assert browser.post("/_/diag", {"doc": DOC}).status == 400


# ── /_/render, /_/jobs, /_/stop (the CLI's, by key) ──────────────────────────

def test_render_registers_the_document_and_answers_with_its_url(browser, plan):
    r = browser.post("/_/render", {"path": str(plan), "settings": {"toc": "never", "title": "My plan"},
                                   "target": None}, cookie=False, key=True)
    assert r.status == 200
    got = r.json()
    assert (got["ok"], got["doc"], got["tabs"]) == (True, DOC, 0)
    assert got["url"] == f"http://127.0.0.1:{browser.hub.port}/work/plan.md"
    assert any("edit mode" in line for line in got["log"]) and got["warnings"] == []
    saved = state.Docs().get(DOC)
    assert saved["path"] == str(plan.resolve()) and saved["toc"] == "never" and saved["title"] == "My plan"
    assert "rendered" in saved
    assert "<title>My plan</title>" in browser.get(URL).text
    assert json.loads((paths.state_dir() / "roots.json").read_text())["work"]["path"] == str(plan.parent.resolve())


def test_a_for_setting_is_on_the_page_the_tabs_get_and_in_every_export(browser, plan, monkeypatch):
    plan.parent.joinpath(".sheaf.toml").write_text('for = "Acme"\n', encoding="utf-8")
    made = {}

    def fake(html, out):
        made["html"] = html
        Path(out).write_bytes(b"%PDF-fake")
    monkeypatch.setattr("sheafmd.pdf.write_pdf", fake)
    r = browser.post("/_/render", {"path": str(plan), "settings": {"by": "Grace", "for": "Globex"}},
                     cookie=False, key=True)
    assert r.status == 200
    assert state.Docs().get(DOC)["for"] == "Globex"
    page = browser.get(URL).text
    assert "Document prepared by Grace for Globex</p>" in page and "Acme" not in page
    shared = browser.post("/_/export", {"doc": DOC, "kind": "html"}).text
    assert "Document prepared by Grace for Globex</p>" in shared and "Acme" not in shared
    assert browser.post("/_/export", {"doc": DOC, "kind": "pdf"}).status == 200
    assert "Document prepared by Grace for Globex</p>" in made["html"]


def test_a_render_with_another_for_renders_the_page_again(browser, plan):
    settings = {"by": "Grace", "for": "Globex"}
    browser.post("/_/render", {"path": str(plan), "settings": settings}, cookie=False, key=True)
    assert "for Globex</p>" in browser.get(URL).text
    browser.post("/_/render", {"path": str(plan), "settings": {**settings, "for": "Initech"}},
                 cookie=False, key=True)
    page = browser.get(URL).text
    assert "for Initech</p>" in page and "Globex" not in page


@pytest.mark.parametrize("value", [5, True, ["Globex"], {"a": 1}])
def test_a_for_setting_that_is_not_text_is_400(browser, plan, value):
    r = browser.post("/_/render", {"path": str(plan), "settings": {"for": value}}, cookie=False, key=True)
    assert r.status == 400 and "for must be str" in r.text


def test_the_link_rule_warning_goes_to_the_first_render_only(browser, work):
    f = work / "links.md"
    f.write_text("# T\n\nSee example.com for more.\n", encoding="utf-8")
    body = {"path": str(f)}
    first = browser.post("/_/render", body, cookie=False, key=True).json()
    assert len(first["warnings"]) == 1 and "example.com" in first["warnings"][0]
    assert browser.post("/_/render", body, cookie=False, key=True).json()["warnings"] == []
    browser.get("/work/links.md")
    update_file(f, lambda t: t + "\nMore at other.org.\n")
    browser.hub.entry("work/links.md").live.refresh()
    assert browser.post("/_/render", body, cookie=False, key=True).json()["warnings"] == []


def test_a_render_with_other_settings_tells_the_open_tabs(browser, plan):
    browser.post("/_/render", {"path": str(plan), "settings": {"toc": "never"}}, cookie=False, key=True)
    tab = browser.get(f"/_/live?doc={DOC}").stream
    tab.drain()
    r = browser.post("/_/render", {"path": str(plan), "settings": {"title": "New title"}},
                     cookie=False, key=True)
    assert r.json()["tabs"] == 1
    (name, data), = tab.drain()
    assert name == "changed" and data["textSame"] is False and data["hash"] == md_hash(PLAN)
    assert "<title>New title</title>" in browser.get(URL).text


def test_a_render_with_the_same_settings_tells_nobody(browser, plan):
    body = {"path": str(plan), "settings": {"toc": "never"}}
    browser.post("/_/render", body, cookie=False, key=True)
    tab = browser.get(f"/_/live?doc={DOC}").stream
    tab.drain()
    browser.post("/_/render", body, cookie=False, key=True)
    assert tab.drain() == []


def test_render_keeps_the_target_unless_told_to_clear_it(browser, plan):
    target = {"agent": "claude-code", "session": "abc", "name": "Cosima"}
    post = lambda body: browser.post("/_/render", {"path": str(plan), **body}, cookie=False, key=True)   # noqa: E731
    post({"target": target})
    stored = state.Docs().get(DOC)["target"]                   # every field, the ones not sent empty
    assert stored["agent"] == "claude-code" and stored["session"] == "abc"
    assert stored["name"] == "Cosima" and stored["pid"] is None and stored["socket"] == ""
    post({"target": None})                                     # a plain shell: the target stays
    assert state.Docs().get(DOC)["target"] == stored
    post({"target": {"agent": "none"}})                        # --agent none: it is cleared
    assert state.Docs().get(DOC)["target"] is None


@pytest.mark.parametrize("make", [
    lambda p: {}, lambda p: {"path": 5}, lambda p: {"path": "relative/plan.md"},
    lambda p: {"path": "/nonexistent/plan.md"}, lambda p: {"path": str(p.parent)},
    lambda p: {"path": str(p), "settings": []},
    lambda p: {"path": str(p), "settings": {"toc": "sometimes"}},
    lambda p: {"path": str(p), "settings": {"max_image_width": "wide"}},
    lambda p: {"path": str(p), "settings": {"max_image_width": 0}},
    lambda p: {"path": str(p), "settings": {"max_image_width": True}},
    lambda p: {"path": str(p), "settings": {"title": 5}},
    lambda p: {"path": str(p), "settings": {"credit": "yes"}},
    lambda p: {"path": str(p), "target": "x"}])
def test_render_of_nonsense_is_400(browser, plan, make):
    r = browser.post("/_/render", make(plan), cookie=False, key=True)
    assert r.status == 400 and r.json()["ok"] is False


def test_a_document_the_renderer_refuses_is_422_with_its_reason(browser, plan, monkeypatch):
    from sheafmd.render import RenderError

    def refuse(*a, **k):
        raise RenderError("pandoc could not read this document")
    monkeypatch.setattr(browser.hub, "render", refuse)
    r = browser.post("/_/render", {"path": str(plan)}, key=True, cookie=False)
    assert r.status == 422 and r.json() == {"ok": False, "error": "pandoc could not read this document"}


def test_render_with_a_theme_that_does_not_exist_is_422_with_the_reason_not_a_500(browser, plan):
    """`sheaf open --theme nonesuch` sends the name to the hub; the answer names the theme."""
    r = browser.post("/_/render", {"path": str(plan), "settings": {"theme": "nonesuch"}},
                     cookie=False, key=True)
    assert r.status == 422 and "nonesuch" in r.json()["error"]
    assert rows("request-failed") == []


def test_render_with_a_theme_whose_name_holds_a_nul_is_422_not_a_500(browser, plan):
    """No file has that name: pathlib said False for it, and `os.stat` raises ValueError."""
    r = browser.post("/_/render", {"path": str(plan), "settings": {"theme": "bad\0name"}},
                     cookie=False, key=True)
    assert r.status == 422 and "there is no folder at" in r.json()["error"]
    assert rows("request-failed") == []


def test_render_with_a_theme_behind_a_folder_the_hub_may_not_enter_is_422_naming_it(
        browser, plan, tmp_path, closed):
    """3.13 answered 500 (PermissionError), 3.14 "there is no folder at" for a folder that is there."""
    brand = tmp_path / "srv" / "brand"
    brand.mkdir(parents=True)
    (brand / "theme.toml").write_text('name = "brand"\n', encoding="utf-8")
    closed(tmp_path / "srv")
    r = browser.post("/_/render", {"path": str(plan), "settings": {"theme": str(brand)}},
                     cookie=False, key=True)
    assert r.status == 422 and f"the folder {brand} cannot be entered: Permission denied" in r.json()["error"]
    assert rows("request-failed") == []


def test_render_of_a_file_that_is_not_markdown_is_400(browser, work):
    f = work / "notes.txt"
    f.write_text("x")
    assert browser.post("/_/render", {"path": str(f)}, cookie=False, key=True).status == 400


def test_jobs_lists_what_runs_in_every_document(browser, plan):
    assert browser.get("/_/jobs", cookie=False, key=True).json() == {"ok": True, "asking": [],
                                                                      "telling": []}


def test_stop_asks_the_hub_to_stop_with_a_reason(browser, plan):
    assert browser.hub.stop_requested is None
    r = browser.post("/_/stop", {"reason": "upgrade"}, cookie=False, key=True)
    assert r.json() == {"ok": True} and browser.hub.stop_requested == "upgrade"


@pytest.mark.parametrize("body", [{}, {"reason": "because"}, {"reason": 3}])
def test_stop_with_another_reason_is_400(browser, plan, body):
    assert browser.post("/_/stop", body, cookie=False, key=True).status == 400
    assert browser.hub.stop_requested is None


# ── the event stream and the watcher ─────────────────────────────────────────

def test_a_stream_starts_with_hello_and_counts_its_tab(browser, plan):
    a = browser.get(f"/_/live?doc={DOC}")
    assert a.status == 200 and a.headers["Content-Type"] == "text/event-stream"
    assert a.stream.drain() == [("hello", {"boot": browser.hub.boot, "version": browser.hub.version,
                                           "service": False, "tabs": 1})]
    b = browser.get(f"/_/live?doc={DOC}")
    assert b.stream.drain()[0][1]["tabs"] == 2
    a.stream.close()
    assert browser.hub.tabs(DOC) == 1


def test_a_stream_of_a_document_that_is_not_there_is_404(browser, plan):
    assert browser.get("/_/live?doc=work/none.md").status == 404
    assert browser.get("/_/live?doc=").status == 404


def test_the_watcher_tells_an_open_tab_about_a_write_from_outside(browser, plan):
    tab = browser.get(f"/_/live?doc={DOC}").stream
    tab.drain()
    update_file(plan, lambda t: t.replace("about apples", "about apples and plums"))
    browser.hub.tick()
    (name, data), = tab.drain()
    assert name == "changed" and data["textSame"] is False
    assert data["hash"] == md_hash(plan.read_text(encoding="utf-8"))
    assert "plums" in browser.get(URL).text                 # and the page it serves is the new one
    browser.hub.tick()
    assert tab.drain() == []                                # said once


def test_a_write_that_only_moved_comments_says_so(browser, plan):
    tab = browser.get(f"/_/live?doc={DOC}").stream
    tab.drain()
    update_file(plan, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "Second paragraph"),
                                                "Second paragraph", "Why?", "Grace",
                                                "2026-10-14T10:00")[0])
    browser.hub.tick()
    (name, data), = tab.drain()
    assert name == "changed" and data["textSame"] is True and data["comments"][0]["by"] == "Grace"


def test_a_document_with_no_tab_is_not_watched_but_its_page_is_current_when_asked_for(browser, plan):
    """The watcher skips a document nobody has open, so `sheaf open` after an agent's edit used
    to serve the old text until the first `changed`: the page itself catches up on the request."""
    browser.get(URL)
    update_file(plan, lambda t: t.replace("about apples", "about apples and plums"))
    browser.hub.tick()
    assert "plums" in browser.get(URL).text


def test_a_tab_that_connects_after_an_outside_write_is_told_when_the_page_it_holds_is_old(browser, plan):
    browser.get(URL)
    update_file(plan, lambda t: t.replace("about apples", "about apples and plums"))
    tab = browser.get(f"/_/live?doc={DOC}").stream
    browser.hub.tick()                                      # now a tab is open
    assert [n for n, _ in tab.drain()] == ["hello", "changed"]


def test_a_page_served_after_an_outside_write_tells_the_tabs_already_open(browser, plan):
    tab = browser.get(f"/_/live?doc={DOC}").stream
    tab.drain()
    update_file(plan, lambda t: t.replace("about apples", "about apples and plums"))
    assert "plums" in browser.get(URL).text                 # a second tab opens before the tick
    (name, data), = tab.drain()
    assert name == "changed" and data["hash"] == md_hash(plan.read_text(encoding="utf-8"))
    browser.hub.tick()
    assert tab.drain() == []                                # said once


def two_tabs(browser):
    a = browser.get(f"/_/live?doc={DOC}").stream
    b = browser.get(f"/_/live?doc={DOC}").stream
    a.drain()
    b.drain()
    return a, b


def test_a_save_tells_every_open_tab_once(browser, plan):
    a, b = two_tabs(browser)
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN),
                                 "edits": edit(PLAN, "Second paragraph", "<p>Second, saved.</p>")})
    got = r.json()
    for tab in (a, b):
        (name, data), = tab.drain()
        assert name == "changed" and data["hash"] == got["hash"] == md_hash(plan.read_text(encoding="utf-8"))
        assert data["base"] == md_hash(PLAN) and data["textSame"] is False
    browser.hub.tick()
    assert a.drain() == [] and b.drain() == []              # said once: the watcher finds nothing new


def test_a_save_that_changed_nothing_tells_no_tab(browser, plan):
    a, b = two_tabs(browser)
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN), "edits": []})
    assert r.status == 200 and r.json()["changed"] == []
    browser.hub.tick()
    assert a.drain() == [] and b.drain() == []


def test_a_comment_tells_every_open_tab_once_for_each_operation(browser, plan):
    a, b = two_tabs(browser)
    h = lambda: md_hash(plan.read_text(encoding="utf-8"))          # noqa: E731
    sent = [add(browser)]
    sent.append(browser.post("/_/comment", {"doc": DOC, "op": "reply", "hash": h(), "id": "c1",
                                            "body": "Because.", "resolve": True}))
    sent.append(browser.post("/_/comment", {"doc": DOC, "op": "status", "hash": h(), "id": "c1",
                                            "status": "open"}))
    sent.append(browser.post("/_/comment", {"doc": DOC, "op": "edit", "hash": h(), "id": "c1",
                                            "body": "Why pears, really?"}))
    sent.append(browser.post("/_/comment", {"doc": DOC, "op": "delete", "hash": h(), "id": "c1"}))
    assert [r.status for r in sent] == [200] * 5
    for tab in (a, b):
        got = tab.drain()
        assert [n for n, _ in got] == ["changed"] * 5
        assert [d["hash"] for _, d in got] == [r.json()["hash"] for r in sent]
        assert all(d["textSame"] is True for _, d in got)
        assert [d["base"] for _, d in got][0] == md_hash(PLAN)
        assert [d["base"] for _, d in got][1:] == [d["hash"] for _, d in got][:-1]
        assert [len(d["comments"]) for _, d in got] == [1, 1, 1, 1, 0]
    browser.hub.tick()
    assert a.drain() == [] and b.drain() == []              # said once each


def test_a_comment_the_hub_refused_tells_no_tab(browser, plan):
    a, b = two_tabs(browser)
    r = browser.post("/_/comment", {"doc": DOC, "op": "reply", "hash": md_hash(PLAN), "id": "c9",
                                    "body": "Nobody here."})
    assert r.status == 410
    assert a.drain() == [] and b.drain() == []


def test_a_page_whose_rebuild_fails_is_the_last_good_one_and_the_failure_is_written_down(browser, plan, monkeypatch):
    browser.get(URL)
    entry = browser.hub.entry(DOC)
    monkeypatch.setattr(entry.live, "refresh", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pandoc died")))
    update_file(plan, lambda t: t + "\nMore.\n")
    r = browser.get(URL)
    assert r.status == 200 and "about apples" in r.text
    assert rows("rebuild-failed")[0]["error"] == "RuntimeError: pandoc died"


def test_a_rebuild_that_failed_is_tried_again_on_the_next_tick_not_when_the_file_next_changes(browser, plan, monkeypatch):
    tab = browser.get(f"/_/live?doc={DOC}").stream
    tab.drain()
    entry = browser.hub.entry(DOC)
    real, calls = entry.live.refresh, []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("pandoc died")
        return real(*a, **k)
    monkeypatch.setattr(entry.live, "refresh", flaky)
    update_file(plan, lambda t: t + "\nMore.\n")
    browser.hub.tick()
    assert tab.drain() == [] and len(rows("rebuild-failed")) == 1
    browser.hub.tick()                                      # the file has not moved since
    (name, data), = tab.drain()
    assert name == "changed" and "More." in browser.get(URL).text


def test_a_rebuild_that_keeps_failing_is_written_down_once_not_every_tick(browser, plan, monkeypatch):
    """The retry is every second while the file stays broken; the log has one row for it, so a
    document nobody fixes does not push the older rows out of the capped file."""
    tab = browser.get(f"/_/live?doc={DOC}").stream
    tab.drain()
    entry = browser.hub.entry(DOC)
    real, broken = entry.live.refresh, [True]

    def refresh(*a, **k):
        if broken:
            raise RuntimeError("pandoc died")
        return real(*a, **k)
    monkeypatch.setattr(entry.live, "refresh", refresh)
    update_file(plan, lambda t: t + "\nMore.\n")
    for _ in range(4):
        browser.hub.tick()
    assert len(rows("rebuild-failed")) == 1 and tab.drain() == []
    broken.clear()                                          # fixed: the page catches up
    browser.hub.tick()
    (name, data), = tab.drain()
    assert name == "changed" and len(rows("rebuild-failed")) == 1
    broken.append(True)                                     # broken again, a new failure
    update_file(plan, lambda t: t + "\nAnd more.\n")
    browser.hub.tick()
    browser.hub.tick()
    assert len(rows("rebuild-failed")) == 2


def test_the_same_failure_on_another_state_of_the_file_is_written_again_whatever_rebuilt_in_between(browser, plan, monkeypatch):
    """A save rebuilds the page without the watcher, so the hub cannot know a rebuild worked
    from its own bookkeeping alone: a failure is the same only while the file is the same."""
    tab = browser.get(f"/_/live?doc={DOC}").stream
    tab.drain()
    entry = browser.hub.entry(DOC)
    monkeypatch.setattr(entry.live, "refresh", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pandoc died")))
    update_file(plan, lambda t: t + "\nMore.\n")
    browser.hub.tick()
    browser.hub.tick()
    assert len(rows("rebuild-failed")) == 1
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN),
                                 "edits": edit(PLAN, "Second paragraph", "<p>Second, saved.</p>")})
    assert r.status == 200 and r.json()["changed"]                  # a rebuild that worked, by the save
    update_file(plan, lambda t: t + "\nAnd more.\n")
    browser.hub.tick()
    browser.hub.tick()
    assert len(rows("rebuild-failed")) == 2


def test_a_failure_after_a_rebuild_that_worked_is_written_again_even_for_the_same_file(browser, plan, monkeypatch):
    """Any rebuild that works ends the failure that came before it, the settings change that
    renders the page again included: the file is the same one and the error the same, and the
    log still hears of it, because the page was fine in between."""
    tab = browser.get(f"/_/live?doc={DOC}").stream
    tab.drain()
    entry = browser.hub.entry(DOC)
    monkeypatch.setattr(entry.live, "refresh", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pandoc died")))
    update_file(plan, lambda t: t + "\nMore.\n")
    browser.hub.tick()
    browser.hub.tick()
    assert len(rows("rebuild-failed")) == 1
    entry.live.rebuild()                                    # what a change of the render settings does
    browser.hub.tick()
    browser.hub.tick()
    assert len(rows("rebuild-failed")) == 2


def test_a_page_asked_for_again_while_its_rebuild_keeps_failing_writes_one_row(browser, plan, monkeypatch):
    browser.get(URL)
    entry = browser.hub.entry(DOC)
    monkeypatch.setattr(entry.live, "refresh", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pandoc died")))
    update_file(plan, lambda t: t + "\nMore.\n")
    for _ in range(3):
        assert browser.get(URL).status == 200
    assert len(rows("rebuild-failed")) == 1


def test_a_rebuild_that_fails_is_written_down_and_the_loop_goes_on(browser, plan, monkeypatch):
    tab = browser.get(f"/_/live?doc={DOC}").stream
    tab.drain()
    update_file(plan, lambda t: t + "\nMore.\n")
    entry = browser.hub.entry(DOC)
    monkeypatch.setattr(entry.live, "refresh", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pandoc died")))
    browser.hub.tick()
    assert rows("rebuild-failed")[0]["error"] == "RuntimeError: pandoc died"


def test_stopping_tells_every_stream(browser, plan):
    tab = browser.get(f"/_/live?doc={DOC}").stream
    tab.drain()
    browser.hub.announce_stop("stop")
    assert tab.drain() == [("hub-stopping", {"reason": "stop"})]


# ── what goes wrong ──────────────────────────────────────────────────────────

def test_an_exception_in_a_request_is_a_500_and_a_row_and_the_hub_goes_on(browser, plan, monkeypatch):
    entry = browser.hub.entry(DOC)
    monkeypatch.setattr(entry.live, "save", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(PLAN), "edits": []})
    assert r.status == 500 and r.json()["ok"] is False and "boom" not in r.text
    row = rows("request-failed")[0]
    assert row["source"] == "hub" and "RuntimeError: boom" in row["traceback"] and row["endpoint"] == "/_/save"
    assert browser.get(URL).status == 200


def test_every_refusal_is_written_down_with_its_endpoint(browser, plan):
    browser.post("/_/save", {"doc": "work/none.md", "hash": "x", "edits": []})
    row = rows("save-404")[0]
    assert row["source"] == "hub" and row["error"] == "no such document" and row["endpoint"] == "/_/save"


def test_an_unknown_route_is_404_and_a_wrong_method_405(browser, plan):
    assert browser.get("/_/nothing").status == 404
    assert browser.post("/_/nothing").status == 404
    r = browser.get("/_/save")
    assert r.status == 405 and r.headers["Allow"] == "POST"
    r = browser.post(f"/_/doc?doc={DOC}")
    assert r.status == 405 and r.headers["Allow"] == "GET"
    assert browser.request("PUT", "/_/save").status == 405
    assert browser.request("DELETE", URL).status == 405


def test_every_response_says_not_to_cache_and_not_to_refer(browser, plan):
    for r in (browser.get(URL), browser.get("/_/health", cookie=False), browser.get("/_/nothing"),
              browser.get(URL, cookie=False), browser.post("/_/seen", {}), browser.get("/_/jobs", key=True)):
        assert r.headers["Cache-Control"] == "no-store" and r.headers["Referrer-Policy"] == "no-referrer"


# ── a restart the service manager makes: the hub is told first (SPEC 8.4) ────

def stops_of(hub):
    seen = []
    hub.on_stop = seen.append
    return seen


def test_a_signal_after_the_hub_was_told_of_a_restart_is_an_upgrade_stop(browser):
    seen = stops_of(browser.hub)
    assert browser.post("/_/restarting", cookie=False, key=True).json() == {"ok": True}
    browser.hub.request_stop("signal")
    assert seen == ["upgrade"] and browser.hub.stop_requested == "upgrade"
    assert browser.hub.told_restart is True


def test_a_signal_nobody_announced_stays_a_signal(browser):
    seen = stops_of(browser.hub)
    browser.hub.request_stop("signal")
    assert seen == ["signal"] and browser.hub.told_restart is False


def test_a_restart_that_was_announced_and_never_came_is_forgotten_after_a_while(browser):
    now = [1000.0]
    browser.hub.clock = lambda: now[0]
    seen = stops_of(browser.hub)
    browser.post("/_/restarting", cookie=False, key=True)
    now[0] += 31
    browser.hub.request_stop("signal")                 # a logout, a long time after
    assert seen == ["signal"]


def test_a_restart_the_command_takes_back_is_forgotten_at_once(browser):
    """`sheaf restart` told the hub, then the service manager failed: the next SIGTERM is a logout or
    a `systemctl stop`, not the restart, and must say `signal` (8.4)."""
    seen = stops_of(browser.hub)
    browser.post("/_/restarting", cookie=False, key=True)
    r = browser.request("DELETE", "/_/restarting", cookie=False, key=True)
    assert r.status == 200 and r.json() == {"ok": True}
    browser.hub.request_stop("signal")
    assert seen == ["signal"] and browser.hub.told_restart is False


def test_taking_back_a_restart_nobody_announced_is_a_quiet_ok(browser):
    seen = stops_of(browser.hub)
    assert browser.request("DELETE", "/_/restarting", cookie=False, key=True).status == 200
    browser.hub.request_stop("signal")
    assert seen == ["signal"]


def test_a_restart_announced_again_after_it_was_taken_back_is_expected_again(browser):
    seen = stops_of(browser.hub)
    browser.post("/_/restarting", cookie=False, key=True)
    browser.request("DELETE", "/_/restarting", cookie=False, key=True)
    browser.post("/_/restarting", cookie=False, key=True)
    browser.hub.request_stop("signal")
    assert seen == ["upgrade"] and browser.hub.told_restart is True


def stop_with(browser, reason):
    return browser.post("/_/stop", {"reason": reason}, cookie=False, key=True)


@pytest.mark.parametrize("first", ["stop", "signal"])
def test_an_upgrade_stop_never_turns_a_stop_that_was_taken_into_a_restart(browser, first):
    """A plain stop (the person's) or a signal (a logout, the manager's) is under way: a newer
    command that asks for an upgrade then must not make it `upgrade`, because under the service
    that exits 75 and the manager starts the hub the person stopped (8.4, 14.4)."""
    seen = stops_of(browser.hub)
    if first == "stop":
        assert stop_with(browser, "stop").status == 200
    else:
        browser.hub.request_stop("signal")
    r = stop_with(browser, "upgrade")
    assert r.status == 200 and r.json() == {"ok": True}          # it is stopping, as the caller wanted
    assert browser.hub.stop_requested == first and seen == [first]
    assert browser.hub.told_restart is False


def test_a_signal_that_follows_the_announcement_of_a_restart_does_not_turn_a_stop_into_an_upgrade(browser):
    seen = stops_of(browser.hub)
    stop_with(browser, "stop")
    browser.post("/_/restarting", cookie=False, key=True)
    browser.hub.request_stop("signal")
    assert browser.hub.stop_requested == "stop" and browser.hub.told_restart is False
    assert seen == ["stop"]


@pytest.mark.parametrize("later", ["stop", "signal"])
def test_a_stop_or_a_signal_after_an_upgrade_stop_wins(browser, later):
    """The other way round the person's decision is the later one: the hub ends for good."""
    seen = stops_of(browser.hub)
    assert stop_with(browser, "upgrade").status == 200
    if later == "stop":
        stop_with(browser, "stop")
    else:
        browser.hub.request_stop("signal")
    assert browser.hub.stop_requested == later and seen == ["upgrade", later]


def test_a_second_upgrade_stop_is_taken_again_as_before(browser):
    seen = stops_of(browser.hub)
    assert stop_with(browser, "upgrade").status == 200 and stop_with(browser, "upgrade").status == 200
    assert browser.hub.stop_requested == "upgrade" and seen == ["upgrade", "upgrade"]


def test_only_a_signal_is_turned_into_an_upgrade_by_the_announcement(browser):
    seen = stops_of(browser.hub)
    browser.post("/_/restarting", cookie=False, key=True)
    browser.hub.request_stop("stop")
    assert seen == ["stop"]
