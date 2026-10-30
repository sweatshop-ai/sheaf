"""The door's page tools `read`, `create` and `update`, in memory (SPEC 12, 9.7). The comment tools
are in test_mcp_tools.py, authentication and the protocol in test_mcp_http.py."""
import os
import re
import subprocess

import pytest

import sheafmd.comments as rdc
from helpers import (GIT_FAILS, NOW, PLAN, comment, door, git_dirs_in, git_fails, ok, refused, refused_as_not_there, rpc,
                     undecodable_names_or_skip)
from sheafmd import diagnostics
from sheafmd.hub.state import Tokens
from sheafmd.mcp import NOT_IN_A_ROOT
from sheafmd.render import strip_comments
from sheafmd.source import md_hash, update_file
from test_hub_handler import edit

DOC = "work/plan.md"


# ── read ─────────────────────────────────────────────────────────────────────

def test_read_gives_the_text_as_the_file_holds_it_and_its_hash(browser, plan):
    comment(plan)
    text = plan.read_text(encoding="utf-8")
    got = ok(browser, "read", doc=DOC)
    assert got == {"doc": DOC, "url": f"http://127.0.0.1:{browser.hub.port}/work/plan.md",
                   "hash": md_hash(text), "text": text}
    assert "<!-- sheaf-comment id=c1" in got["text"]


def test_read_without_comments_gives_the_text_a_page_is_built_from(browser, plan):
    comment(plan)
    got = ok(browser, "read", doc=DOC, comments=False)
    assert got["text"] == PLAN
    assert got["hash"] == md_hash(plan.read_text(encoding="utf-8"))   # the hash an update needs


def test_read_without_comments_refuses_a_text_that_hides_the_rest_of_the_page(browser, plan):
    plan.write_text(PLAN + "\n<!-- never closed\n\nThe last paragraph.\n", encoding="utf-8")
    line = PLAN.count("\n") + 2
    assert f"line {line}" in refused(browser, "read", doc=DOC, comments=False)
    assert ok(browser, "read", doc=DOC)["text"].endswith("The last paragraph.\n")


def test_a_write_token_reads_and_a_token_without_the_right_does_not(browser, plan):
    """A token made without `--write` keeps the four tools it always had: `read` would show it the
    whole text of every document, where it saw the comments and their quotes (SPEC 9.7)."""
    assert ok(browser, "read", doc=DOC, token=Tokens().add("writer", write=True))["text"] == PLAN
    assert "--write" in refused(browser, "read", doc=DOC, token=Tokens().add("codex"))


def test_read_of_a_document_that_is_not_there_says_so(browser, plan):
    refused(browser, "read", doc="work/none.md")


# ── create ───────────────────────────────────────────────────────────────────

PAGE = "# The order\n\nThe thread.\n\n## Reply\n\nThank you.\n\n- [ ] Approve\n"


def test_create_makes_a_new_page_with_exactly_the_text_given(browser, plan, work):
    got = ok(browser, "create", doc="work/new.md", text=PAGE)
    assert (work / "new.md").read_text(encoding="utf-8") == PAGE
    assert got == {"doc": "work/new.md", "url": f"http://127.0.0.1:{browser.hub.port}/work/new.md",
                   "hash": md_hash(PAGE)}
    assert ok(browser, "read", doc="work/new.md")["hash"] == got["hash"]


def test_a_write_token_creates_a_page_and_names_it_by_absolute_path_too(browser, plan, work):
    token = Tokens().add("writer", write=True)
    ok(browser, "create", doc="work/a.md", text=PAGE, token=token)
    ok(browser, "create", doc=str(work / "b.md"), text=PAGE, token=token)
    assert (work / "a.md").read_text(encoding="utf-8") == (work / "b.md").read_text(encoding="utf-8") == PAGE


def test_an_absolute_path_under_a_folder_that_is_not_there_in_a_nested_repo_is_that_repos(browser, plan, work):
    """8.2 judges the folder that is not there by the nearest one that is, `sub`, a root the hub
    does not have: the page is not filed under `work`, which holds `sub` but is not its root."""
    subprocess.run(["git", "init", "-q", str(work / "sub")], check=True)
    doc = str(work / "sub" / "guess" / "new.md")
    msg = refused(browser, "create", doc=doc, text=PAGE, token=Tokens().add("writer", write=True))
    assert msg == f"{doc} {NOT_IN_A_ROOT}"


