"""Which box lines the page holds for a reload while it does not know the file's buttons (SPEC 10.11). The page reads
the rendered text of a line, the hub the raw markdown (the_list._ACTION_RE); the page's check is a superset of the hub's,
so a line the hub reads as an action is never ticked as a plain box. The check is a closure of the page, so its own
source (the words and the pattern) is cut out of page.js and run on a page of the browser."""
from importlib.resources import files

import pytest

pytestmark = pytest.mark.page

SOURCE = files("sheafmd.page").joinpath("page.js").read_text(encoding="utf-8")
CUT = SOURCE[SOURCE.index("  var ACTION_WORDS"):SOURCE.index("  // The text of a box's own item")]

# What a box's line says once rendered and its whitespace collapsed (page.js itemLine), against what the hub makes of the markdown.
HUB_ACTIONS = ["Approve", "Run it", "Done @bea", "Merge", "Merge a/b#1", "Merge", "Install pkg", "Deploy now",
               "Belongs to plan (ref abc)", "Shared with the team", "Share"]
PAGE_ONLY_ACTIONS = [
    "Merge",                     # `- [ ] Merge <!-- note -->`: the hub reads the raw line, which holds a note; the rendering drops it
    "Merge",                     # `- [ ] Merge ![](x)`: the image has no text
    "Merge a/b#1",               # `- [ ] **Merge** a/b#1`: the hub does not read it; the page holds it for a reload, accepted
]
PLAIN = ["Mergers are hard", "Doner kebab", "Approved by the board", "Plan the merge"]


@pytest.fixture
def may_be_action(tab):
    tab.open()
    run = tab.page.evaluate

    def test(line):
        return run("(line) => {\n" + CUT + "\n  return ACTION_LINE.test(line); }", line)
    return test


@pytest.mark.parametrize("line", HUB_ACTIONS + PAGE_ONLY_ACTIONS)
def test_a_line_that_begins_with_a_word_may_be_an_action(may_be_action, line):
    assert may_be_action(line)


@pytest.mark.parametrize("line", PLAIN)
def test_a_plain_line_that_begins_with_the_letters_of_a_word_is_not_an_action(may_be_action, line):
    assert not may_be_action(line)
