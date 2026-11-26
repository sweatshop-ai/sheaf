"""Columns in a real browser (block editor v1, ticket 05): side by side at their stored split, stacked in source order
below 600 px on a screen, side by side again in print, and an image keeping its share of its column."""
import pytest

from pagehelp import rewrite

pytestmark = pytest.mark.page

MD = ('# Plan\n\n::: {#k .columns}\n::: {#a .column size="25"}\nLeft column text.\n\n'
      '::: {#i .image size="50" align="center"}\n![A](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==)\n:::\n'
      ':::\n::: {#b .column size="75"}\nRight column text.\n:::\n:::\n\nAfter.\n')


def boxes(p):
    return p.evaluate("""() => { const r = e => e.getBoundingClientRect();
        const a = r(document.querySelector('div.column#u-a, div.column#a')), b = r(document.querySelector('div.column#u-b, div.column#b'));
        const k = r(document.querySelector('div.columns')), i = r(document.querySelector('div.image img'));
        return {a: [a.left, a.top, a.width, a.bottom], b: [b.left, b.top, b.width, b.bottom], k: [k.width], i: [i.width]}; }""")


@pytest.fixture
def doc(tab, site):
    rewrite(site.file, MD)
    return tab.open()


def test_columns_sit_side_by_side_at_their_split_on_a_wide_screen(doc):
    p = doc.page
    p.set_viewport_size({"width": 1200, "height": 800})
    g = boxes(p)
    assert abs(g["a"][1] - g["b"][1]) < 2
    assert g["b"][0] > g["a"][0] + g["a"][2] - 2
    assert abs(g["a"][2] / (g["a"][2] + g["b"][2]) - 0.25) < 0.04


def test_columns_stack_in_source_order_below_600px(doc):
    p = doc.page
    p.set_viewport_size({"width": 500, "height": 800})
    g = boxes(p)
    assert g["b"][1] >= g["a"][3] - 1
    assert abs(g["a"][2] - g["b"][2]) < 2


def test_columns_stay_side_by_side_in_print_even_on_a_narrow_page(doc):
    p = doc.page
    p.set_viewport_size({"width": 500, "height": 800})
    p.emulate_media(media="print")
    g = boxes(p)
    assert abs(g["a"][1] - g["b"][1]) < 2 and g["b"][0] > g["a"][0]


@pytest.mark.parametrize("width", [1200, 500])
def test_an_image_keeps_its_share_of_its_column_at_every_width(doc, width):
    p = doc.page
    p.set_viewport_size({"width": width, "height": 800})
    g = boxes(p)
    assert abs(g["i"][0] / g["a"][2] - 0.5) < 0.05
