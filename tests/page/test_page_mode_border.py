"""The Edit / Save toggle wears a border in the colour of the status ball by the round menu, and follows its state (ticket 03,
Thierry's trial 2026-11-09): grey when idle, green in Edit mode, red-orange when a block has changed. One source: the ball and the
border read the same variable, so they cannot disagree. The ball's colours do not change with the theme; both themes are checked."""
import pytest

from pagehelp import P1, until

pytestmark = pytest.mark.page

TOGGLE = "#rd-mode button"
MD = "# Plan\n\nSecond paragraph, about pears.\n\nA third one, about apples.\n"
GREY, GREEN, RED = "rgb(153, 153, 153)", "rgb(22, 163, 74)", "rgb(234, 88, 12)"


def ball(p):
    return p.evaluate("getComputedStyle(document.querySelector('#rd-menu-btn .rd-dot')).backgroundColor")


def border(p):
    return p.evaluate("(() => { const s = getComputedStyle(document.getElementById('rd-mode'));"
                      " return [s.borderTopColor, s.borderRightColor, s.borderBottomColor, s.borderLeftColor, s.borderTopWidth]; })()")


def agree(p, colour):
    assert ball(p) == colour, ("the ball", ball(p))
    *sides, width = border(p)
    assert sides == [colour] * 4, ("the border", sides)
    assert float(width[:-2]) >= 2, ("the border is too thin to see", width)


@pytest.fixture
def doc(tab, site):
    site.file.write_text(MD, encoding="utf-8")
    return tab.open()


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_border_follows_the_ball_grey_green_red(doc, scheme):
    p = doc.page
    p.emulate_media(color_scheme=scheme)
    agree(p, GREY)
    p.click(TOGGLE)
    until(lambda: ball(p) == GREEN, what="the green ball")
    agree(p, GREEN)
    p.focus(P1)
    p.keyboard.press("Control+End")
    p.keyboard.type(" and plums")
    until(lambda: ball(p) == RED, what="the red ball")
    agree(p, RED)
