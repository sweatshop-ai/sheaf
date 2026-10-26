"""The door's tools `threads`, `reply` and `resolve`, in memory (SPEC 12). `documents` is in
test_mcp_documents.py. Authentication and the protocol are in test_mcp_http.py."""
import json
import re
import subprocess

import pytest

import sheafmd.comments as rdc
from helpers import (GIT_FAILS, PLAN, call, comment, git_dirs_in, git_fails, ok, page_meta, refused,
                     refused_as_not_there)
from sheafmd import diagnostics, mcp
from sheafmd.hub.live import prose
from sheafmd.hub.state import Tokens
from sheafmd.source import md_hash, update_file

DOC = "work/plan.md"
PAGE = "/work/plan.md"


@pytest.fixture
def talk(plan):
    """plan.md with one open comment, c1, asked by Ada."""
    comment(plan)
    return plan


def thread(path, cid="c1"):
    return rdc.parse(path.read_text(encoding="utf-8")).by_id(cid)


# ── threads ──────────────────────────────────────────────────────────────────

def test_threads_reads_what_was_asked_with_exactly_the_documented_fields(browser, talk):
    got = ok(browser, "threads", doc=DOC)
    assert got["doc"] == DOC and got["url"] == f"http://127.0.0.1:{browser.hub.port}{PAGE}"
    assert got["malformed"] == []
    [c] = got["comments"]
    assert sorted(c) == ["at", "body", "by", "id", "line", "orphan", "quote", "replies", "status"]
    assert (c["id"], c["by"], c["at"], c["status"]) == ("c1", "Ada", "2026-10-14T10:00", "open")
    assert (c["quote"], c["body"], c["orphan"], c["replies"]) == ("Second paragraph", "Why pears?",
                                                                  False, [])
    text = talk.read_text(encoding="utf-8")
    assert c["line"] == text.count("\n", 0, text.index("<!-- ")) + 1


def test_every_reply_carries_who_what_when_and_its_effective_role(browser, talk):
    update_file(talk, lambda t: rdc.reply(t, "c1", "Looks fine.", "Ada", "2026-10-14T10:05"))
    update_file(talk, lambda t: rdc.reply(t, "c1", "Done.", "Codex", "2026-10-14T10:06", role="action"))
    update_file(talk, lambda t: rdc.reply(t, "c1", "Old style.", "Claude (action)", "2026-10-14T10:07"))
    replies = ok(browser, "threads", doc=DOC)["comments"][0]["replies"]
    assert [sorted(r) for r in replies] == [["at", "by", "display", "role", "text"]] * 3
    assert [(r["by"], r["display"], r["role"]) for r in replies] == [
        ("Ada", "Ada", None), ("Codex", "Codex", "action"), ("Claude (action)", "Claude", "action")]
    assert replies[1]["text"] == "Done." and replies[1]["at"] == "2026-10-14T10:06"


@pytest.mark.parametrize("status,ids", [(None, ["c2"]), ("open", ["c2"]), ("resolved", ["c1"]),
                                        ("all", ["c1", "c2"])])
def test_threads_shows_the_open_ones_unless_asked_for_more(browser, talk, status, ids):
    comment(talk, "First paragraph", "And apples?")
    update_file(talk, lambda t: rdc.set_status(t, "c1", "resolved"))
    got = ok(browser, "threads", doc=DOC, **({"status": status} if status else {}))
    assert sorted(c["id"] for c in got["comments"]) == ids


def test_threads_lists_a_comment_that_cannot_be_read_with_its_line_and_reason(browser, talk):
    update_file(talk, lambda t: t + "\n-->\n")
    got = ok(browser, "threads", doc=DOC)
    assert [c["id"] for c in got["comments"]] == ["c1"]
    [m] = got["malformed"]
    assert sorted(m) == ["line", "reason"] and isinstance(m["line"], int) and m["reason"]


def test_threads_reads_the_file_as_it_is_now_not_as_the_page_was_rendered(browser, talk):
    browser.get(PAGE)                                           # the hub has the page in memory
    comment(talk, "First paragraph", "Written after the page was rendered.")
    assert sorted(c["id"] for c in ok(browser, "threads", doc=DOC)["comments"]) == ["c1", "c2"]


