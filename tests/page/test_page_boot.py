"""The browser harness itself: a hub, a signed-in page, no script errors."""
import pytest

pytestmark = pytest.mark.page


def test_the_page_loads_signed_in_and_raises_no_script_error(tab):
    tab.open()
    assert "about apples" in tab.page.inner_text("main, body")


def test_a_hub_that_goes_and_comes_back_has_a_new_boot(site):
    first = site.hub.boot
    site.stop()
    site.start()
    assert site.hub.boot != first
