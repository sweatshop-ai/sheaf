"""The toast the page shows after a save that met a change in the file.

The toast for a `locked` conflict once said "also changed in the file" for a mixed save, and
no test ran the page's script. The sentences are built by one function in page.js,
`conflictNote`, which these tests read out of the asset: the sentences are pinned as text
(always), and the function is run under node when node is installed (the same optional use
as in test_page_assets.py; node is not a dependency of the project).

Checked by hand, because nothing here drives a browser: that `save()` hands the server's
`conflicts` to `conflictNote`, keeps it across the reload (sessionStorage `rd-toast`) and
shows it as the toast of the reloaded page."""
import json
import re
import shutil
import subprocess
from importlib.resources import files

import pytest

JS = (files("sheafmd") / "page" / "page.js").read_text(encoding="utf-8")

ALSO = "also changed in the file. Your version was kept; the file’s is in a comment by sheaf."
REPLACED = ("replaced in the file by a block this page cannot edit. "
            "The file’s block was kept; your text is in a comment by sheaf.")
THERE = ("replaced by a block this page cannot edit: there the file’s block was kept "
         "and your text is in the comment.")


def function_source():
    m = re.search(r"^  function conflictNote\(.*?^  }\n", JS, re.S | re.M)
    assert m, "page.js has no function conflictNote"
    return m.group(0)


def test_the_three_sentences_of_the_toast_are_in_the_script_and_save_uses_them():
    src = function_source()
    # each sentence is one literal of the script, so a change of wording shows in the diff
    for sentence in (ALSO, REPLACED, THERE):
        assert "' " + sentence + "'" in src
    assert JS.count("conflictNote(") == 2 and "conflictNote(conflicts)" in JS


CASES = [
    (["both"], "1 paragraph was " + ALSO),
    (["both", "gone"], "2 paragraphs were " + ALSO),
    (["locked"], "1 paragraph was " + REPLACED),
    (["locked", "locked"], "2 paragraphs were " + REPLACED),
    (["both", "locked"], "2 paragraphs were " + ALSO + " 1 of them was " + THERE),
    (["gone", "locked", "locked"], "3 paragraphs were " + ALSO + " 2 of them were " + THERE),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("kinds, sentence", CASES, ids=["+".join(k) for k, _ in CASES])
def test_the_toast_function_says_what_happened_to_the_paragraphs(kinds, sentence):
    script = (function_source() + "\n"
              "const kinds = JSON.parse(process.argv[1]);\n"
              "console.log(JSON.stringify(conflictNote(kinds.map((k, i) => ({ i: i, kind: k })))));")
    r = subprocess.run(["node", "-e", script, json.dumps(kinds)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == sentence
