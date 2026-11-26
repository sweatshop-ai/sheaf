"""The door's read tools `blocks` and `block_types` (block editor v1, ticket 14), through the in-memory `call()`."""
import json

import pytest

from helpers import call, ok, refused
from sheafmd import adapter as rda
from sheafmd import mcp
from sheafmd.blocks import declarations as decl
from sheafmd.blocks import read_tree
from sheafmd.document import DocumentService
from sheafmd.hub.state import Tokens
from sheafmd.source import md_hash

DOC = "work/plan.md"
TEXT = (
    "# Title\n\n"
    "Intro paragraph.\n\n"
    '::: {.callout tone="warning"}\n'
    "Inside the callout.\n\n"
    "- item one\n"
    "- item two\n"
    ":::\n\n"
    "```python\nprint(1)\n```\n\n"
    "::: {.widget}\nraw widget source\n:::\n\n"
    "Last paragraph.\n"
)


@pytest.fixture
def page(plan):
    plan.write_text(TEXT, encoding="utf-8")
    return plan


def top(got):
    return {b["type"]: b for b in got["blocks"]}


def test_blocks_returns_the_tree_with_the_base(browser, page):
    got = ok(browser, "blocks", doc=DOC)
    assert got["doc"] == DOC and got["base"] == md_hash(TEXT)
    tree = read_tree(TEXT)
    assert [b["id"] for b in got["blocks"]] == tree.ids          # the ids the Document service gives
    assert [b["type"] for b in got["blocks"]] == ["heading", "paragraph", "callout", "code", "stub", "paragraph"]
    assert sorted(got["blocks"][0]) == ["attrs", "capabilities", "children", "id", "markdown", "type"]
    assert got["blocks"][1]["markdown"] == "Intro paragraph."
    callout = top(got)["callout"]
    assert callout["attrs"] == {"tone": "warning"}
    assert callout["capabilities"] == ["edit", "move", "remove"]
    assert [c["type"] for c in callout["children"]] == ["paragraph", "list"]
    assert callout["children"][0]["markdown"] == "Inside the callout."
    assert [i["type"] for i in callout["children"][1]["children"]] == ["item", "item"]


def test_a_locked_block_shows_as_locked(browser, page):
    code = top(ok(browser, "blocks", doc=DOC))["code"]
    assert code["capabilities"] == ["move", "remove"]
    assert code["markdown"] == "```python\nprint(1)\n```"


def test_a_stub_shows_its_type_name_raw_source_and_only_move_and_remove(browser, page):
    stub = top(ok(browser, "blocks", doc=DOC))["stub"]
    assert stub["attrs"]["type"] == "widget"
    assert stub["markdown"] == "::: {.widget}\nraw widget source\n:::"
    assert stub["capabilities"] == ["move", "remove"] and stub["children"] == []


def test_depth_one_keeps_the_top_level_and_says_what_it_left_out(browser, page):
    got = ok(browser, "blocks", doc=DOC, depth=1)
    callout = top(got)["callout"]
    assert callout["children"] == [] and callout["more"] == 2
    assert got["base"] == md_hash(TEXT)
    assert "more" not in top(got)["paragraph"]


def test_depth_two_goes_one_level_down(browser, page):
    callout = top(ok(browser, "blocks", doc=DOC, depth=2))["callout"]
    assert [c["type"] for c in callout["children"]] == ["paragraph", "list"]
    assert callout["children"][1]["children"] == [] and callout["children"][1]["more"] == 2


def test_ids_return_only_those_blocks_wherever_they_sit_plus_the_base(browser, page):
    full = ok(browser, "blocks", doc=DOC)
    callout = top(full)["callout"]
    nested = callout["children"][0]["id"]
    got = ok(browser, "blocks", doc=DOC, ids=[callout["id"], nested])
    assert [b["id"] for b in got["blocks"]] == [callout["id"], nested]
    assert got["base"] == full["base"]
    only = ok(browser, "blocks", doc=DOC, ids=[nested], depth=1)
    assert [b["markdown"] for b in only["blocks"]] == ["Inside the callout."]


def test_an_unknown_id_is_refused_by_name(browser, page):
    assert "nope" in refused(browser, "blocks", doc=DOC, ids=["nope"])


def test_bad_arguments_are_refused(browser, page):
    refused(browser, "blocks", doc=DOC, depth=0)
    refused(browser, "blocks", doc=DOC, depth="2")
    refused(browser, "blocks", doc=DOC, ids="abc")
    refused(browser, "blocks", doc=DOC, ids=[1])


