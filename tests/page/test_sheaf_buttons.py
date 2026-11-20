"""The owner's buttons on the Sheaf, and its view switch, in a real browser (SPEC 8.6, ticket 16): a row of the member's own
loose page offers Archive now (Restore in "Archived"), Keep and Delete; Delete asks a second click in the button itself and
puts the page in the trash, where each row offers Restore; the three views, Pages, Archived and Trash, each show their own
list and their count. The page is mounted as in test_mount_sheaf.py, every request answered by the hub's proxy handler as
Bea; the marks are read from the root's `.sheaf/` folder after each act, so the page and the hub are seen to agree."""
import json
import time

import pytest
from helpers import BEA
from pagehelp import until, rewrite
from test_mount_sheaf import agentview, mounted, pages  # noqa: F401  (fixtures)

pytestmark = pytest.mark.page


@pytest.fixture
def own(mounted, pages):  # noqa: F811  (the fixtures, by name)
    """Two loose pages of Bea, `alpha` and `beta`, on the page after a reload."""
    root, _ = pages.hub.loose.root_for(pages.hub.proxy.members[BEA])
    for name in ("alpha", "beta"):
        f = root.path / "2026-11" / f"{name}.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        rewrite(f, f"# {name.title()}\n\nText of {name}.\n")
    mounted.page.reload()
    until(lambda: mounted.page.evaluate("!!window.__root"), what="the page after the reload")
    until(lambda: mounted.js("return !!root.querySelector('.sheaf-row');"), what="the rows in the root")
    mounted.root_path = root.path
    return mounted


def marks(m, name):
    f = m.root_path / ".sheaf" / name
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def own_rows(m):
    return sorted(d.rsplit("/", 1)[1][:-3] for d in m.visible_rows() if "/2026-11/" in d)


def row(name):
    return f'.sheaf-row[data-doc$="/{name}.md"]'


def act(m, name, what):
    m.click(f'{row(name)} .sheaf-act[data-act="{what}"]')


def view(m, which):
    m.click(f'.sheaf-viewswitch[data-view="{which}"]')


def label(m, which):
    return m.js("return root.querySelector('.sheaf-viewswitch[data-view=\"' + arg + '\"]').textContent;", which)


def on(m):
    return m.js("return Array.from(root.querySelectorAll('.sheaf-viewswitch.on')).map((b) => b.dataset.view);")


def wait_rows(m, names, what):
    until(lambda: own_rows(m) == names, what=what)


def test_a_row_of_an_own_page_offers_archive_now_keep_and_delete_and_no_restore(own):
    assert own_rows(own) == ["alpha", "beta"]
    got = own.js("return Array.from(root.querySelectorAll(arg + ' .sheaf-act')).map((b) => [b.dataset.act, b.textContent]);", row("alpha"))
    assert got == [["archive", "Archive now"], ["keep", "Keep"], ["delete", "Delete"]]


def test_archive_now_takes_the_row_out_of_pages_and_into_archived_and_restore_brings_it_back(own):
    act(own, "alpha", "archive")
    wait_rows(own, ["beta"], "alpha gone from Pages")
    assert list(marks(own, "archived.json")) == ["2026-11/alpha.md"]
    until(lambda: label(own, "archived") == "Archived (1)", what="the count of Archived")
    view(own, "archived")
    until(lambda: on(own) == ["archived"] and own_rows(own) == ["alpha"], what="Archived lists alpha alone")
    got = own.js("return Array.from(root.querySelectorAll(arg + ' .sheaf-act')).map((b) => b.dataset.act);", row("alpha"))
    assert got == ["restore", "keep", "delete"]                  # Restore stands in the place of Archive now
    act(own, "alpha", "restore")
    until(lambda: own_rows(own) == [] and label(own, "archived") == "Archived", what="Archived empty again")
    assert not marks(own, "archived.json")
    view(own, "")
    until(lambda: on(own) == [""] and own_rows(own) == ["alpha", "beta"], what="both pages back in Pages")


