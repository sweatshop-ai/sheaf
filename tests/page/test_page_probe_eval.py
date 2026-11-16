import pytest

pytestmark = pytest.mark.page


@pytest.fixture
def late(tab, site):
    site.file.write_text("# Plan\n\nBody.\n", encoding="utf-8")
    tab.open()
    tab.page.wait_for_selector("main")
    tab.page.evaluate("setTimeout(() => { window.__late = true }, 400)")
    return tab.page


def test_probe_string_predicate_true_at_once(tab, site):
    site.file.write_text("# Plan\n\nBody.\n", encoding="utf-8")
    tab.open()
    tab.page.wait_for_selector("main")
    tab.page.evaluate("window.__late = true")
    tab.page.wait_for_function("window.__late === true")


def test_probe_string_predicate_true_later(late):
    late.wait_for_function("window.__late === true")


def test_probe_function_predicate_true_later(late):
    late.wait_for_function("() => window.__late === true")