@pytest.mark.parametrize("doc", [DOC, f"http://127.0.0.1:27419{PAGE}", f"http://localhost:1{PAGE}",
                                 f"http://127.0.0.1:27419{PAGE}?x=1#top", "ABSOLUTE"])
def test_a_document_is_named_by_address_page_url_or_absolute_path(browser, talk, doc):
    doc = str(talk) if doc == "ABSOLUTE" else doc
    got = ok(browser, "threads", doc=doc)
    assert got["doc"] == DOC and got["comments"][0]["id"] == "c1"


def test_an_absolute_path_to_a_document_in_no_root_registers_its_root_for_the_key(browser, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "n.md").write_text(PLAN, encoding="utf-8")
    assert browser.hub.roots.all() == []
    got = ok(browser, "threads", doc=str(other / "n.md"))
    assert got["doc"] == "elsewhere/n.md" and got["comments"] == []
    assert [r.name for r in browser.hub.roots.all()] == ["elsewhere"]


def test_an_absolute_path_behind_a_folder_that_may_not_be_entered_names_the_reason(browser, tmp_path, closed):
    """The key's caller runs as the hub's account; 3.14 said "is not an existing .md file"."""
    other = tmp_path / "srv" / "notes"
    other.mkdir(parents=True)
    (other / "n.md").write_text(PLAN, encoding="utf-8")
    closed(tmp_path / "srv")
    got = refused(browser, "threads", doc=str(other / "n.md"))
    assert got == f"{other / 'n.md'} cannot be used as a document (Permission denied)."
    assert browser.hub.roots.all() == []


@pytest.mark.parametrize("doc", [
    "plan.md", "nowhere/plan.md", "work/none.md", "work/../plan.md", "work/plan.txt", "work/",
    "", "  ", "/", "/nonexistent/x.md", "work/plan.md\0", "http://evil.example/work/plan.md",
    "https://127.0.0.1:27419/work/plan.md", "http://127.0.0.1:27419/work/",
    "ftp://127.0.0.1/work/plan.md", "http://127.0.0.1:27419/_/doc"])
def test_a_document_that_is_not_there_is_an_error_the_agent_can_read(browser, talk, doc):
    before = talk.read_bytes()
    refused(browser, "threads", doc=doc)
    assert talk.read_bytes() == before


