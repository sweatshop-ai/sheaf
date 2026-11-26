"""The block editor's hub side (SPEC 4.3, 8.5): the flag, `GET /_/blocks`, `GET /_/editor.js` and the Markdown form of `/_/save`."""
import pytest

from helpers import page_meta
from sheafmd import config
from sheafmd.hub import assets
from sheafmd.source import md_hash

DOC = "work/plan.md"
URL = "/work/plan.md"
TEXT = "# Plan\n\nOne.\n\nTwo.\n\n- a\n- b\n"


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("SHEAF_BLOCK_EDITOR", "1")


@pytest.fixture
def doc(plan):
    plan.write_text(TEXT, encoding="utf-8")
    return plan


def save(browser, text, base, ids, session="page-1", rid=None):
    r = browser.post("/_/save", {"doc": DOC, "hash": base, "markdown": text, "ids": ids, "session": session,
                                 **({"rid": rid} if rid else {})})
    return r


# ── the flag ─────────────────────────────────────────────────────────────────

def test_the_flag_is_off_by_default_and_the_env_turns_it_on_or_off(monkeypatch, sheaf_env):
    monkeypatch.delenv("SHEAF_BLOCK_EDITOR", raising=False)
    assert config.block_editor() is False
    monkeypatch.setenv("SHEAF_BLOCK_EDITOR", "1")
    assert config.block_editor() is True
    monkeypatch.setenv("SHEAF_BLOCK_EDITOR", "0")
    assert config.block_editor() is False


def test_the_config_file_turns_the_flag_on_and_the_env_overrides_it(monkeypatch, sheaf_env):
    from sheafmd import paths
    monkeypatch.delenv("SHEAF_BLOCK_EDITOR", raising=False)
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text("block_editor = true\n", encoding="utf-8")
    assert config.block_editor() is True
    monkeypatch.setenv("SHEAF_BLOCK_EDITOR", "false")
    assert config.block_editor() is False


def test_with_the_flag_off_the_meta_has_no_editor_key_and_the_routes_refuse(browser, doc):
    assert "blockEditor" not in page_meta(browser.get(URL).text)
    assert browser.get(f"/_/blocks?doc={DOC}").status >= 400
    assert save(browser, TEXT, md_hash(TEXT), []).status >= 400


def test_with_the_flag_on_the_meta_names_the_bundle_by_its_tag(on, browser, doc):
    meta = page_meta(browser.get(URL).text)
    assert meta["blockEditor"] == browser.hub.editor_asset.tag


# ── the bundle ───────────────────────────────────────────────────────────────

def test_the_bundle_is_served_with_a_year_of_cache_when_asked_by_its_tag(on, browser):
    tag = browser.hub.editor_asset.tag
    r = browser.get(f"/_/editor.js?v={tag}")
    assert r.status == 200 and r.headers["Content-Type"].startswith("text/javascript")
    assert "immutable" in r.headers["Cache-Control"]
    assert r.body == assets.editor_bundle().body
    assert browser.get("/_/editor.js?v=old").headers["Cache-Control"] == "no-store"


# ── the blocks ───────────────────────────────────────────────────────────────

def test_the_blocks_are_the_documents_top_level_blocks_with_their_ids_and_the_hash(on, browser, doc):
    j = browser.get(f"/_/blocks?doc={DOC}").json()
    assert j["hash"] == md_hash(TEXT)
    assert [b["type"] for b in j["blocks"]] == ["heading", "paragraph", "paragraph", "list"]
    assert "".join(b["content"] + b["gap"] for b in j["blocks"]) == j["lead"] + TEXT[len(j["lead"]):]
    assert len({b["id"] for b in j["blocks"]}) == 4


# ── the save ─────────────────────────────────────────────────────────────────

def test_a_markdown_save_writes_the_file_and_answers_with_the_new_hash(on, browser, doc):
    j = browser.get(f"/_/blocks?doc={DOC}").json()
    ids = [b["id"] for b in j["blocks"]]
    new = TEXT.replace("One.", "One, edited.")
    r = save(browser, new, j["hash"], ids).json()
    assert r["changed"] is True and r["conflict"] is False and r["hash"] == md_hash(new)
    assert doc.read_text(encoding="utf-8") == new


def test_a_markdown_save_of_the_same_text_changes_nothing(on, browser, doc):
    j = browser.get(f"/_/blocks?doc={DOC}").json()
    r = save(browser, TEXT, j["hash"], [b["id"] for b in j["blocks"]]).json()
    assert r["changed"] is False and r["conflict"] is False
    assert doc.read_text(encoding="utf-8") == TEXT


def test_two_quick_saves_of_one_page_never_conflict_with_each_other(on, browser, doc):
    j = browser.get(f"/_/blocks?doc={DOC}").json()
    ids = [b["id"] for b in j["blocks"]]
    a = TEXT.replace("One.", "One, a.")
    b = a.replace("Two.", "Two, b.")
    ra = save(browser, a, j["hash"], ids, rid="request-one-0000000").json()
    rb = save(browser, b, j["hash"], ids, rid="request-two-0000000").json()            # the page sent it before a's answer came back
    assert ra["conflict"] is False and rb["conflict"] is False
    assert doc.read_text(encoding="utf-8") == b


