# 137: Follow-ups on page edits, version pins and the atomic writers

**Status:** open

**From:** render-doc ticket 137 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/edit.py`, `src/sheafmd/render.py:801`, `src/sheafmd/hub/live.py`, `src/sheafmd/hub/state.py`, `src/sheafmd/source.py`, `src/sheafmd/atomic.py`, `src/sheafmd/agent_setup.py`, `SPEC.md:460`, `:788`, `:1636`

**Size:** 21 items, one P2 and the rest P3; the three probed edit items were run through sheaf 1.0.3's `html_block_to_md` (byte-identical to main's `edit.py`) with pandoc 3.7

## What a page edit writes

- [ ] **P2: backslashes are lost on a page edit.** `html_block_to_md` (`src/sheafmd/edit.py:629`, writer call at `:644`/`:648`) passes paragraph text through pandoc's gfm writer, which leaves `\\` unescaped and swallows the character after an escaped backslash. Probed: typing `a\\b` saves `a\\b` (reads back `a\b`); `a\*b` saves `a\\b` (the `*` is lost); `c\_d` saves `c\\d`. Tables with a break avoid it by going as raw HTML (`edit.py:585-590`); paragraphs do not. Fix idea: escape backslash runs around the pandoc call.
- [ ] **Emoji shortcodes become emoji after an edit.** The page renders `:+1:` with gfm's emoji extension as `<span class="emoji" data-emoji="+1">👍</span>`. Probed: `html_block_to_md` of that span writes `👍`, not `:+1:`. Fix idea: write `data-emoji` spans back as `:name:`, or render with `-f gfm-emoji` (`edit.py:681`, `:774`; `render.py:801`).
- [ ] **A no-break space counts as white space in `ends_its_cell`** (`src/sheafmd/edit.py:572-579`, `x.strip()`). Probed: a cell `a<br>&nbsp;` saves as `| a\xa0 |` (the break is lost); `x<br><br>` (an empty line on screen) saves as `| x |`.
- [ ] **Enter inside inline code in a table cell writes the whole table as raw HTML.** Chromium writes `<code>red on<br>xes</code>`; `edit.py:584` excludes breaks inside `code`, so the table falls through to raw HTML, which the page cannot edit. Probed.
- [ ] **Enter after a word of a heading splits it into a heading and a paragraph.** `<h2>Ab<div>cd</div></h2>` saves as `## Ab` plus a paragraph `cd` (probed). Open design question: should the second half stay a heading? The hub cannot tell this from Enter at the end; the page would have to mark the line.
- [ ] **Enter where a block is not a paragraph.** `---` typed after Enter becomes a rule, and a pasted `<div style>` stays raw HTML. Not re-probed through the full save path (`apply_edits`).
- [ ] **A no-break space at a cut.** One NBSP at the cut is trimmed, but one to three leading spaces that the file adds to the page's own save get no conflict note. Separately, `split_md_blocks` reads a line indented by space+tab as a paragraph where pandoc reads code. Not re-probed.

## Merging a split line

- [ ] **Split-line merge edges** (all "same as before", no words lost), in `src/sheafmd/edit.py` `merge_edits` / `_own_rows` (around `:2088-2330`). Not re-probed:
  - (a) mirror shape: a line typed above plus a line split off below; the file deletes the block before; the second save drops the first line; the split line is written twice.
  - (b) a three-line split whose middle line the file deletes: the next save types on the last line, which is written twice.
  - (c) a line typed above that the file then changes is kept beside the edit with no conflict note.
  - (d) a typed-above line plus a split line, the file deleting the next block: the typed line is left twice. Also 2 of 168 grid scenes with two file changes.
- [ ] **An agent's comment on a split line that the second save drops** moves to the end of the first line with `quote="off"`, instead of being marked orphan. Not re-probed.

## Pins

- [ ] **Pins in memory have no age.** `Live._pins` (`src/sheafmd/hub/live.py:74`, `:486-491`) is capped at `PINS` but never expires; on disk pins expire after 7 days (`src/sheafmd/hub/state.py:37`, `:254`).
- [ ] **The 16-pin cap is per document, not per member** (`state.py:36`, `:208`; `live.py:490`). One member pinning many versions can push out another member's pin.
- [ ] **"An Ask answered with unsaved edits keeps the hash without a pin."** Not checked in sheaf's `page.js`: the pin call sites around an Ask answer were not traced. Trace them first.
- [ ] **Test gap: no page-level test pins the merged-save `was` hash.** The page tests at `tests/page/test_page_writing.py:1276-1350` cover the served hash only; the `was` pin is tested at hub and live level.

## Writers and Windows

- [ ] **`os.fchmod` breaks four commands on native Windows with Python 3.11 or 3.12.** `os.fchmod` (`src/sheafmd/source.py:201`, also `beneath.py:123`, `cli.py:1073`) exists on Windows only from Python 3.13. `requires-python` is `>=3.11` (`pyproject.toml:10`), and `SPEC.md:1636` lets `comment`, `reply`, `resolve` and `reopen` run on native Windows, so there they raise `AttributeError`, which `cli._change_doc` does not catch (it catches `OSError`). Fix: guard with `hasattr(os, "fchmod")`, or catch it.
- [ ] **Two atomic writers remain:** `source._write_atomic` (`src/sheafmd/source.py:171`) and `atomic.write_text_atomic` (`src/sheafmd/atomic.py:10`). The first does the extra swap checks.
- [ ] **Wrong error text when the document's owner bits lack read.** A save then fails with "...sheaf-tmp was replaced while the new text was written to it" (`source.py:163`), though nothing was replaced: the saver cannot read back the sibling it created with that mode. Only the wording is wrong.
- [ ] **SPEC 9.1 says more than SPEC 7.1.** `SPEC.md:788` says "a write that meets such a swap fails rather than being acknowledged", while 7.1 (`SPEC.md:460`) says the checks only narrow the window: a swap after the second check is not caught.
- [ ] **`sheaf init codex` runs `codex mcp get` twice** (`src/sheafmd/agent_setup.py:398` and `:417`, the second check before the add; up to 60 s each when codex hangs).

## Tests and code hygiene

- [ ] **Test duplication:** `tests/test_hub_handler.py:231` builds its own sibling-swap hook (monkeypatching `os.fsync`) beside the shared helper `swap_the_sibling_at` in `tests/test_source.py:258`.
- [ ] **Test hygiene:** a SIGTERM to a full `tests/page/` run once left "Task was destroyed but it is pending! ... Page._on_route()" and a main thread at 100% CPU for 15 minutes. Every full run showed 2 to 4 `PytestUnraisableExceptionWarning`s from a `Page._on_route` coroutine collected after its loop. Not re-run on sheaf.
- [ ] **Code smells in `src/sheafmd/edit.py`** (standards only): `_Step` is built by position (`:2217`, `:2225`); `BOTH_NOTE + "\n\n"` is repeated three times (`:2250`, `:2311`, `:2321`); `_PINS` is a folder name (`hub/state.py:40`); the closures use `nonlocal` and bare tuples; the names `own`, `mine`, `span`, `at` and `keeping` each mean several things.