def test_keep_marks_the_page_and_the_same_button_takes_it_off(own):
    act(own, "alpha", "keep")
    until(lambda: own.js("return root.querySelector(arg + ' .sheaf-act[data-act=\"keep\"]').textContent;", row("alpha")) == "Kept",
          what="the button says Kept")
    assert own.js("return root.querySelector(arg + ' .sheaf-act[data-act=\"keep\"]').classList.contains('on');", row("alpha")) is True
    assert list(marks(own, "keep.json")) == ["2026-11/alpha.md"]
    act(own, "alpha", "keep")
    until(lambda: own.js("return root.querySelector(arg + ' .sheaf-act[data-act=\"keep\"]').textContent;", row("alpha")) == "Keep",
          what="the button says Keep again")
    assert not marks(own, "keep.json")


def test_archive_now_on_a_kept_page_says_why_and_archives_nothing(own):
    act(own, "alpha", "keep")
    until(lambda: list(marks(own, "keep.json")) == ["2026-11/alpha.md"], what="the Keep mark")
    until(lambda: own.js("return root.querySelector(arg + ' .sheaf-act[data-act=\"keep\"]').textContent;", row("alpha")) == "Kept",
          what="the row drawn again")
    act(own, "alpha", "archive")
    until(lambda: own.js("return !root.querySelector('.sheaf-said').hidden;"), what="the line the hub gave")
    assert "kept" in own.js("return root.querySelector('.sheaf-said').textContent;")
    assert own_rows(own) == ["alpha", "beta"] and not marks(own, "archived.json")


def test_delete_asks_a_second_click_in_the_button_and_then_moves_the_page_to_the_trash(own):
    act(own, "alpha", "delete")
    until(lambda: own.js("return root.querySelector(arg + ' .sheaf-act[data-act=\"delete\"]').textContent;", row("alpha")) == "Really delete?",
          what="the second click asked for")
    for _ in range(5):                  # one click deletes nothing: a POST out after the button changed would show within this half second
        assert own_rows(own) == ["alpha", "beta"] and (own.root_path / "2026-11" / "alpha.md").exists()
        time.sleep(0.1)
    act(own, "alpha", "delete")
    wait_rows(own, ["beta"], "alpha gone from Pages")
    assert not (own.root_path / "2026-11" / "alpha.md").exists()
    assert len(list((own.root_path / ".sheaf" / "trash").rglob("alpha.md"))) == 1
    until(lambda: label(own, "trash") == "Trash (1)", what="the count of Trash")


def test_the_trash_view_lists_the_deleted_page_with_its_days_and_restore_puts_it_back(own):
    act(own, "alpha", "delete")
    act(own, "alpha", "delete")
    wait_rows(own, ["beta"], "alpha deleted")
    view(own, "trash")
    until(lambda: on(own) == ["trash"] and own.js("return root.querySelectorAll('.sheaf-trashed').length;") == 1, what="one trashed row")
    got = own.js("return Array.from(root.querySelectorAll('.sheaf-trashed td')).map((c) => c.textContent);")
    assert got[0].endswith("alpha.md") and got[1] == "30 days left"
    assert own_rows(own) == []                                   # the trash view lists no page of Pages
    own.click(".sheaf-trashed .sheaf-act")
    until(lambda: own.js("return !!root.querySelector('.sheaf-trash-empty');"), what="the trash empty")
    assert (own.root_path / "2026-11" / "alpha.md").exists()
    view(own, "")
    until(lambda: on(own) == [""] and own_rows(own) == ["alpha", "beta"], what="alpha back in Pages")
    assert label(own, "trash") == "Trash"


def test_the_view_switch_shows_pages_archived_and_trash_each_with_its_own_list(own):
    act(own, "alpha", "archive")
    wait_rows(own, ["beta"], "alpha archived")
    act(own, "beta", "delete")
    act(own, "beta", "delete")
    wait_rows(own, [], "beta deleted")
    until(lambda: label(own, "archived") == "Archived (1)" and label(own, "trash") == "Trash (1)", what="both counts")
    assert on(own) == [""]
    view(own, "archived")
    until(lambda: on(own) == ["archived"] and own_rows(own) == ["alpha"], what="Archived: alpha only")
    assert own.js("return root.querySelectorAll('.sheaf-trashed').length;") == 0
    view(own, "trash")
    until(lambda: on(own) == ["trash"] and own.js("return root.querySelectorAll('.sheaf-trashed').length;") == 1, what="Trash: beta only")
    assert own_rows(own) == [] and own.js("return root.querySelector('.sheaf-trashed td').textContent;").endswith("beta.md")
    view(own, "")
    until(lambda: on(own) == [""] and own_rows(own) == [], what="Pages: neither")