def test_a_token_made_without_the_right_cannot_create_and_is_told_how(browser, plan, work):
    token = Tokens().add("codex")
    msg = refused(browser, "create", doc="work/new.md", text=PAGE, token=token)
    assert "--write" in msg
    assert not (work / "new.md").exists()


def test_tools_list_shows_the_write_tools_only_to_a_caller_that_may_use_them(browser):
    def names(**kw):
        return [t["name"] for t in door(browser, rpc("tools/list"), **kw).json()["result"]["tools"]]
    everything = ["documents", "threads", "reply", "resolve", "read", "create", "update"]
    assert names() == everything                                        # the key
    assert names(token=Tokens().add("writer", write=True)) == everything
    assert names(token=Tokens().add("codex")) == ["documents", "threads", "reply", "resolve"]


def test_read_is_marked_read_only_and_the_write_tools_are_not(browser):
    tools = {t["name"]: t for t in door(browser, rpc("tools/list")).json()["result"]["tools"]}
    assert tools["read"]["annotations"] == {"readOnlyHint": True}
    assert "annotations" not in tools["create"] and "annotations" not in tools["update"]
    assert tools["create"]["inputSchema"]["required"] == ["doc", "text"]
    assert tools["update"]["inputSchema"]["required"] == ["doc", "text", "expected_hash"]


def test_create_makes_a_page_in_a_folder_of_the_root_that_exists(browser, plan, work):
    (work / "pages").mkdir()
    ok(browser, "create", doc="work/pages/t1.md", text=PAGE)
    assert (work / "pages" / "t1.md").read_text(encoding="utf-8") == PAGE
    assert sorted(p.name for p in (work / "pages").iterdir()) == ["t1.md"]       # nothing left beside it


@pytest.mark.parametrize("make", ["file", "folder", "link", "dangling"])
def test_create_never_replaces_anything_that_is_there(browser, plan, work, tmp_path, make):
    target = work / "new.md"
    if make == "file":
        target.write_text("# mine\n", encoding="utf-8")
    elif make == "folder":
        target.mkdir()
    elif make == "link":
        target.symlink_to(plan)
    else:
        target.symlink_to(work / "nowhere.md")
    before = plan.read_bytes()
    assert "exists already" in refused(browser, "create", doc="work/new.md", text=PAGE)
    assert plan.read_bytes() == before and not (work / "nowhere.md").exists()
    if make == "file":
        assert target.read_text(encoding="utf-8") == "# mine\n"


def test_creating_the_page_of_an_existing_document_is_refused(browser, plan):
    before = plan.read_bytes()
    refused(browser, "create", doc=DOC, text=PAGE)
    assert plan.read_bytes() == before


@pytest.mark.parametrize("doc", [
    "work/../x.md", "work/./x.md", "work//x.md", "work/x.txt", "work/x", "work/.x.md", "work/.hidden/x.md",
    "work/", "work", "", "  ", "nowhere/x.md", "work/x.md\0", "http://evil.example/work/x.md",
    "/nonexistent/x.md"])
def test_create_refuses_a_path_that_is_no_new_page_of_a_root(browser, plan, work, doc):
    (work / ".hidden").mkdir()
    before = sorted(p.name for p in work.rglob("*"))
    refused(browser, "create", doc=doc, text=PAGE)
    assert sorted(p.name for p in work.rglob("*")) == before


# A name Python made of bytes that are not UTF-8 (a lone surrogate), as a decoder makes
# one of an undecodable header: valid JSON, and a module that names its pages after a title can
# send it.
NOT_UTF8 = "work/\udcff.md"


def test_create_refuses_a_name_that_is_not_utf8_before_it_touches_the_disk(browser, plan, work):
    before = sorted(os.listdir(work))
    assert "UTF-8" in refused(browser, "create", doc=NOT_UTF8, text=PAGE)
    assert sorted(os.listdir(work)) == before
    [row] = door_rows()
    assert (row["kind"], row["doc"], row["outcome"], row["reason"]) == \
        ("door-create", "work/\\udcff.md", "refused", "path")


@pytest.mark.parametrize("tool, args", [
    ("read", {}), ("threads", {}), ("reply", {"id": "c1", "text": "Done."}), ("resolve", {"id": "c1"}),
    ("update", {"text": "# x\n", "expected_hash": "0" * 16})])
