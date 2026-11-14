"""Ticket 70, c1: does `-webkit-user-modify: read-write` in a style attribute that the simple-mode sanitiser keeps make text editable?
The page finds an editable surface with `closest('[contenteditable="true"]')`, which does not see one made by CSS. Each engine is given the
span, as the sanitiser returns it, and types into it; the failure names the engines that let it be typed into."""
import pytest

from sheafmd.sanitize import sanitize

pytestmark = pytest.mark.page
SPANS = [
    '<p><span id="t" style="/*:*/-webkit-user-modify: read-write">x</span></p>',
    '<p><span id="t" style="-webkit-user-modify: read-write">x</span></p>',
]


@pytest.fixture(params=["chromium", "firefox", "webkit"])
def engine_page(request, chromium):
    if request.param == "chromium":
        browser, own = chromium, False
    else:
        try:
            browser, own = getattr(chromium.pw, request.param).launch(), True
        except Exception as e:      # noqa: BLE001 - not installed here (CI fails on a skip)
            pytest.skip(f"{request.param} cannot start here: {str(e).splitlines()[0]}")
    ctx = browser.new_context()
    page = ctx.new_page()
    yield request.param, page
    ctx.close()
    if own:
        browser.close()


def _types_into(page, html):
    page.set_content(f"<body>{html}</body>")
    page.click("#t")
    page.keyboard.type("hello")
    return page.evaluate("document.getElementById('t').textContent")


@pytest.mark.parametrize("html", SPANS)
def test_what_the_sanitiser_keeps_of_the_span_cannot_be_typed_into(engine_page, html):
    """The span as `sanitize()` returns it in simple mode: no engine may let the reader type into it."""
    name, page = engine_page
    got = _types_into(page, sanitize(html))
    assert got == "x", f"{name} let text be typed into the sanitised span: {got!r}"


@pytest.mark.parametrize("html", SPANS)
def test_the_unsanitised_span_is_typed_into_in_chromium_and_webkit(engine_page, html):
    """The control for the test above: without `sanitize()` the span takes the text in the engines that honour the property
    (Firefox does not). If an engine stopped honouring it, the sanitised case would pass for nothing."""
    name, page = engine_page
    if name == "firefox":
        pytest.skip("Firefox does not honour -webkit-user-modify")
    got = _types_into(page, html)
    assert got != "x", f"{name} no longer lets the unsanitised span be typed into: the test above proves nothing"
