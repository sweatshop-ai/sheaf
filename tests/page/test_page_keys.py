"""The keys a page test presses, on the system the browser runs on.

Playwright's Chromium on macOS turns a key into the editing command macOS gives it: End and Home scroll the
document and leave the caret where it was, Control+End moves nothing, and Control+v is page down. A test that
pressed End to type at the end of a paragraph typed at its start (run 41002665059: 25 page tests). `key`
gives the keys a person on that system presses for the same move."""
import pytest

from pagehelp import key


@pytest.mark.parametrize("combo, mac", [
    ("End", "Meta+ArrowRight"), ("Home", "Meta+ArrowLeft"), ("Shift+End", "Shift+Meta+ArrowRight"),
    ("Control+End", "Meta+ArrowDown"), ("Control+Home", "Meta+ArrowUp"), ("Control+v", "Meta+v")])
def test_on_macos_a_caret_move_or_a_paste_is_pressed_as_a_mac_person_does(combo, mac):
    assert key(combo, "darwin") == mac
    assert key(combo, "linux") == combo


@pytest.mark.parametrize("combo", ["Enter", "e", "Escape", "Control+s", "Control+Enter", "Shift+ArrowRight", "ArrowLeft"])
def test_a_key_macos_gives_the_same_meaning_is_pressed_as_it_is(combo):
    assert key(combo, "darwin") == combo