def test_a_symlink_out_of_the_root_is_not_a_document(browser, talk, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# secret\n", encoding="utf-8")
    (talk.parent / "link.md").symlink_to(outside)
    refused(browser, "threads", doc="work/link.md")


# ── reply ────────────────────────────────────────────────────────────────────

def test_a_reply_is_written_signed_with_the_name_the_door_was_given(browser, talk):
    before = talk.read_text(encoding="utf-8")
    got = ok(browser, "reply", doc=DOC, id="c1", text="Pears keep better.", as_name="Claude Code")
    r = thread(talk).replies[-1]
    assert (r.by, r.text, r.role) == ("Claude Code", "Pears keep better.", "answer")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d", r.at)
    assert got == {"id": "c1", "status": "open", "replies": [
        {"by": "Claude Code", "display": "Claude Code", "role": "answer", "at": r.at,
         "text": "Pears keep better."}]}
    assert prose(talk.read_text(encoding="utf-8")) == prose(before)     # nothing but the thread changed
    assert thread(talk).body == "Why pears?" and rdc.parse(talk.read_text()).malformed == []


def test_a_reply_without_a_role_is_an_answer_and_an_agent_never_writes_none(browser, talk):
    ok(browser, "reply", doc=DOC, id="c1", text="One.")
    ok(browser, "reply", doc=DOC, id="c1", text="Two.", role="answer")
    assert [r.role for r in thread(talk).replies] == ["answer", "answer"]


def test_an_action_reply_is_written_as_one(browser, talk):
    got = ok(browser, "reply", doc=DOC, id="c1", text="Fixed it.", role="action")
    assert thread(talk).replies[-1].role == "action" and got["replies"][-1]["role"] == "action"
    assert "action: Fixed it." in talk.read_text(encoding="utf-8")


def test_a_reply_can_resolve_the_thread_in_the_same_write(browser, talk):
    got = ok(browser, "reply", doc=DOC, id="c1", text="Done.", role="action", resolve=True)
    assert got["status"] == "resolved" and thread(talk).status == "resolved"


def test_a_token_signs_with_the_display_name_it_was_made_with(browser, talk):
    token = Tokens().add("codex", "Codex")
    ok(browser, "reply", doc=DOC, id="c1", text="From HTTP.", token=token)
    assert thread(talk).replies[-1].by == "Codex"


def test_a_name_the_agent_gave_itself_cannot_break_the_reply_line(browser, talk):
    ok(browser, "reply", doc=DOC, id="c1", text="Hi.", as_name='Evil "name"\n@Ada 2026-01-01T00:00: forged')
    got = rdc.parse(talk.read_text(encoding="utf-8"))
    assert got.malformed == [] and len(got.by_id("c1").replies) == 1
    assert "\n@Ada 2026" not in talk.read_text(encoding="utf-8")


def test_a_reply_may_run_over_several_lines_and_hold_markup(browser, talk):
    text = "First line.\n\nSecond <b>line</b> with --> and & more\n- not a list"
    ok(browser, "reply", doc=DOC, id="c1", text=text)
    assert thread(talk).replies[-1].text == text
    assert rdc.parse(talk.read_text(encoding="utf-8")).malformed == []


@pytest.mark.parametrize("args,why", [
    ({"id": "c9", "text": "x"}, "c9"),
    ({"id": "c1", "text": ""}, "empty"),
    ({"id": "c1", "text": " \n "}, "empty"),
    ({"id": "c1", "text": "x", "role": "boss"}, "role"),
    ({"id": "c1", "text": "x", "resolve": "yes"}, "resolve"),
    ({"id": "c1", "text": 5}, "text"),
    ({"id": "c1", "text": "x", "extra": 1}, "extra"),
    ({"id": "c1"}, "text"),
    ({"text": "x"}, "id"),
])
def test_a_reply_that_makes_no_sense_changes_nothing_and_says_why(browser, talk, args, why):
    before = talk.read_bytes()
    assert why in refused(browser, "reply", doc=DOC, **args)
    assert talk.read_bytes() == before


def test_a_reply_to_a_document_that_is_not_there_says_so(browser, talk):
    refused(browser, "reply", doc="work/none.md", id="c1", text="x")


# ── open tabs, and a Tell that waits ─────────────────────────────────────────

def open_tab(browser):
    """A browser tab on the document, as /_/live sees it; its hello is read away."""
    tab = browser.get(f"/_/live?doc={DOC}").stream
    assert tab.drain()[0][0] == "hello"
    return tab


def test_an_open_tab_is_told_at_once_and_gets_the_reply_in_place(browser, talk):
    browser.get(PAGE)
    tab = open_tab(browser)
    before = md_hash(talk.read_text(encoding="utf-8"))
    ok(browser, "reply", doc=DOC, id="c1", text="Pears keep better.")
    (name, data), = tab.drain()
    assert name == "changed" and data["textSame"] is True and data["base"] == before
    assert data["hash"] == md_hash(talk.read_text(encoding="utf-8"))
    assert data["comments"][0]["replies"][0]["text"] == "Pears keep better."
    assert data["comments"][0]["replies"][0]["display"] == "Claude"
    assert data["telling"] == [] and data["malformed"] == []


def test_a_page_opened_afterwards_already_holds_the_reply(browser, talk):
    browser.get(PAGE)
    ok(browser, "reply", doc=DOC, id="c1", text="Pears keep better.")
    meta = page_meta(browser.get(PAGE).text)
    assert meta["comments"][0]["replies"][0]["text"] == "Pears keep better."
    assert meta["hash"] == md_hash(talk.read_text(encoding="utf-8"))


def test_an_action_reply_ends_a_tell_wait_and_the_tab_hears_it(browser, talk):
    e = browser.hub.entry(DOC)
    assert e.live.await_reply("c1") is True and browser.hub.jobs()["telling"] == [[DOC, "c1"]]
    tab = open_tab(browser)
    ok(browser, "reply", doc=DOC, id="c1", text="Did it.", role="action")
    assert e.live.waiting() == [] and browser.hub.jobs()["telling"] == []
    (name, data), = tab.drain()
    assert name == "changed" and data["telling"] == []


def test_an_answer_does_not_end_a_tell_wait(browser, talk):
    e = browser.hub.entry(DOC)
    e.live.await_reply("c1")
    tab = open_tab(browser)
    ok(browser, "reply", doc=DOC, id="c1", text="Only words.", role="answer")
    assert e.live.waiting() == ["c1"]
    (name, data), = tab.drain()
    assert name == "changed" and data["telling"] == ["c1"]


def test_a_resolve_through_a_reply_ends_no_wait_by_itself_but_is_seen(browser, talk):
    e = browser.hub.entry(DOC)
    tab = open_tab(browser)
    ok(browser, "reply", doc=DOC, id="c1", text="Done.", role="action", resolve=True)
    (name, data), = tab.drain()
    assert data["comments"][0]["status"] == "resolved" and e.live.waiting() == []


def test_a_document_nobody_has_open_is_written_straight_to_the_file(browser, talk):
    assert DOC not in browser.hub.entries
    ok(browser, "reply", doc=DOC, id="c1", text="Quietly.")
    assert thread(talk).replies[-1].text == "Quietly."
    assert DOC not in browser.hub.entries                    # no page was rendered for a reply


def test_the_diagnostics_log_has_no_row_for_a_good_reply(browser, talk):
    ok(browser, "reply", doc=DOC, id="c1", text="Fine.")
    assert [r for r in diagnostics.read() if r["kind"].startswith("mcp")] == []


# ── resolve ──────────────────────────────────────────────────────────────────

def test_resolve_marks_the_thread_resolved(browser, talk):
    assert ok(browser, "resolve", doc=DOC, id="c1") == {"id": "c1", "status": "resolved"}
    assert thread(talk).status == "resolved"


def test_resolving_a_resolved_thread_does_not_touch_the_file(browser, talk):
    ok(browser, "resolve", doc=DOC, id="c1")
    # Written by hand, with a raw `&` that any rewrite of the comment would encode.
    update_file(talk, lambda t: t.replace("Why pears?", "Why pears & plums?"))
    before = talk.read_bytes()
    mtime = talk.stat().st_mtime_ns
    assert ok(browser, "resolve", doc=DOC, id="c1") == {"id": "c1", "status": "resolved"}
    assert talk.read_bytes() == before and talk.stat().st_mtime_ns == mtime


def test_resolve_tells_an_open_tab(browser, talk):
    browser.get(PAGE)
    tab = open_tab(browser)
    ok(browser, "resolve", doc=DOC, id="c1")
    (name, data), = tab.drain()
    assert name == "changed" and data["comments"][0]["status"] == "resolved"


def test_resolve_of_a_thread_that_is_not_there_says_so(browser, talk):
    before = talk.read_bytes()
    assert "c9" in refused(browser, "resolve", doc=DOC, id="c9")
    assert talk.read_bytes() == before


# ── a token stays inside the roots the hub has (9.7) ─────────────────────────

@pytest.fixture
def stranger(tmp_path):
    """A .md in a folder the hub has never been told about (outside the `work` root)."""
    f = tmp_path / "stranger" / "s.md"
    f.parent.mkdir()
    f.write_text(PLAN, encoding="utf-8")
    comment(f)
    return f


@pytest.mark.parametrize("tool,args", [
    ("threads", {}), ("reply", {"id": "c1", "text": "x"}), ("resolve", {"id": "c1"})])
def test_a_token_cannot_name_a_file_outside_every_root_and_adds_no_root(browser, talk, stranger,
                                                                         tool, args):
    token = Tokens().add("codex")
    before, roots = stranger.read_bytes(), [r.name for r in browser.hub.roots.all()]
    msg = refused(browser, tool, doc=str(stranger), token=token, **args)
    assert "token" in msg and "root" in msg
    assert stranger.read_bytes() == before
    assert [r.name for r in browser.hub.roots.all()] == roots == ["work"]


def test_a_token_gets_the_same_answer_for_a_file_that_is_not_there(browser, talk, tmp_path):
    token = Tokens().add("codex")
    a = refused(browser, "threads", doc=str(tmp_path / "stranger" / "gone.md"), token=token)
    (tmp_path / "stranger").mkdir()
    (tmp_path / "stranger" / "here.md").write_text("# x\n", encoding="utf-8")
    b = refused(browser, "threads", doc=str(tmp_path / "stranger" / "here.md"), token=token)
    assert a.replace("gone", "here") == b


def test_a_token_gets_the_same_answer_for_a_file_behind_a_folder_that_may_not_be_entered(
        browser, talk, tmp_path, closed):
    token = Tokens().add("codex")
    shut = tmp_path / "srv" / "notes"
    shut.mkdir(parents=True)
    (shut / "n.md").write_text(PLAN, encoding="utf-8")
    closed(tmp_path / "srv")
    a = refused(browser, "threads", doc=str(tmp_path / "gone" / "n.md"), token=token)
    b = refused(browser, "threads", doc=str(shut / "n.md"), token=token)
    assert a.replace(str(tmp_path / "gone"), str(shut)) == b and "Permission denied" not in b


def test_a_token_may_name_a_file_inside_a_root_the_hub_has(browser, talk):
    token = Tokens().add("codex")
    got = ok(browser, "threads", doc=str(talk), token=token)
    assert got["doc"] == DOC
    ok(browser, "reply", doc=str(talk), id="c1", text="By path.", token=token)
    assert thread(talk).replies[-1].by == "codex"


def test_a_token_naming_a_symlink_loop_gets_the_answer_of_a_file_that_is_not_there(browser, talk):
    token = Tokens().add("codex")
    loop, gone = talk.parent / "loop.md", talk.parent / "gone.md"
    loop.symlink_to(loop.name)
    said = refused(browser, "threads", doc=str(loop), token=token)
    assert said == refused(browser, "threads", doc=str(gone), token=token).replace(str(gone), str(loop))


def test_a_token_follows_the_same_root_as_the_key_when_roots_nest(browser, tmp_path):
    """A git repo inside a folder that is itself a root: the key puts a document of the repo in
    the repo's root, so the token must not find it under the outer one (two addresses would be two
    live documents for one file)."""
    import subprocess
    outer = tmp_path / "wiki"
    (outer / "sub").mkdir(parents=True)
    (outer / "a.md").write_text("# a\n", encoding="utf-8")
    browser.hub.roots.for_document(outer / "a.md")                 # `wiki` is a root, not git
    subprocess.run(["git", "init", "-q", str(outer / "sub")], check=True)
    inner = outer / "sub" / "b.md"
    inner.write_text("# b\n", encoding="utf-8")
    token = Tokens().add("codex")
    refused(browser, "threads", doc=str(inner), token=token)       # the repo is not a root yet
    assert ok(browser, "threads", doc=str(inner))["doc"] == "sub/b.md"   # the key registers it
    assert ok(browser, "threads", doc=str(inner), token=token)["doc"] == "sub/b.md"


# ── a git directory is no document to the door, by any name (8.2) ─────────────

@pytest.fixture
def git_dirs(talk):
    """`git_dirs_in` the root `work`, each page a copy of plan.md with its open comment c1."""
    return git_dirs_in(talk.parent, talk.read_text(encoding="utf-8"))


def by_url(address):
    return f"http://127.0.0.1:27419/{address}"


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.mark.parametrize("how", ["runs", *GIT_FAILS])
@pytest.mark.parametrize("who", ["key", "token"])
@pytest.mark.parametrize("tool,args", [
    ("threads", {}), ("reply", {"id": "c1", "text": "x"}), ("resolve", {"id": "c1"})])
def test_a_document_in_a_git_directory_is_not_there_to_the_door_by_address_or_page_url(
        browser, git_dirs, monkeypatch, tmp_path, how, who, tool, args):
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)
    token = Tokens().add("codex") if who == "token" else None
    for rel in ("sub/.git/x.md", "sub/keep.git/x.md"):
        before = (git_dirs / rel).read_bytes()
        for name in (f"work/{rel}", by_url(f"work/{rel}")):
            refused_as_not_there(browser, tool, name, name.replace(rel, "sub/gone.md"), token=token, **args)
        assert (git_dirs / rel).read_bytes() == before, rel


