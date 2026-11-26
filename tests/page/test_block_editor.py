"""The block editor on the page (ticket 07, ADR 0003, SPEC 10.3): TipTap on the plain blocks, the Markdown it writes, and the autosave.

Run in CI, never on the laptop."""
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


def test_enter_in_a_table_cell_is_a_line_break_and_the_text_after_it_is_saved(doc, site):
    p = open_editor(doc, site)
    p.click(f"{DOC} td >> text=a")
    p.keyboard.press(key("End"))
    p.keyboard.press("Enter")
    p.keyboard.type("more")
    until(lambda: "more" in text(site), timeout=10, what="the autosave")
    assert text(site) == SAMPLE.replace("| a | 1 |", "| a<br>more | 1 |")
    p.reload()
    p.click(TOGGLE)
    p.wait_for_selector(DOC)
    assert p.evaluate("window.sheafBlockEditor.last.freshMarkdown()") == text(site)      # `<br>` reads back as the line break


def test_a_table_cell_with_a_line_break_opens_as_a_table_and_stays_editable(doc, site):
    rewrite(site.file, SAMPLE.replace("| a | 1 |", "| a<br>more | 1 |"))
    doc.open()
    doc.page.click(TOGGLE)
    doc.page.wait_for_selector(DOC)
    p = doc.page
    assert p.locator(f"{DOC} td").count() == 4          # the table is a table, not a block shown as it is
    p.click(f"{DOC} td >> text=more")
    p.keyboard.press(key("End"))
    p.keyboard.type("!")
    until(lambda: text(site) != SAMPLE.replace("| a | 1 |", "| a<br>more | 1 |"), timeout=10, what="the autosave")
    assert "| a!<br>more | 1 |" in text(site)      # the click lands on the cell's first line


def test_shift_enter_in_a_heading_does_nothing_and_a_pasted_list_in_a_cell_is_paragraphs(doc, site):
    p = open_editor(doc, site)
    p.click(f"{DOC} h1")
    p.keyboard.press(key("End"))
    p.keyboard.press("Shift+Enter")
    assert p.evaluate("window.sheafBlockEditor.last.markdown()") == SAMPLE


def test_an_empty_paragraph_before_a_block_the_editor_keeps_does_not_shift_its_id(doc, site):
    p = open_editor(doc, site)
    before = p.evaluate("window.sheafBlockEditor.last.ids()")
    p.click(f"{DOC} p >> text=Last paragraph.")
    p.keyboard.press(key("Home"))
    p.keyboard.press("Enter")
    p.keyboard.press("ArrowUp")
    p.keyboard.press("Enter")                       # an empty paragraph, then the text moves down
    ids = p.evaluate("window.sheafBlockEditor.last.ids()")
    assert ids == before                            # an empty paragraph is no block of the Markdown


PASTE = """(html) => {
  const dt = new DataTransfer(); dt.setData('text/html', html);
  document.querySelector('#rd-be .ProseMirror').dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
}"""


def test_enter_at_the_start_of_a_paragraph_leaves_the_ids_of_the_blocks_as_they_were(doc, site):
    p = open_editor(doc, site)
    before = p.evaluate("window.sheafBlockEditor.last.ids()")
    p.click(f"{DOC} p >> text=Last paragraph.")
    p.keyboard.press(key("Home"))
    p.keyboard.press("Enter")
    assert p.evaluate("window.sheafBlockEditor.last.ids()") == before


def test_html_only_clipboard_pasted_in_a_cell_is_its_text_and_a_range_of_cells_is_left_alone(doc, site):
    p = open_editor(doc, site)
    p.click(f"{DOC} td >> text=a")
    p.keyboard.press(key("End"))
    p.evaluate(PASTE, "<ul><li>x</li><li>y</li></ul>")
    got = p.evaluate("window.sheafBlockEditor.last.markdown()")
    assert "| axy | 1 |" in got
    p.evaluate("""(() => {
      const ed = window.sheafBlockEditor.last.editor; let from = null, to = null;
      ed.state.doc.descendants((n, pos) => { if (n.isText && n.text === 'axy') from = pos + 1; if (n.isText && n.text === '1' && from !== null && to === null) to = pos + 1; });
      ed.commands.setTextSelection({ from, to });
    })()""")                                         # from inside one cell to inside the next
    p.evaluate(PASTE, "<p>zzz</p>")
    md = p.evaluate("window.sheafBlockEditor.last.markdown()")
    assert "| axy | 1 |" in md and "zzz" not in md


def test_a_held_escape_after_a_conflict_does_not_discard_the_editor(doc, site):
    p = open_editor(doc, site)
    p.click(f"{DOC} p >> text=Last paragraph.")
    p.keyboard.press(key("End"))
    p.keyboard.type(" mine")
    p.keyboard.press(key("Control+s"))
    answers = server_saves(p)
    until(lambda: text(site) != SAMPLE, timeout=10, what="the first save")
    rewrite(site.file, text(site).replace("# Rectoverso sample", "# Theirs"))
    p.keyboard.type(" more")
    p.keyboard.press(key("Control+s"))
    until(lambda: "conflict" in p.inner_text("body").lower() or p.evaluate("window.sheafBlockEditor.last.markdown().includes('more')"), timeout=10, what="the conflict")
    p.keyboard.press("Escape")                       # arms the discard
    p.wait_for_timeout(1000)
    p.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', repeat: true, bubbles: true }))")
    assert p.locator(DOC).count() == 1               # the editor is still there