def test_a_document_that_is_not_there_is_refused(browser, page):
    refused(browser, "blocks", doc="work/none.md")
    refused(browser, "block_types", doc="work/none.md")


def test_both_tools_are_read_only_and_open_to_a_token_that_cannot_write(browser, page):
    token = Tokens().add("codex")
    assert ok(browser, "blocks", doc=DOC, token=token)["base"] == md_hash(TEXT)
    assert ok(browser, "block_types", doc=DOC, token=token)["types"]
    for n in ("blocks", "block_types"):
        assert mcp.TOOLS[n]["annotations"] == {"readOnlyHint": True}
        assert n not in mcp.PAGE_TOOLS and n not in mcp.WRITE_TOOLS and n not in mcp.SESSION_WRITES
    assert page.read_text(encoding="utf-8") == TEXT                # nothing was written


def test_a_token_that_may_not_see_the_page_is_told_it_is_not_there(browser, page):
    token = Tokens().add("codex")
    assert refused(browser, "blocks", doc="work/none.md", token=token) == refused(
        browser, "blocks", doc="work/none.md")


def test_block_types_matches_the_declarations(browser, page):
    got = ok(browser, "block_types", doc=DOC)
    assert got["doc"] == DOC
    types = {t["type"]: t for t in got["types"]}
    callout = types["callout"]
    assert callout["attributes"] == [
        {"name": a.name, "values": list(a.values), "default": a.default} for a in decl.CALLOUT.attrs]
    assert set(types) >= set(decl.PLAIN) | set(decl.DECLARED)
    assert got["containers"]["document"] == list(types)
    assert got["containers"]["callout"] == [t for t in decl.CALLOUT.children if t in types]
    assert "callout" not in got["containers"]["quote"]
    assert "box" not in got["containers"]["callout"]               # declared as a child, not yet a Block type


def test_every_example_block_types_gives_is_accepted_by_the_document_service(browser, page, tmp_path):
    got = ok(browser, "block_types", doc=DOC)
    for t in got["types"]:
        p = tmp_path / f"{t['type']}.md"
        p.write_text("Start.\n", encoding="utf-8")
        svc = DocumentService(rda.MarkdownFileAdapter(p))
        tree, base = svc.read()
        out = svc.save("Start.\n\n" + t["example"] + "\n", [tree.blocks[0].id, None], base, "s1")
        assert out["outcome"] == "written", (t["type"], out)
        added = read_tree(p.read_text(encoding="utf-8")).blocks[-1]
        assert added.type == t["type"], (t["type"], added.type)
        assert "\n" not in t["description"] and t["description"]


def test_the_key_and_a_write_token_see_the_same_tree_as_a_read_only_token(browser, page):
    want = ok(browser, "blocks", doc=DOC)
    assert ok(browser, "blocks", doc=DOC, token=Tokens().add("writer", write=True)) == want
    assert ok(browser, "blocks", doc=DOC, token=Tokens().add("reader")) == want


def test_a_rich_block_that_breaks_its_declaration_is_a_stub_with_only_move_and_remove(browser, plan):
    plan.write_text('Before.\n\n::: {.callout tone="purple"}\nBad tone.\n:::\n', encoding="utf-8")
    stub = ok(browser, "blocks", doc=DOC)["blocks"][1]
    assert stub["type"] == "stub" and stub["attrs"]["type"] == "callout"
    assert stub["markdown"] == '::: {.callout tone="purple"}\nBad tone.\n:::'
    assert stub["capabilities"] == ["move", "remove"]


def test_the_attributes_block_types_declares_are_the_ones_blocks_reports(browser, plan):
    plan.write_text("## Head\n\n1. one\n\n```py\nx\n```\n", encoding="utf-8")
    rows = {b["type"]: b for b in ok(browser, "blocks", doc=DOC)["blocks"]}
    declared = {t["type"]: {a["name"]: a for a in t["attributes"]} for t in ok(browser, "block_types", doc=DOC)["types"]}
    assert rows["heading"]["attrs"]["level"] in declared["heading"]["level"]["values"]
    assert rows["list"]["attrs"]["ordered"] in declared["list"]["ordered"]["values"]
    assert set(declared["code"]) == {"lang"} and "lang" in rows["code"]["attrs"]