def test_a_save_of_the_same_request_id_is_answered_again_and_written_once(on, browser, doc):
    j = browser.get(f"/_/blocks?doc={DOC}").json()
    ids = [b["id"] for b in j["blocks"]]
    new = TEXT.replace("One.", "One, a.")
    first = save(browser, new, j["hash"], ids, rid="request-same-000000").json()
    again = save(browser, new, j["hash"], ids, rid="request-same-000000").json()
    assert again.pop("again") is True and again == first and doc.read_text(encoding="utf-8") == new


def test_another_page_on_the_old_base_is_a_conflict_and_the_file_is_left_as_it_is(on, browser, doc):
    j = browser.get(f"/_/blocks?doc={DOC}").json()
    ids = [b["id"] for b in j["blocks"]]
    a = TEXT.replace("One.", "One, a.")
    save(browser, a, j["hash"], ids, session="page-1")
    r = save(browser, TEXT.replace("One.", "One, theirs."), j["hash"], ids, session="page-2").json()
    assert r["conflict"] is True and r["changed"] is False
    assert doc.read_text(encoding="utf-8") == a


@pytest.mark.parametrize("body", [{"markdown": 1}, {"markdown": "x", "ids": "no"}, {"markdown": "x", "ids": [1]},
                                  {"markdown": "x", "ids": [], "session": 5}, {"markdown": "x", "ids": [], "session": "s" * 65}])
def test_a_malformed_markdown_save_is_refused_with_a_4xx(on, browser, doc, body):
    r = browser.post("/_/save", {"doc": DOC, "hash": md_hash(TEXT), **body})
    assert 400 <= r.status < 500
    assert doc.read_text(encoding="utf-8") == TEXT


def test_a_comment_written_while_the_page_edits_is_not_a_conflict_and_survives_the_save(on, browser, doc):
    import sheafmd.comments as rdc
    j = browser.get(f"/_/blocks?doc={DOC}").json()
    ids = [b["id"] for b in j["blocks"]]
    blk, s, e = rdc.find_quote(TEXT, "Two.")
    c = browser.post("/_/comment", {"doc": DOC, "op": "add", "hash": j["hash"], "block": blk, "start": s, "end": e,
                                    "quote": "Two.", "body": "Why?"}).json()
    assert c.get("hash") and c["hash"] != j["hash"]
    r = save(browser, TEXT.replace("One.", "One, edited."), j["hash"], ids).json()
    assert r["conflict"] is False
    now = doc.read_text(encoding="utf-8")
    assert "One, edited." in now and "Why?" in now




def test_a_page_that_saved_before_a_comment_and_saves_again_after_it_is_not_a_conflict(on, browser, doc):
    import sheafmd.comments as rdc
    j = browser.get(f"/_/blocks?doc={DOC}").json()
    ids = [b["id"] for b in j["blocks"]]
    a = TEXT.replace("One.", "One, a.")
    first = save(browser, a, j["hash"], ids).json()
    blk, s, e = rdc.find_quote(doc.read_text(encoding="utf-8"), "Two.")
    browser.post("/_/comment", {"doc": DOC, "op": "add", "hash": first["hash"], "block": blk, "start": s, "end": e,
                                "quote": "Two.", "body": "Why?"})
    r = save(browser, a.replace("One, a.", "One, b."), j["hash"], ids).json()
    assert r["conflict"] is False
    now = doc.read_text(encoding="utf-8")
    assert "One, b." in now and "Why?" in now


def test_a_comment_survives_every_save_of_a_page_that_never_heard_of_it(on, browser, doc):
    import sheafmd.comments as rdc
    j = browser.get(f"/_/blocks?doc={DOC}").json()
    ids = [b["id"] for b in j["blocks"]]
    a = TEXT.replace("One.", "One, a.")
    first = save(browser, a, j["hash"], ids).json()
    blk, s, e = rdc.find_quote(doc.read_text(encoding="utf-8"), "Two.")
    browser.post("/_/comment", {"doc": DOC, "op": "add", "hash": first["hash"], "block": blk, "start": s, "end": e,
                                "quote": "Two.", "body": "Why?"})
    for word in ("b", "c", "d"):
        r = save(browser, a.replace("One, a.", f"One, {word}."), j["hash"], ids).json()
        assert r["conflict"] is False
        now = doc.read_text(encoding="utf-8")
        assert f"One, {word}." in now and "Why?" in now


def test_a_markdown_save_that_breaks_a_callout_is_a_409_and_the_file_is_unchanged(on, browser, plan):
    text = 'Intro.\n\n::: {#c1 .callout tone="warning"}\nBe careful.\n:::\n'
    plan.write_text(text, encoding="utf-8")
    j = browser.get(f"/_/blocks?doc={DOC}").json()
    ids = [b["id"] for b in j["blocks"]]
    r = save(browser, text.replace('tone="warning"', 'tone="warning" onclick="x"'), j["hash"], ids)
    assert r.status == 409 and "refused" in r.text
    assert plan.read_text(encoding="utf-8") == text