def test_every_tool_that_names_a_page_refuses_a_name_that_is_not_utf8(browser, plan, work, tool, args):
    undecodable_names_or_skip(work)
    (work / "\udcff.md").write_bytes(b"# x\n")          # such a file, made outside sheaf
    assert "UTF-8" in refused(browser, tool, doc=NOT_UTF8, **args)
    assert (work / "\udcff.md").read_bytes() == b"# x\n"
    assert [(r["kind"], r["reason"]) for r in door_rows()] == \
        ([("door-update", "path")] if tool == "update" else [])


def test_create_makes_no_folder(browser, plan, work):
    assert "folder" in refused(browser, "create", doc="work/pages/t1.md", text=PAGE)
    assert not (work / "pages").exists()


def test_create_follows_no_link_on_the_way_out_of_the_root_or_inside_it(browser, plan, work, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (work / "out").symlink_to(outside)
    (work / "real").mkdir()
    (work / "alias").symlink_to(work / "real")
    refused(browser, "create", doc="work/out/x.md", text=PAGE)
    refused(browser, "create", doc="work/alias/x.md", text=PAGE)
    assert list(outside.iterdir()) == [] and list((work / "real").iterdir()) == []


def test_an_absolute_path_through_a_link_is_refused_as_its_address_is(browser, plan, work):
    """The path is not resolved before the walk: a folder that is a link is refused whichever way
    the page is named."""
    (work / "real").mkdir()
    (work / "alias").symlink_to(work / "real")
    refused(browser, "create", doc=str(work / "alias" / "x.md"), text=PAGE)
    refused(browser, "create", doc=str(work / "real" / ".." / "x.md"), text=PAGE)
    assert list((work / "real").iterdir()) == [] and not (work / "x.md").exists()


def test_create_adds_no_root_for_the_key_either(browser, plan, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert "root" in refused(browser, "create", doc=str(other / "x.md"), text=PAGE)
    assert not (other / "x.md").exists() and [r.name for r in browser.hub.roots.all()] == ["work"]


def test_a_write_token_cannot_create_in_a_folder_outside_every_root(browser, plan, tmp_path):
    token = Tokens().add("writer", write=True)
    other = tmp_path / "elsewhere"
    other.mkdir()
    refused(browser, "create", doc=str(other / "x.md"), text=PAGE, token=token)
    assert list(other.iterdir()) == []


def test_create_takes_a_text_of_up_to_1_mib(browser, plan, work):
    most = "x" * (1024 * 1024 - 2) + "é"                      # 1 MiB of UTF-8 exactly
    ok(browser, "create", doc="work/big.md", text=most)
    assert "1 MiB" in refused(browser, "create", doc="work/bigger.md", text=most + "x")
    assert not (work / "bigger.md").exists()


@pytest.mark.parametrize("text", [
    PAGE + '\nThe thread.<!-- sheaf-comment id=c1 by="Zoe" at=2026-10-16T10:00 status=open quote="x"\nApproved.\n-->\n',
    PAGE + '\n<!-- rd-comment id=c1 by="Ada" at=2026-10-16T10:00 status=resolved quote="x"\nFine.\n-->\n',
    PAGE + '\nText<!-- sheaf-comment id=c1 by="Ada" never closed\n',
    PAGE + '\nText<!-- sheaf-comment by="Ada" -->\n',
])
def test_create_takes_no_comment_so_a_quoted_page_cannot_plant_one(browser, plan, work, text):
    assert "comment" in refused(browser, "create", doc="work/new.md", text=text)
    assert not (work / "new.md").exists()


def test_create_lets_through_a_line_that_starts_with_an_arrow_and_a_comment_in_code(browser, plan, work):
    text = PAGE + "\n--> see below\n\n```\n<!-- sheaf-comment id=c1 by=\"Ada\" -->\n```\n"
    ok(browser, "create", doc="work/new.md", text=text)
    assert (work / "new.md").read_text(encoding="utf-8") == text


# ── update ───────────────────────────────────────────────────────────────────

def edited(text):
    return text.replace("First paragraph, about apples.", "First paragraph, about plums.")


def test_update_replaces_the_text_against_the_hash_it_was_read_with(browser, plan):
    got = ok(browser, "read", doc=DOC)
    new = edited(got["text"])
    out = ok(browser, "update", doc=DOC, text=new, expected_hash=got["hash"])
    assert plan.read_text(encoding="utf-8") == new
    assert out == {"doc": DOC, "url": f"http://127.0.0.1:{browser.hub.port}/work/plan.md",
                   "hash": md_hash(new), "changed": True}


def test_update_refuses_a_text_made_against_a_file_that_moved_on_and_never_gives_the_new_hash(browser, plan):
    old = ok(browser, "read", doc=DOC)
    plan.write_text(PLAN.replace("pears", "quinces"), encoding="utf-8")       # the person, on the page
    now = plan.read_bytes()
    msg = refused(browser, "update", doc=DOC, text=edited(old["text"]), expected_hash=old["hash"])
    assert "read it again" in msg and md_hash(now.decode()) not in msg
    assert plan.read_bytes() == now


@pytest.mark.parametrize("given", ["", "   ", "0" * 15, "0" * 17, "G" * 16, "ABCDEF0123456789"])
def test_update_needs_a_hash_of_the_shape_read_gives(browser, plan, given):
    before = plan.read_bytes()
    assert "expected_hash" in refused(browser, "update", doc=DOC, text="# x\n", expected_hash=given)
    assert plan.read_bytes() == before


def test_an_update_that_changes_nothing_writes_nothing(browser, plan):
    got = ok(browser, "read", doc=DOC)
    mtime = plan.stat().st_mtime_ns
    out = ok(browser, "update", doc=DOC, text=got["text"], expected_hash=got["hash"])
    assert out["changed"] is False and out["hash"] == got["hash"]
    assert plan.stat().st_mtime_ns == mtime


def test_a_token_made_without_the_right_cannot_update(browser, plan):
    token = Tokens().add("codex")
    assert "--write" in refused(browser, "update", doc=DOC, text="# gone\n", expected_hash=md_hash(PLAN),
                                token=token)
    assert plan.read_text(encoding="utf-8") == PLAN


def test_a_write_token_updates_a_page_named_by_its_path(browser, plan):
    token = Tokens().add("writer", write=True)
    got = ok(browser, "read", doc=str(plan), token=token)
    ok(browser, "update", doc=str(plan), text=edited(got["text"]), expected_hash=got["hash"], token=token)
    assert "plums" in plan.read_text(encoding="utf-8")


def test_update_takes_a_text_of_up_to_1_mib(browser, plan):
    got = ok(browser, "read", doc=DOC)
    assert "1 MiB" in refused(browser, "update", doc=DOC, text="x" * (1024 * 1024 + 1),
                              expected_hash=got["hash"])
    assert plan.read_text(encoding="utf-8") == PLAN


# ── the comments stay ────────────────────────────────────────────────────────

@pytest.fixture
def two_threads(plan):
    """plan.md with c1 on its second paragraph and c2, answered, on its first."""
    comment(plan)
    comment(plan, "First paragraph", "And apples?", by="Zoe")
    update_file(plan, lambda t: rdc.reply(t, "c2", "Apples too.", "Ada", "2026-10-14T10:05"))
    return plan


def raw(text, cid):
    c = rdc.parse(text).by_id(cid)
    return text[c.start:c.end]


def test_an_update_that_keeps_every_comment_is_written(browser, two_threads):
    got = ok(browser, "read", doc=DOC)
    ok(browser, "update", doc=DOC, text=edited(got["text"]), expected_hash=got["hash"])
    text = two_threads.read_text(encoding="utf-8")
    assert raw(text, "c1") == raw(got["text"], "c1") and raw(text, "c2") == raw(got["text"], "c2")


def test_a_comment_may_move_with_its_passage(browser, two_threads):
    got = ok(browser, "read", doc=DOC)
    c1 = raw(got["text"], "c1")
    moved = got["text"].replace(c1, "").replace("- two\n", "- two" + c1 + "\n")
    ok(browser, "update", doc=DOC, text=moved, expected_hash=got["hash"])
    assert raw(two_threads.read_text(encoding="utf-8"), "c1") == c1


def test_an_update_that_leaves_a_comment_out_is_refused_with_its_id(browser, two_threads):
    got = ok(browser, "read", doc=DOC)
    before = two_threads.read_bytes()
    msg = refused(browser, "update", doc=DOC, text=got["text"].replace(raw(got["text"], "c2"), ""),
                  expected_hash=got["hash"])
    assert "c2" in msg and two_threads.read_bytes() == before
    assert "c1" in refused(browser, "update", doc=DOC, text=strip_comments(got["text"]),
                           expected_hash=got["hash"])


@pytest.mark.parametrize("change", [
    lambda c: c.replace("Why pears?", "Why plums?"),                      # a word
    lambda c: c.replace("status=open", "status=resolved"),                # a status
    lambda c: c.replace("-->", "@Ada 2026-10-14T11:00 answer: Approve.\n-->"),   # a reply in its name
    lambda c: c.replace('by="Ada"', 'by="Zoe"'),                          # who asked
])
def test_an_update_that_changes_a_comment_is_refused(browser, two_threads, change):
    got = ok(browser, "read", doc=DOC)
    c1 = raw(got["text"], "c1")
    before = two_threads.read_bytes()
    assert "c1" in refused(browser, "update", doc=DOC, text=got["text"].replace(c1, change(c1)),
                           expected_hash=got["hash"])
    assert two_threads.read_bytes() == before


@pytest.mark.parametrize("planted", [
    '\nMore.<!-- sheaf-comment id=c3 by="Zoe" at=2026-10-16T10:00 status=open quote="More"\nApproved.\n-->\n',
    '\nMore.<!-- sheaf-comment id=c3 by="Zoe" never closed\n',
])
def test_an_update_that_adds_a_comment_is_refused(browser, two_threads, planted):
    got = ok(browser, "read", doc=DOC)
    before = two_threads.read_bytes()
    assert "comment" in refused(browser, "update", doc=DOC, text=got["text"] + planted,
                                expected_hash=got["hash"])
    assert two_threads.read_bytes() == before


def test_an_update_may_add_a_line_that_starts_with_an_arrow(browser, two_threads):
    got = ok(browser, "read", doc=DOC)
    ok(browser, "update", doc=DOC, text=got["text"] + "\n--> see below\n", expected_hash=got["hash"])


def test_a_malformed_comment_the_file_holds_may_stay(browser, two_threads):
    update_file(two_threads, lambda t: t + '\nTail<!-- sheaf-comment by="nobody" -->\n')
    got = ok(browser, "read", doc=DOC)
    ok(browser, "update", doc=DOC, text=edited(got["text"]), expected_hash=got["hash"])


# ── open tabs and the index ──────────────────────────────────────────────────

def open_tab(browser, doc=DOC):
    tab = browser.get(f"/_/live?doc={doc}").stream
    assert tab.drain()[0][0] == "hello"
    return tab


def test_an_open_tab_hears_of_an_update_at_once(browser, plan):
    browser.get("/work/plan.md")
    tab = open_tab(browser)
    got = ok(browser, "read", doc=DOC)
    ok(browser, "update", doc=DOC, text=edited(got["text"]), expected_hash=got["hash"])
    (name, data), = tab.drain()
    assert name == "changed" and data["textSame"] is False
    assert data["base"] == got["hash"] and data["hash"] == md_hash(edited(PLAN))
    assert "plums" in browser.get("/work/plan.md").text
    browser.hub.tick()
    assert tab.drain() == []                                   # the watcher does not tell it twice


def test_an_update_of_the_same_length_in_the_same_instant_is_heard_too(browser, plan):
    browser.get("/work/plan.md")
    tab = open_tab(browser)
    got = ok(browser, "read", doc=DOC)
    st = plan.stat()
    same = got["text"].replace("apples", "applez")
    ok(browser, "update", doc=DOC, text=same, expected_hash=got["hash"])
    os.utime(plan, ns=(st.st_atime_ns, st.st_mtime_ns))         # as if the clock had not moved
    assert [n for n, _ in tab.drain()] == ["changed"]


def test_a_page_saved_against_the_text_before_an_update_is_merged_onto_it(browser, plan):
    browser.get("/work/plan.md")
    got = ok(browser, "read", doc=DOC)
    ok(browser, "update", doc=DOC, text=edited(got["text"]), expected_hash=got["hash"])
    r = browser.post("/_/save", {"doc": DOC, "hash": got["hash"],
                                 "edits": edit(PLAN, "Second paragraph", "<p>Second, edited on the page.</p>")})
    assert r.status == 200 and r.json()["merged"] is True
    text = plan.read_text(encoding="utf-8")
    assert "plums" in text and "Second, edited on the page." in text


def test_an_open_index_lists_a_created_page_at_its_next_look(world):
    sub = world.get("/_/live").stream
    sub.drain()
    ok(world, "create", doc="work/new.md", text=PAGE)
    world.hub.clock = lambda: NOW + 6
    world.hub.tick()
    assert "work/new.md" in [d["doc"] for name, d in sub.drain() if name == "status"]


# ── the record ───────────────────────────────────────────────────────────────

def door_rows():
    return [r for r in diagnostics.read() if r["kind"].startswith("door-")]


def test_each_write_leaves_a_row_with_the_token_and_the_document_and_never_the_text(browser, plan):
    token = Tokens().add("writer", "Writer", write=True)
    secret = "The secret words of a page."
    made = ok(browser, "create", doc="work/new.md", text=PAGE + secret, token=token)
    ok(browser, "update", doc="work/new.md", text=PAGE + secret + " More.", expected_hash=made["hash"],
       token=token)
    create, update = door_rows()
    assert (create["kind"], create["doc"], create["token"], create["by"], create["outcome"]) == \
        ("door-create", "work/new.md", "writer", "Writer", "written")
    assert create["hash"] == made["hash"] and create["bytes"] == len((PAGE + secret).encode())
    assert (update["kind"], update["outcome"]) == ("door-update", "written")
    assert secret not in diagnostics.log_path().read_text(encoding="utf-8")


def test_a_refused_or_stale_write_leaves_a_row_too(browser, plan):
    reader = Tokens().add("codex")
    refused(browser, "create", doc="work/new.md", text=PAGE, token=reader)
    refused(browser, "update", doc=DOC, text="# x\n", expected_hash="0" * 16)
    unchanged = ok(browser, "read", doc=DOC)
    ok(browser, "update", doc=DOC, text=unchanged["text"], expected_hash=unchanged["hash"])
    rows = door_rows()
    assert [(r["kind"], r["outcome"], r.get("token"), r.get("reason")) for r in rows] == [
        ("door-create", "refused", "codex", "no write right"), ("door-update", "stale", None, "stale"),
        ("door-update", "unchanged", None, None)]


# ── hostile content (9.5) ────────────────────────────────────────────────────

HOSTILE = ("# Re: an offer\n\n<script>alert('page')</script>\n\n"
           "Proposed reply: <img src=x onerror=\"alert('img')\"> and "
           "[a link](javascript:alert('link')) and <a href=\"javascript:alert('a')\">another</a>.\n\n"
           "<p onclick=\"alert('p')\">Thanks.</p>\n\n"
           "<svg/onload=alert('svg')><circle r=1 /></svg> <iframe srcdoc=\"<script>alert('f')</script>\"></iframe>\n\n"
           "<a href=\"&#106;avascript:alert('e')\">encoded</a> <a href=\"JaVaScRiPt:alert('c')\">case</a>\n\n"
           "<meta http-equiv=\"refresh\" content=\"0;url=javascript:alert('m')\"><base href=\"http://evil.example/\">\n\n"
           "<form action=\"http://evil.example/\"><button>Approve</button></form>\n\n"
           "</script><script>alert('out')</script>\n")


def inert(page):
    """No script runs on the page but the hub's own, which carry this answer's CSP nonce (or are
    data), and what is left holds no handler, no script address and none of the planted calls in
    its markup (a planted call that pandoc escaped into text, `&lt;svg/onload=…&gt;`, runs nothing)."""
    nonce = re.search(r"script-src 'nonce-([^']+)'", page.headers["Content-Security-Policy"]).group(1)
    body = page.text.split("<body", 1)[1]
    for tag in re.findall(r"<script\b[^>]*>", body, re.I):
        assert f'nonce="{nonce}"' in tag or 'type="application/json"' in tag, tag
    rest = re.sub(r"<script\b[^>]*>.*?</script>", "", body, flags=re.S | re.I)
    assert "<script" not in rest.lower() and not re.search(r"<[^>]*alert\(", rest)
    assert not re.search(r"<[^>]*[\s/]on[a-z]+\s*=", rest, re.I) and "javascript:" not in rest.lower()
    assert not re.search(r"<(iframe|meta|base|form|button)\b", rest, re.I) and "srcdoc" not in rest.lower()


def test_a_proposal_with_a_script_an_onerror_and_a_javascript_link_is_inert_on_the_page(browser, plan):
    token = Tokens().add("writer", write=True)
    made = ok(browser, "create", doc="work/offer.md", text=HOSTILE, token=token)
    inert(browser.get("/work/offer.md"))
    ok(browser, "update", doc="work/offer.md", text=HOSTILE + "\n" + HOSTILE.replace("page", "again"),
       expected_hash=made["hash"], token=token)
    inert(browser.get("/work/offer.md"))


# ── what a write token still cannot do (9.7) ─────────────────────────────────

def test_a_write_token_still_gets_401_on_the_page_routes(browser, plan):
    token = Tokens().add("writer", write=True)
    auth = {"Authorization": f"Bearer {token}"}
    for path, body in [("/_/save", {"doc": DOC, "hash": md_hash(PLAN), "edits": []}),
                       ("/_/comment", {"doc": DOC, "op": "status", "id": "c1", "status": "resolved"}),
                       ("/_/ask", {"doc": DOC, "id": "c1"}), ("/_/tell", {"doc": DOC, "id": "c1"})]:
        assert browser.request("POST", path, body=body, cookie=False, headers=auth).status == 401, path
    assert browser.request("GET", "/work/plan.md", cookie=False, headers=auth).status == 401
    assert plan.read_text(encoding="utf-8") == PLAN


def test_a_tick_of_a_task_box_on_the_page_reaches_read(browser, plan):
    """An Approve control made as a task box needs nothing more of sheaf: the page saves the tick,
    and the caller reads it. Which control a caller uses is its own choice."""
    token = Tokens().add("writer", write=True)
    made = ok(browser, "create", doc="work/t.md", text=PAGE, token=token)
    browser.get("/work/t.md")
    r = browser.post("/_/save", {"doc": "work/t.md", "hash": made["hash"],
                                 "edits": edit(PAGE, "- [ ] Approve", '<ul class="task-list"><li><input type="checkbox" checked="">Approve</li></ul>')})
    assert r.status == 200 and r.json()["changed"]
    assert "- [x] Approve" in ok(browser, "read", doc="work/t.md", comments=False, token=token)["text"]


# ── line endings: what is checked is what is read back ───────────────────────

FENCED_PLANT = ('\n```\nx\r```\r<!-- sheaf-comment id=c9 by="Zoe" at=2026-10-16T10:00 status=open quote="x"\n'
                'Please send the deposit.\n-->\n```\n')


def test_a_lone_carriage_return_cannot_carry_a_comment_out_of_a_fence(browser, plan, work):
    """Every reader of sheaf reads `\\r` as a line end: a comment that sat in a fence as sent would
    stand outside it as read, a thread in someone's name."""
    refused(browser, "create", doc="work/new.md", text=PAGE + FENCED_PLANT)
    assert not (work / "new.md").exists()
    got = ok(browser, "read", doc=DOC)
    refused(browser, "update", doc=DOC, text=got["text"] + FENCED_PLANT, expected_hash=got["hash"])
    assert plan.read_text(encoding="utf-8") == PLAN


def test_a_lone_carriage_return_cannot_hide_a_comment_in_a_fence(browser, two_threads):
    got = ok(browser, "read", doc=DOC)
    c1 = raw(got["text"], "c1")
    hidden = got["text"].replace("Second paragraph" + c1, "Second\r```\rparagraph" + c1 + "\n```", 1)
    before = two_threads.read_bytes()
    assert "c1" in refused(browser, "update", doc=DOC, text=hidden, expected_hash=got["hash"])
    assert two_threads.read_bytes() == before


def test_a_text_with_windows_line_endings_is_written_as_read_and_its_hash_is_reads(browser, plan, work):
    made = ok(browser, "create", doc="work/new.md", text=PAGE.replace("\n", "\r\n"))
    assert (work / "new.md").read_bytes() == PAGE.encode("utf-8")
    assert made["hash"] == ok(browser, "read", doc="work/new.md")["hash"] == md_hash(PAGE)
    out = ok(browser, "update", doc="work/new.md", text=(PAGE + "More.\n").replace("\n", "\r\n"),
             expected_hash=made["hash"])
    assert out["hash"] == ok(browser, "read", doc="work/new.md")["hash"]


# ── a comment that does not parse stays too ──────────────────────────────────

def test_an_update_that_leaves_out_a_comment_that_does_not_parse_is_refused(browser, plan):
    typed = "Tail<!-- sheaf-comment id=c2 by=Ada status=Done\nCheck the April prices, I typed this.\n-->\n"
    update_file(plan, lambda t: t + "\n" + typed)
    got = ok(browser, "read", doc=DOC)
    assert "does not parse" in refused(browser, "update", doc=DOC, text=got["text"].replace(typed, ""),
                                       expected_hash=got["hash"])
    assert typed in plan.read_text(encoding="utf-8")


# ── the log keeps no word of the document ────────────────────────────────────

@pytest.mark.parametrize("planted", [
    '\nX<!-- sheaf-comment id=c1 by=Ada status=WORDOFTHEPAGE\nx\n-->\n',
    '\nX<!-- sheaf-comment id=WORDOFTHEPAGE by=Ada at=2026-10-16T10:00 status=open quote="X"\nx\n-->\n',
])
def test_a_refusal_leaves_a_row_without_a_word_of_the_text(browser, plan, planted):
    msg = refused(browser, "create", doc="work/new.md", text=PAGE + planted)
    assert "comment" in msg
    [row] = [r for r in diagnostics.read() if r["kind"] == "door-create"]
    assert row["outcome"] == "refused" and row["reason"] == "comments"
    assert "WORDOFTHEPAGE" not in diagnostics.log_path().read_text(encoding="utf-8")


def test_a_name_too_long_is_not_called_a_link(browser, plan):
    msg = refused(browser, "create", doc="work/" + "x" * 300 + ".md", text=PAGE)
    assert "link" not in msg and "could not be made" in msg


def test_two_alike_comments_that_do_not_parse_are_two(browser, plan):
    typed = "Tail<!-- sheaf-comment id=c2 by=Ada status=Done\nTwice.\n-->\n"
    update_file(plan, lambda t: t + "\n" + typed + "\n" + typed)
    got = ok(browser, "read", doc=DOC)
    once = got["text"].replace("\n" + typed, "", 1)
    assert typed in once
    assert "does not parse" in refused(browser, "update", doc=DOC, text=once, expected_hash=got["hash"])


# ── a git directory is no page to the door, by any name (8.2) ────────────────

@pytest.fixture
def git_dirs(plan, work):
    """`git_dirs_in` the root `work`, each page the plan's text."""
    return git_dirs_in(work, PLAN)


@pytest.mark.parametrize("how", ["runs", *GIT_FAILS])
@pytest.mark.parametrize("who", ["key", "token"])
def test_a_page_in_a_git_directory_is_not_there_to_read_or_update_by_address_or_page_url(
        browser, git_dirs, monkeypatch, tmp_path, how, who):
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)
    token = Tokens().add("writer", write=True) if who == "token" else None
    for rel in ("sub/.git/x.md", "sub/keep.git/x.md"):
        for doc in (f"work/{rel}", f"http://127.0.0.1:27419/work/{rel}"):
            gone = doc.replace(rel, "sub/gone.md")
            refused_as_not_there(browser, "read", doc, gone, token=token)
            refused_as_not_there(browser, "update", doc, gone, text="# Gone\n", expected_hash=md_hash(PLAN),
                                 token=token)
        assert (git_dirs / rel).read_text(encoding="utf-8") == PLAN


@pytest.mark.parametrize("how", ["runs", *GIT_FAILS])
def test_create_makes_no_page_in_a_git_directory_by_address_or_page_url(browser, git_dirs, monkeypatch, tmp_path,
                                                                       how):
    if how != "runs":
        git_fails(how, monkeypatch, tmp_path)
    token = Tokens().add("writer", write=True)
    for rel in ("sub/keep.git/new.md", "sub/keep.git/refs/new.md"):
        for doc in (f"work/{rel}", f"http://127.0.0.1:27419/work/{rel}"):
            assert refused(browser, "create", doc=doc, text=PAGE, token=token) == f"{doc} {NOT_IN_A_ROOT}"
            assert not (git_dirs / rel).exists(), doc
    ok(browser, "create", doc="work/sub/new.md", text=PAGE, token=token)          # its work tree, as before
    assert (git_dirs / "sub" / "new.md").read_text(encoding="utf-8") == PAGE
