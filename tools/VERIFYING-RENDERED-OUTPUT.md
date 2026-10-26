# Checking a rendered PDF, without inventing defects

Read this before you write a text-extraction check against anything this script produces.

A `pdftotext` pass over three finished PDFs reported missing table columns in all three. All
three were correct. Nothing was missing. The check was wrong, and it was wrong in the direction
that gets acted on: a confident report of three defects in finished documents, where the "fixes"
would have damaged correct work.

A false red and a false green are the same instrument failure. This one was heading for a
report that looked thorough.

## Two causes, both properties of the pipeline

**A theme can uppercase table headers.** A header written `Google's criterion` in the
markdown arrives in the extracted text as `GOOGLE'S CRITERION`. Nothing in the source says so,
and the page looks exactly like the markdown.

**`pdftotext` breaks cell text across lines.** A header cell wide enough to wrap comes out with
newlines inside it, so `Orders at priority 1 to 3` is never a contiguous string anywhere in
the output. Substring matching cannot find it no matter how the cell renders.

Either one alone produces a miss. Together they produced six.

## Normalise both sides before matching

```python
import re

def norm(s):
    s = s.replace("’", "'").replace("‘", "'")   # curly quotes -> straight
    s = s.replace("—", "-").replace("–", "-")   # em/en dash -> hyphen
    return re.sub(r"\s+", " ", s).lower()                 # collapse whitespace, case-fold

# then: norm(expected_header) in norm(extracted_page_text)
```

Case-fold because of the styling. Collapse whitespace because of the line breaks. Fold the
quotes and dashes too — the renderer emits typographic characters where the markdown had ASCII,
so a straight apostrophe in your expected string will not match the curly one on the page.

Worked, on the two that failed:

| expected | in the PDF text | matches raw? | matches normalised? |
|---|---|---|---|
| `Google's criterion` | `GOOGLE'S CRITERION` | no | yes |
| `Orders at priority 1 to 3` | `Orders at\npriority 1 to 3` | no | yes |

## Normalising is not enough for cell text

Headers are short and survive the fix above. Cell text often does not, and there is no
normalisation that rescues it.

In a multi-column table whose cells wrap, `pdftotext` emits the columns **interleaved line by
line**, not cell by cell. A criteria table comes out like this:

```
Items named in the plan         <- column 1, line 1
The cover ends outright...       <- column 2, line 1
for                              <- column 1, line 2
the month.                       <- column 2, line 2
```

`Items named in the plan for` is therefore not contiguous, and collapsing whitespace cannot make
it so: the other column's text sits inside it. A cell-level substring check reports every
wrapping cell in the table as missing. Re-running the verification can flag several
cells in one table, all present on the page.

**A URL wrapping at a hyphen loses that hyphen in the extraction.** Same cause, worse effect,
because the character disappears rather than a newline appearing.
`.../visit-the-old-town-district` breaks after `town-` on the page and extracts as
`visit-the-old-towndistrict`. A substring check for the real URL returns zero, which reads
as "the URL is missing from the document" when the page shows it correctly and the href is
right. Looking at the rendered page shows it: the hyphen is visible at the line
break. To check a URL survived, match on a segment that does not span a wrap, or read the
`href` out of the HTML, which is what a click actually follows.

Check cell **content** by words rather than by phrase — every word of the expected cell appears
somewhere in the page text. That still catches a cell dropped in full, and stays quiet on a cell
merely reflowed. For anything stronger, look at the page.

## What text extraction still cannot tell you

It says a chart's labels are on the page. It does not say the chart drew. A chart that rendered
as an empty frame with correct axes and labels passes every text check there is.

It also cannot see a page break. A table split across two pages extracts as complete text, in
order, with nothing to signal the break — which is how the real defect in that same batch got
through the text pass and was caught only by opening the pages. One table in that
batch broke between its last data row and its `Total` row, leaving the total alone on the next
page under a repeated header.

So: text extraction to check that content is present and whole, then open every page and look.
Every page, not the pages you expect a chart on. A chart cut across a break shows its top half
on one page and its bottom half on the next, and a check that opens only the expected pages
sees the top half and passes it.

## The automated half: `check-rendered-pdf.py`

```bash
tools/check-rendered-pdf.py DOC.pdf [DOC2.pdf ...]
tools/check-rendered-pdf.py --self-test DOC.pdf     # every rule shown firing and staying quiet
```

It catches a stranded table tail, a near-empty final page, and a chart split across a break.

**One correction to the section above.** "It also cannot see a page break" is true of
`pdftotext DOC.pdf -`, which concatenates the whole document. `pdftotext -f N -l N` extracts a
single page, and then the break is precisely what is visible: what starts a page and what ends
one. That is how the script finds the `Total 210` stranded under a repeated header, the same
defect this note records as having escaped the text pass. The rest of the section stands, and
the last line of it matters most: **an empty chart frame passes every check in the script.**
Run it, then open every page anyway.

### Three ways that script was wrong before it was right

Recorded because each one made it look thorough while reporting the wrong thing, and each is
easy to reintroduce while extending it. They are the same class of failure as the false red at
the top of this note, from the other side.

| Wrong how | Cause | Fix |
|---|---|---|
| Passed the split table it was written for | counted every non-header line on the page, so the prose after a table swamped a two-cell tail and made it look like a twenty-row one | count only the lines before the first prose line |
| Flagged three ordinary section headings | a theme that uppercases headings makes it so a heading that wraps is two uppercase lines at the top of a page, which is the shape of a two-column header row | require a run of >= 2 uppercase lines **and** at least one data cell under them |
| Threw a false red on all four charts | an axis label is not unique to the chart: the table beneath it is headed the same words, and case-folding makes them collide | test that label and note share a page, not that they occur on the same set of pages |

The third one carries a lesson the other two do not. **It was caused by two changes that were
each correct on their own.** Adopting the `norm()` above for consistency was right. Comparing an
axis label against a note to detect a split was right. Together they broke the check, because
folding case let the axis label collide with the table header that repeats its words. Reviewing
either change on its merits passes it, which is what makes this class hard to catch.

And the version before it was not sound either. It survived only because it matched
uppercase-exactly, so the collision never surfaced. It was already broken and happened to be
reading a case-sensitive world. A check that passes because of a property nobody chose is
waiting for the first person who improves something next to it.

A fourth failure was in the clipping check: it substring-matched short values like `13` and `20`
against a document containing `2026`, so it could not fail. **A check that cannot fail is worse than no
check, because it gets quoted as evidence.** Test a clipped column by whether its header
survived, normalised as above, and prove the test works by probing a header that does not exist.

---

Written after verifying a batch of finished PDFs in September 2026. The `.tblwrap`
`overflow-x: auto` bug — which scrolled on screen and clipped in print, silently losing a wide
table's right-hand columns — was fixed in the same round. That one is exactly what a text check
catches and looking does not, so the two checks are for different failures and neither replaces
the other.
