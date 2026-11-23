"""A page a job generates (SPEC 8.3, 9.7, 12): the door's `create` and `update` set the mark, `read` shows it,
and only the token that set it, or the key, may update the page or clear the mark."""
import pytest
from helpers import comment, door, ok, refused, rpc

from sheafmd.beneath import Opened
from sheafmd.hub.state import Tokens

DOC = "work/plan.md"


def edited(text, word="plums"):
    return text.replace("First paragraph, about apples.", f"First paragraph, about {word}.")


def generate(browser, token, word="plums", **kw):
    got = ok(browser, "read", doc=DOC, token=token)
    return ok(browser, "update", doc=DOC, text=edited(got["text"], word), expected_hash=got["hash"], token=token, **kw)


def test_a_page_never_generated_reads_with_no_mark_and_an_old_docs_file_loads(browser, plan):
    browser.hub.docs.put(DOC, {"path": str(plan), "rendered": "2026-11-01T10:00:00+0100", "title": None, "toc": "auto",
                               "target": None})     # an entry as an older hub wrote it
    assert "generated" not in browser.hub.docs.get(DOC)
    assert ok(browser, "read", doc=DOC)["generated"] is None


def test_update_with_generated_true_marks_the_page_and_names_the_setting_token(browser, plan):
    token = Tokens().add("builder", write=True)
    generate(browser, token, generated=True)
    mark = browser.hub.docs.get(DOC)["generated"]
    assert mark["by"] == "builder" and mark["id"] == token.id and mark["at"]
    shown = ok(browser, "read", doc=DOC)["generated"]
    assert shown == {"by": "builder", "at": mark["at"]}


def test_create_with_generated_true_marks_the_new_page(browser, plan, work):
    token = Tokens().add("builder", write=True)
    ok(browser, "create", doc="work/made.md", text="# Made\n\nBy a job.\n", generated=True, token=token)
    assert browser.hub.docs.get("work/made.md")["generated"]["by"] == "builder"


def test_another_write_token_cannot_update_a_generated_page(browser, plan):
    setter = Tokens().add("builder", write=True)
    other = Tokens().add("other", write=True)
    generate(browser, setter, generated=True)
    got = ok(browser, "read", doc=DOC, token=other)
    before = plan.read_text(encoding="utf-8")
    said = refused(browser, "update", doc=DOC, text=edited(got["text"], "figs"), expected_hash=got["hash"], token=other)
    assert "builder" in said and "Comment" in said
    assert plan.read_text(encoding="utf-8") == before


def test_the_setting_token_and_the_key_may_update_a_generated_page(browser, plan):
    setter = Tokens().add("builder", write=True)
    generate(browser, setter, generated=True)
    generate(browser, setter, "figs")
    got = ok(browser, "read", doc=DOC)
    ok(browser, "update", doc=DOC, text=edited(got["text"], "pears"), expected_hash=got["hash"])     # the key
    assert "pears" in plan.read_text(encoding="utf-8")


def test_clearing_the_mark_is_the_setters_or_the_keys_alone(browser, plan):
    setter = Tokens().add("builder", write=True)
    other = Tokens().add("other", write=True)
    generate(browser, setter, generated=True)
    got = ok(browser, "read", doc=DOC, token=other)
    refused(browser, "update", doc=DOC, text=got["text"], expected_hash=got["hash"], generated=False, token=other)
    assert ok(browser, "read", doc=DOC)["generated"]["by"] == "builder"
    ok(browser, "update", doc=DOC, text=got["text"], expected_hash=got["hash"], generated=False, token=setter)
    assert ok(browser, "read", doc=DOC)["generated"] is None
    assert "generated" not in browser.hub.docs.get(DOC)
    generate(browser, other, "kiwis")                         # no mark: any write token again


def test_a_later_update_that_leaves_generated_out_keeps_the_mark(browser, plan):
    setter = Tokens().add("builder", write=True)
    generate(browser, setter, generated=True)
    generate(browser, setter, "figs")
    assert ok(browser, "read", doc=DOC)["generated"]["by"] == "builder"


def test_a_revoked_setter_leaves_the_mark_and_only_the_key_clears_it(browser, plan):
    setter = Tokens().add("builder", write=True)
    other = Tokens().add("other", write=True)
    generate(browser, setter, generated=True)
    assert Tokens().revoke("builder")
    got = ok(browser, "read", doc=DOC, token=other)
    refused(browser, "update", doc=DOC, text=got["text"], expected_hash=got["hash"], generated=False, token=other)
    again = Tokens().add("builder", write=True)               # the same name, a token of its own: it inherits nothing
    refused(browser, "update", doc=DOC, text=edited(got["text"], "figs"), expected_hash=got["hash"], token=again)
    ok(browser, "update", doc=DOC, text=got["text"], expected_hash=got["hash"], generated=False)       # the key
    assert ok(browser, "read", doc=DOC)["generated"] is None