def test_the_key_still_reaches_a_document_in_a_git_directory_by_its_own_folders_root(browser, git_dirs):
    """Rule 3: for the key, a .md in a git directory is its own folder's root, and so the door names it."""
    got = ok(browser, "threads", doc=str(git_dirs / "sub" / ".git" / "x.md"))
    assert got["doc"] == "git/x.md" and got["comments"][0]["id"] == "c1"
    token = Tokens().add("codex")
    assert ok(browser, "threads", doc="git/x.md", token=token)["comments"][0]["id"] == "c1"
    ok(browser, "reply", doc="git/x.md", id="c1", text="Here.", token=token)
    (git_dirs / "sub" / ".git" / "objects" / "y.md").write_text(PLAN, encoding="utf-8")
    refused(browser, "threads", doc="git/objects/y.md", token=token)       # below its folder: closed


@pytest.mark.parametrize("how", ["runs", *GIT_FAILS])
def test_a_work_tree_inside_a_git_directory_is_reached_by_address_where_git_runs_and_closed_with_it_where_git_fails(
        browser, talk, monkeypatch, tmp_path, how):
    """A worktree of the bare repo `work/wiki.git`, at `wiki.git/w1`: a work tree to git; where git fails, the git
    directory that holds it closes it, as it does to a member."""
    work, seed = talk.parent, tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q")
    git(seed, "-c", "user.name=G", "-c", "user.email=g@example.com", "commit", "-q", "--allow-empty", "-m", "x")
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(work / "wiki.git"))
    git(work / "wiki.git", "worktree", "add", "-q", "-b", "side", "w1")
    (work / "wiki.git" / "w1" / "p.md").write_text(talk.read_text(encoding="utf-8"), encoding="utf-8")
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)
    token = Tokens().add("codex")
    if how == "runs":
        assert ok(browser, "threads", doc="work/wiki.git/w1/p.md", token=token)["comments"][0]["id"] == "c1"
    else:
        refused_as_not_there(browser, "threads", "work/wiki.git/w1/p.md", "work/wiki.git/w1/gone.md", token=token)


