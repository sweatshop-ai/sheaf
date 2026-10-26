#!/usr/bin/env python3
"""Structural checks on a PDF produced by sheaf.

    tools/check-rendered-pdf.py DOC.pdf [DOC2.pdf ...]
    tools/check-rendered-pdf.py --self-test DOC.pdf     # prove the checks can fail

Catches three print defects that a whole-document text pass cannot see:
a table whose tail is stranded under a repeated header, a near-empty final
page, and a chart split across a page break.

Read VERIFYING-RENDERED-OUTPUT.md first. This script is the automated half;
that note is the half about opening the pages, and neither replaces the other.
**A chart that rendered as an empty frame passes every check in here.**

── Why this works when the note says text extraction cannot see a page break ──

That is true of `pdftotext DOC.pdf -`, which concatenates. `pdftotext -f N -l N`
extracts one page, and then the break is exactly what you can see: content that
starts a page, and content that ends one.

── Three ways this script can be wrong ──

Each is easy to reintroduce while extending it, and each made it *look*
thorough while reporting the wrong thing.

1. **It counted the wrong population.** The stranded-tail rule counted every
   non-header line on the page. The prose that follows a table is non-header
   text too, so a table stranded with two cells looked like a healthy
   twenty-row one and the check passed the defect it was written for. Only the
   lines *before the first prose line* belong to the table.

2. **Uppercase wrapped headings look exactly like repeated table headers.** The
   theme can set headings in uppercase, so a heading long enough to wrap
   arrives as two uppercase lines at the top of a page, which is the shape of a
   two-column header row. Keying on "page starts with uppercase" flagged three
   ordinary section headings. Two discriminators are needed: a run of >= 2
   uppercase lines, AND at least one data cell under them. Zero data cells means
   there is no table on the page at all.

3. **A chart's axis label is not unique to the chart.** Matching the axis
   label and the note to the *same page list* threw a false red on all four
   charts: the table beneath a chart is headed the same words as its axis, so
   `orders at priority 1 to 3` is on the chart page and on both table pages.
   Once case-folded, the two collide. Test that the label and the note share a
   page, not that they occur on the same set of pages.

A fourth mistake was in the *clipping* check that used to live here: it
substring-matched short values like `13` and `20` against a document containing
`2026`, so it could not fail. Check a clipped column by whether its HEADER
survived, normalised per the note, never by hunting short numbers.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

# ── The question this constant answers ──────────────────────────────────────
# Does the final page carry a real ending, or is it a fragment that spilled?
# That is the judgement; the number is only how it is approximated.
#
# The convention, because three numbers describe the same page and only one is
# this threshold. For one document's final page:
#   177  raw pdftotext output, trailing form feed and newline included
#   174  THIS MEASURE: len(page.strip()) -- outer whitespace off, inner kept
#   144  every whitespace character removed
# Compare like with like before concluding two measurements disagree. They did
# not; 150 and 144 were describing the same page under different conventions.
#
# Calibrate against observed pages, not against the integer (all in THIS
# measure, len(page.strip())):
#   96 chars, one stranded sentence, the whole closing thought orphaned  DEFECT
#  258 chars, two short closing paragraphs after a bullet list          ENDING
#  294 chars, three closing paragraphs                                  ENDING
#
# So the line sits between one sentence and one paragraph. 150 is that. An
# earlier 300 was set without a reason, tuned by eye on ~1000-word documents,
# and flagged both real endings above once the same documents were cut to ~400.
# If you are about to change this number, decide first which side of the list
# above your page belongs on, and add it to the list. A threshold with no
# reason attached gets re-tuned to whatever is failing that day.
#
# A page with NO text at all is always reported, whatever this is set to.
MIN_LAST_PAGE = 150
MIN_TAIL_ROWS = 3     # data cells a split table must carry past the break


def norm(s: str) -> str:
    """Fold what the pipeline changes: case, wrapping, quotes, dashes.

    Same normalisation as VERIFYING-RENDERED-OUTPUT.md. Keep them identical.
    """
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip().lower()


def page_texts(pdf: Path) -> list[str]:
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    n = int(re.search(r"Pages:\s+(\d+)", info).group(1))
    return [subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), str(pdf), "-"],
                           capture_output=True, text=True).stdout
            for i in range(1, n + 1)]


def stranded_table_tail(lines: list[str]) -> list[str] | None:
    """Data cells of a table continuing onto this page, if too few. Else None."""
    run = 0
    for l in lines[:6]:
        if l.isupper() and len(l) > 3:
            run += 1
        elif run:
            break
    if run < 2:                       # a single uppercase line is a heading
        return None
    table = []
    for l in lines:                   # stop where prose starts
        if len(l) >= 50 and any(c.islower() for c in l):
            break
        table.append(l)
    data = [l for l in table if not l.isupper()]
    # zero data cells => a wrapped heading, not a table (see docstring, cause 2)
    return data if 1 <= len(data) <= MIN_TAIL_ROWS else None


def check(pdf: Path, charts: list[tuple[str, str]]) -> list[str]:
    pages = page_texts(pdf)
    out = []
    for i, raw in enumerate(pages, 1):
        body = raw.strip()
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        if not body:
            out.append(f"p{i}: page is entirely blank")
        elif i == len(pages) and len(body) < MIN_LAST_PAGE:
            out.append(f"p{i}: final page carries only {len(body)} chars")
        tail = stranded_table_tail(lines)
        if tail:
            out.append(f"p{i}: table continues with only {len(tail)} data cell(s) "
                       f"under a repeated header -> {tail}")
    # A chart split across a break separates its axis label (top) from its
    # note (bottom), so they stop sharing a page. Test for a COMMON page, not
    # for identical page lists: an axis label legitimately repeats elsewhere,
    # because the table under a chart is usually headed the same words.
    for ylab, note in charts:
        py = {i for i, t in enumerate(pages, 1) if norm(ylab) in norm(t)}
        pn = {i for i, t in enumerate(pages, 1) if norm(note) in norm(t)}
        if not pn:
            out.append(f"chart note not found in the PDF, so this chart was NOT "
                       f"checked: {note[:50]!r}")
            continue
        if len(pn) != 1 or not (py & pn):
            out.append(f"chart split: axis label on {sorted(py)}, note on {sorted(pn)}")
    return out


def self_test(pdf: Path) -> int:
    """Show each rule firing on injected input. A rule never seen to fail is
    not evidence -- that is the whole reason this function exists."""
    cases = [
        ("stranded tail fires",
         stranded_table_tail(["REGION", "ORDERS", "Total", "210"]) is not None, True),
        ("wrapped heading stays quiet",
         stranded_table_tail(["THE SECOND HARBOUR SURVEY RAISES THE SAME",
                              "QUESTION AS THE FIRST SURVEY",
                              "None of the ten quays is on the maintenance record, so far."])
         is not None, False),
        ("healthy table stays quiet",
         stranded_table_tail(["REGION", "VISITS"] + [str(i) for i in range(12)])
         is not None, False),
        ("normalisation survives wrap + uppercase",
         norm("Orders at priority 1 to 3") in norm("ORDERS AT\nPRIORITY 1 TO 3"), True),
        ("axis label repeated in a table header is not a split",
         (lambda py, pn: len(pn) == 1 and bool(py & pn))({2, 3}, {2}), True),
        ("a real split is a split",
         (lambda py, pn: len(pn) == 1 and bool(py & pn))({2}, {3}), False),
        ("absent header is not found",
         norm("Visits by quarter") in norm(page_texts(pdf)[0]), False),
    ]
    bad = 0
    for name, got, want in cases:
        ok = got == want
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    return bad


def charts_from_source(pdf: Path):
    """Read the chart specs out of the sibling markdown.

    They were hardcoded here once. Editing a chart note then silently disabled
    that chart's check: the note was not found, the rule skipped it, and the
    run printed "ok" having checked nothing. A list that goes stale without
    saying so is a false green, which is the failure this whole file exists to
    avoid. Deriving them from the source cannot drift.
    """
    md = pdf.with_suffix(".md")
    if not md.exists() and pdf.stem.endswith("-share"):
        md = pdf.with_name(pdf.stem[: -len("-share")] + ".md")     # what `sheaf FILE --share --pdf` writes
    if not md.exists():
        return None                      # caller reports this rather than skipping
    out = []
    for block in re.findall(r"```chart\s*(\{.*?\})\s*```", md.read_text(encoding="utf-8"), re.S):
        try:
            spec = json.loads(block)
        except ValueError:
            # Said, not skipped: a chart that is not checked must not look checked.
            print(f"{md.name}: a chart block is not valid JSON, so that chart was NOT checked",
                  file=sys.stderr)
            continue
        y, n = spec.get("y_label"), spec.get("note")
        if y and n:
            out.append((y, n))
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--self-test"]
    if not args:
        print("usage: check-rendered-pdf.py DOC.pdf [DOC2.pdf ...]\n"
              "       check-rendered-pdf.py --self-test DOC.pdf", file=sys.stderr)
        sys.exit(2)
    if "--self-test" in sys.argv:
        sys.exit(self_test(Path(args[0])))
    total = 0
    for f in args:
        p = Path(f)
        if not p.is_file():
            print(f"{f}: no such file")
            total += 1
            continue
        charts = charts_from_source(p)
        if charts is None:
            print(f"{p.name}: no sibling .md, charts NOT checked")
            charts = []
        issues = check(p, charts)
        total += len(issues)
        print(f"{p.name}  {len(page_texts(p))} pages")
        for msg in issues:
            print(f"   [!] {msg}")
        if not issues:
            print("   ok")
    print(f"\n{total} issue(s). Now open every page and look: an empty chart frame "
          f"passes everything above.")
    sys.exit(1 if total else 0)
