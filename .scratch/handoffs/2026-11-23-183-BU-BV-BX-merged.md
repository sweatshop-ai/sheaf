# Handoff: ticket 183 BU, BV and BX merged in #634 (2026-11-23)

**Status:** merged in #634 (merge `899a25cf`, head `10fcc4e5`). Review: Matt's code-review (standards and spec), boss_review round 1 GO on `9b677f3a` and round 2 (fix pass, `--since 9b677f3a`) GO on `10fcc4e5`, both provisional: Opus fallback, Codex at its usage limit until 2026-11-24 12:39 UTC. CI green on `10fcc4e5`. Worktree and branch `imani/183-bu-bv-bx` removed; nothing on the CI runner host.

## What changed (`src/sheafmd/edit.py`, `_raw_tags`, `_lone_as_text`, `_convert_with_comments`)

- **183 BV**: `lead`/`trail` in `_lone_as_text` also collect the comments at the end of an element closed before the tag (or at the start of one opened after it), down any depth (`beside`). After the tag climbs out of the element, it steps over the comments still due on the element's other side. This also fixes `*Start*<c1></x1>`, which saved as `*Start*</x1><c1>` on main.
- **183 BX**: `lead`/`trail` record which comments stood beside the tag (their source bytes, `\r` dropped), not how many. `_lone_as_text` takes `comments`, a map from placeholder to source bytes (`comment_bytes` in the caller), and `step_over` steps only over those placeholders. Two identical foreign comments cannot be told apart; the spec review's probe of that case came out right.
- **183 BU**: `_raw_tags` returns a fourth item, `unkept`: every non-markdown tag in an HTML block nested in the block (a list item that starts with a comment is one), skipping tags written inside comments. A save whose markdown holds fewer copies of one of them than the source (without comments) is refused with "block holds raw HTML the edit cannot keep". This is wider than BU's lone closing tag: main also rewrote `<kbd>` and dropped `<details>` there silently.
- **CRLF** (boss review round 1): pandoc's render drops `\r` inside a multi-line comment, so the comparison is made without it. Before the fix, BS's wrong-side placement came back in a CRLF file.

## Tests

`tests/test_edit_inline_html.py`: BV (6 cases), BX (3), CRLF (1), BU refusals (3: lone closing tag, kbd, details in a quote), 2 controls (a nested HTML block whose tags are kept; a tag inside a comment's words). `tests/test_edit*.py`: 902 passed locally.

## Findings left as they are (boss review, rounds 1 and 2, minor)

1. **Deleting the words around a nested-block tag is refused.** For example, the reader deletes the list item `- <!-- f --></x1>Start`. A lone inline tag goes with its words (`_lone_as_text`, "the words are all gone"), but the nested-block check cannot tell a deletion from a loss. Left as it is because the refusal loses nothing: the reader is sent to the .md, and before #634 the same save could drop or rewrite the tag silently. Telling the cases apart would need the nested block's words to be matched on the page. File it if it bites.
2. **A nested-block tag that the conversion only rewrites in form is refused.** This covers quote style, attribute order and letter case: the check counts exact source bytes. Left as it is for the same reason. Main rewrote those tags silently (`<kbd>` became `<span class="kbd">`), and keeping the source's bytes is the rule for raw tags elsewhere (`_tags_as_text`).

## Next

Nothing left on BU, BV and BX.
