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
    assert set(types) == set(decl.insertable()) and "column" not in types     # a column is only a child
    assert got["containers"]["document"] == list(types)
    assert got["containers"]["callout"] == list(decl.CALLOUT.children)
    assert got["containers"]["columns"] == ["column"]
    assert "callout" not in got["containers"]["quote"]
    for name, kids in got["containers"].items():                   # a container only holds types that are declared
        assert set(kids) <= set(decl.PLAIN) | set(decl.DECLARED), name


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


def test_the_key_and_a_write_token_see_the_same_full_tree(browser, page):
    want = ok(browser, "blocks", doc=DOC)
    assert ok(browser, "blocks", doc=DOC, token=Tokens().add("writer", write=True)) == want


SECRET = "zqxmarker"
SECRET_TEXT = (
    f"# Head {SECRET}h\n\n"
    f"Para {SECRET}p\n\n"
    f'::: {{.callout tone="warning"}}\nCallout {SECRET}c\n\n- nested {SECRET}n\n:::\n\n'
    f"```py{SECRET}l\nprint('{SECRET}code')\n```\n\n"
    f"> Quote {SECRET}q\n\n"
    f"3. Third {SECRET}o\n4. Fourth\n\n"
    f"| a | b |\n|---|---|\n| {SECRET}t | 2 |\n\n"
    f"::: {{.widget{SECRET}w}}\nraw {SECRET}s\n:::\n"
)


def test_a_token_without_write_gets_the_structure_and_no_text_of_the_page(browser, plan):
    plan.write_text(SECRET_TEXT, encoding="utf-8")
    full = ok(browser, "blocks", doc=DOC)
    assert SECRET in json.dumps(full)                               # the fixture does put text in every type
    reader = Tokens().add("reader")
    got = ok(browser, "blocks", doc=DOC, token=reader)
    assert SECRET not in json.dumps(got)                            # nowhere: markdown, attrs, ids, children
    assert got["base"] == full["base"]

    def shape(rows):
        return [(r["id"], r["type"], r["capabilities"], shape(r["children"])) for r in rows]
    assert shape(got["blocks"]) == shape(full["blocks"])            # the same tree
    seen = set()

    def walk(rows):
        for r in rows:
            assert "markdown" not in r
            seen.add(r["type"])
            walk(r["children"])
    walk(got["blocks"])
    assert seen >= {"heading", "paragraph", "callout", "code", "quote", "list", "item", "table", "stub"}
    top = {b["type"]: b for b in got["blocks"]}
    assert top["callout"]["attrs"] == {"tone": "warning"}           # layout stays
    assert top["heading"]["attrs"] == {"level": 1}
    assert top["list"]["attrs"].get("ordered") is True
    assert top["code"]["attrs"] == {} and top["stub"]["attrs"] == {}
    for n in ids_only(top):                                         # asking by id gives the same, still no text
        got = ok(browser, "blocks", doc=DOC, ids=[n], token=reader)
        assert SECRET not in json.dumps(got)


def ids_only(top):
    return [b["id"] for b in top.values()]


def test_the_structural_attributes_are_chosen_per_type_in_one_place():
    assert decl.structural("callout", {"tone": "info", "align": "left", "pad": "m"}) == {
        "tone": "info", "align": "left", "pad": "m"}
    assert decl.structural("code", {"lang": "py"}) == {}
    assert decl.structural("stub", {"type": "x", "reason": "y"}) == {}
    assert decl.structural("heading", {"level": 2, "other": "t"}) == {"level": 2}


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


def test_an_empty_ids_list_asks_for_no_block(browser, page):
    got = ok(browser, "blocks", doc=DOC, ids=[])
    assert got["blocks"] == [] and got["base"] == md_hash(TEXT)


def test_a_nested_blocks_markdown_keeps_a_column_and_a_button(browser, plan):
    plan.write_text('::: {.columns}\n::: {.column size="50"}\nLeft [[Go](https://example.org/)]{.button size="m"} here.\n:::\n:::\n',
                    encoding="utf-8")
    col = ok(browser, "blocks", doc=DOC)["blocks"][0]["children"][0]
    assert col["type"] == "column" and col["markdown"].startswith('::: {.column size="50"}') and "<div" not in col["markdown"]
    assert '{.button size="m"}' in col["children"][0]["markdown"] and "<span" not in col["children"][0]["markdown"]