def test_an_update_of_a_generated_page_still_keeps_every_comment(browser, plan):
    comment(plan)
    setter = Tokens().add("builder", write=True)
    generate(browser, setter, generated=True)
    got = ok(browser, "read", doc=DOC, token=setter)
    stripped = got["text"].replace(got["text"][got["text"].index("<!-- sheaf-comment"):], "")
    refused(browser, "update", doc=DOC, text=stripped, expected_hash=got["hash"], token=setter)


def test_tools_list_shows_generated_on_create_and_update(browser):
    res = door(browser, rpc("tools/list")).json()
    tools = {t["name"]: t for t in res["result"]["tools"]}
    for name in ("create", "update"):
        assert tools[name]["inputSchema"]["properties"]["generated"]["type"] == "boolean"
    assert "generated" not in tools["update"]["inputSchema"].get("required", [])


def test_generated_must_be_true_or_false(browser, plan):
    got = ok(browser, "read", doc=DOC)
    assert "true or false" in refused(browser, "update", doc=DOC, text=got["text"], expected_hash=got["hash"],
                                      generated="yes")


def test_a_render_of_the_page_keeps_the_mark(browser, plan):
    setter = Tokens().add("builder", write=True)
    generate(browser, setter, generated=True)
    browser.hub.render(plan, {"title": "Plan"}, None)
    assert browser.hub.docs.get(DOC)["generated"]["by"] == "builder"


def test_a_page_the_key_marks_has_no_token_as_its_setter(browser, plan):
    got = ok(browser, "read", doc=DOC)
    ok(browser, "update", doc=DOC, text=got["text"], expected_hash=got["hash"], generated=True)
    same_name = Tokens().add("Claude", write=True)          # the key signs as `Claude`: a token of that name is not it
    refused(browser, "update", doc=DOC, text=edited(got["text"]), expected_hash=got["hash"], token=same_name)
    ok(browser, "update", doc=DOC, text=edited(got["text"]), expected_hash=got["hash"])


def test_a_mark_set_by_a_token_with_no_id_is_not_inherited_by_a_token_made_since(browser, plan):
    browser.hub.docs.put(DOC, {"path": str(plan), "generated": {"by": "old", "id": None, "at": "2026-11-01T10:00:00+0100"}})
    made_since = Tokens().add("old", write=True)             # the same name; it has an id, the old row had none
    got = ok(browser, "read", doc=DOC)
    refused(browser, "update", doc=DOC, text=edited(got["text"]), expected_hash=got["hash"], token=made_since)


def a_failing_write(monkeypatch):
    def refuse(self, text):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(Opened, "write", refuse)


@pytest.mark.parametrize("marked", [True, False], ids=["clearing", "setting"])
def test_an_update_whose_write_fails_leaves_the_mark_as_it_was(browser, plan, monkeypatch, marked):
    """The mark is set before the text is written, so a page is never changed and unmarked; a write that then fails
    puts it back (ticket 183 Z)."""
    setter = Tokens().add("builder", write=True)
    if marked:
        generate(browser, setter, generated=True)
    before = browser.hub.docs.get(DOC).get("generated")
    a_failing_write(monkeypatch)
    got = ok(browser, "read", doc=DOC, token=setter)
    refused(browser, "update", doc=DOC, text=got["text"] + "\nA last line.\n", expected_hash=got["hash"],
            generated=not marked, token=setter)
    assert browser.hub.docs.get(DOC).get("generated") == before


def test_a_create_whose_mark_cannot_be_written_leaves_no_page_and_may_be_sent_again(browser, plan, work, monkeypatch):
    """`docs.json` refuses the mark: the create is refused with nothing made, so the same create succeeds once it can
    be written (ticket 183 AA)."""
    token = Tokens().add("builder", write=True)
    change = browser.hub.docs.change

    def refuse_the_mark(address, settle):
        if "generated" in settle({}):
            raise OSError(28, "No space left on device")
        return change(address, settle)
    monkeypatch.setattr(browser.hub.docs, "change", refuse_the_mark)
    said = refused(browser, "create", doc="work/made.md", text="# Made\n\nBy a job.\n", generated=True, token=token)
    assert "not made" in said
    assert not (work / "made.md").exists()
    monkeypatch.setattr(browser.hub.docs, "change", change)
    ok(browser, "create", doc="work/made.md", text="# Made\n\nBy a job.\n", generated=True, token=token)
    assert browser.hub.docs.get("work/made.md")["generated"]["by"] == "builder"