# The documents of a plain root, of a git root and of a plain root that holds a repo `sub`.
ROOT_DOCUMENTS = {"plain": ["a.md", "d/e/c.md"], "git": ["a.md", "d/e/c.md"],
                  "nested": ["a.md", "sub/b.md", "sub/d/c.md"]}


@pytest.mark.parametrize("how", ["runs", *GIT_FAILS])
@pytest.mark.parametrize("kind", ROOT_DOCUMENTS)
def test_the_door_reaches_the_documents_of_a_plain_root_a_git_root_and_a_nested_repos_work_tree_as_before(
        browser, tmp_path, monkeypatch, kind, how):
    top = tmp_path / kind
    (top / "sub").mkdir(parents=True)
    if kind != "plain":
        git(top if kind == "git" else top / "sub", "init", "-q")
    for rel in ROOT_DOCUMENTS[kind]:
        (top / rel).parent.mkdir(parents=True, exist_ok=True)
        (top / rel).write_text(PLAN, encoding="utf-8")
        comment(top / rel)
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)
    root = browser.hub.roots.for_document(top / "a.md")
    token = Tokens().add("codex")
    for rel in ROOT_DOCUMENTS[kind]:
        address = f"{root.name}/{rel}"
        for name in (address, by_url(address)):
            assert ok(browser, "threads", doc=name, token=token)["comments"][0]["id"] == "c1", name
        # by its path a nested repo's document is that repo's, a root the hub does not have where git runs
        other_root = kind == "nested" and rel.startswith("sub/") and how == "runs"
        refused_by_path, got = call(browser, "threads", doc=str(top / rel), token=token)
        assert refused_by_path == other_root and (other_root or got["doc"] == address), rel


# ── names the door shares with the rest of the code ──────────────────────────

def test_the_reply_tool_offers_the_roles_a_comment_knows():
    enum = mcp.TOOLS["reply"]["properties"]["role"]["enum"]
    assert tuple(enum) == rdc.ROLES


def test_the_internal_error_code_is_named_beside_the_other_codes():
    assert mcp.INTERNAL_ERROR == -32603


def test_hub_waiting_tells_whether_a_tell_waits_on_a_document(browser, talk):
    hub = browser.hub
    assert hub.waiting(DOC) is False                       # no entry yet
    e = hub.entry(DOC)
    assert hub.waiting(DOC) is False
    assert e.live.await_reply("c1") and hub.waiting(DOC) is True
