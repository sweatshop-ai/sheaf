"""The block editor on the page (ticket 07, ADR 0003, SPEC 10.3): TipTap on the plain blocks, the Markdown it writes, and the autosave.

Run in CI and on t-compute, never on the laptop."""
import pytest

from pagehelp import key, until, rewrite

pytestmark = pytest.mark.page

DOC = "#rd-be .ProseMirror"
TOGGLE = "#rd-mode button"
# A sample the converter spells back byte for byte, with one block of each plain kind and a block it keeps raw.
SAMPLE = """---
title: Sample
---

# Rectoverso sample

A paragraph with **bold**, *italic*, `code` and a [link](https://example.com/a "tip").

## Lists

- one
- two
  - nested

1. first
2. second

> A quote
> over two lines.

| Name | Value |
| --- | --- |
| a | 1 |
| b | 2 |

```python
print("kept")
```

---

::: {#note .callout tone="info"}
A block the editor does not read stays as it is.
:::

Last paragraph.
"""


@pytest.fixture
def flag(monkeypatch):
    monkeypatch.setenv("SHEAF_BLOCK_EDITOR", "1")      # read when the hub starts, so before the `site` fixture builds it


@pytest.fixture
def doc(flag, tab, site):
    return tab


def text(site):
    return site.file.read_text(encoding="utf-8")


def open_editor(tab, site):
    rewrite(site.file, SAMPLE)
    tab.open()
    tab.page.click(TOGGLE)
    tab.page.wait_for_selector(DOC)
    return tab.page


RECORD = """(() => {
  const real = window.fetch; window.__saves = [];
  window.fetch = function (url, init) {
    const p = real.apply(this, arguments);
    if (String(url).endsWith('/_/save')) p.then((r) => r.clone().json()).then((j) => window.__saves.push(j), () => {});
    return p;
  };
})()"""


def server_saves(page):
    """The JSON answers of `/_/save` the page has had, in order (recorded in the page: a response read later is gone from the driver)."""
    page.evaluate(RECORD)
    return lambda: page.evaluate("window.__saves")


def test_the_editor_opens_on_the_documents_blocks_and_writes_them_back_byte_for_byte(doc, site):
    p = open_editor(doc, site)
    assert p.evaluate("window.sheafBlockEditor.last.markdown()") == SAMPLE
    assert p.evaluate("window.sheafBlockEditor.last.freshMarkdown()") == SAMPLE      # the converter alone, not the kept source
    assert text(site) == SAMPLE


def test_typing_in_a_paragraph_saves_by_itself_and_changes_only_that_paragraph(doc, site):
    p = open_editor(doc, site)
    p.click(f"{DOC} p >> text=Last paragraph.")
    p.keyboard.press(key("End"))
    p.keyboard.type(" Typed.")
    until(lambda: text(site) != SAMPLE, timeout=10, what="the autosave")
    assert text(site) == SAMPLE.replace("Last paragraph.", "Last paragraph. Typed.")


def test_enter_splits_a_paragraph_backspace_joins_it_and_ctrl_z_undoes(doc, site):
    p = open_editor(doc, site)
    p.click(f"{DOC} p >> text=Last paragraph.")
    p.keyboard.press(key("End"))
    for _ in range(len("paragraph.")):
        p.keyboard.press("ArrowLeft")
    p.keyboard.press("Backspace")                    # the space before "paragraph."
    p.keyboard.press("Enter")
    assert p.evaluate("window.sheafBlockEditor.last.markdown()").endswith("Last\n\nparagraph.\n")
    p.keyboard.press("Backspace")
    assert p.evaluate("window.sheafBlockEditor.last.markdown()").endswith("Lastparagraph.\n")
    p.keyboard.press(key("Control+z"))
    assert p.evaluate("window.sheafBlockEditor.last.markdown()") != SAMPLE.replace("Last paragraph.", "Lastparagraph.")
    for _ in range(4):                               # the history may group the keys; it ends on the text as it was
        p.keyboard.press(key("Control+z"))
    assert p.evaluate("window.sheafBlockEditor.last.markdown()") == SAMPLE


def test_two_quick_saves_of_the_page_never_conflict_with_each_other(doc, site):
    p = open_editor(doc, site)
    answers = server_saves(p)
    p.click(f"{DOC} p >> text=Last paragraph.")
    p.keyboard.press(key("End"))
    p.keyboard.type(" a")
    p.keyboard.press(key("Control+s"))
    p.keyboard.type("b")
    p.keyboard.press(key("Control+s"))           # the first answer need not have come back
    until(lambda: len(answers()) >= 2, timeout=10, what="both saves answered")
    assert [a["conflict"] for a in answers()] == [False, False]
    assert text(site) == SAMPLE.replace("Last paragraph.", "Last paragraph. ab")


def test_a_writer_outside_the_page_between_its_saves_is_a_conflict_and_the_file_keeps_their_text(doc, site):
    p = open_editor(doc, site)
    answers = server_saves(p)
    p.click(f"{DOC} p >> text=Last paragraph.")
    p.keyboard.press(key("End"))
    p.keyboard.type(" mine")
    p.keyboard.press(key("Control+s"))
    until(lambda: len(answers()) >= 1, timeout=10, what="the first save")
    theirs = text(site).replace("# Rectoverso sample", "# Rectoverso, theirs")
    rewrite(site.file, theirs)
    p.keyboard.type(" more")                    # text the file does not hold: the page keeps its editor open
    p.keyboard.press(key("Control+s"))
    until(lambda: len(answers()) >= 2, timeout=10, what="the second save")
    assert answers()[1]["conflict"] is True
    assert text(site) == theirs


def test_a_block_the_editor_does_not_read_is_shown_as_it_is_and_never_rewritten(doc, site):
    p = open_editor(doc, site)
    assert p.locator(f"{DOC} pre.sheaf-raw").count() >= 2         # the front matter and the fenced div
    p.click(f"{DOC} p >> text=Last paragraph.")
    p.keyboard.type("X")
    until(lambda: text(site) != SAMPLE, timeout=10, what="the autosave")
    assert '::: {#note .callout tone="info"}\nA block the editor does not read stays as it is.\n:::\n' in text(site)
    assert text(site).startswith("---\ntitle: Sample\n---\n")
