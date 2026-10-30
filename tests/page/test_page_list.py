"""The list's action buttons in Chromium (SPEC 9.10, #107): a press waits 5 seconds with Undo before it posts the
tick, Undo in that window sends nothing, and a refusal gives the button back. The page and its `/_/tick` are the
hub's own, through the proxy handler of tests/test_hub_list.py; the page's clock is Playwright's."""
import json

import pytest
from pagehelp import close_context, new_context, until
from test_hub_list import JOEY, NELL, box, github, sheaves  # noqa: F401  (the hub with its list, as there)

ORIGIN = "http://list.test"


@pytest.fixture
def listed(chromium, box):  # noqa: F811
    """A tab on the list as Nell, its requests answered by the hub; `ticks` holds each tick's body and status."""
    ticks = []

    def answer(route):
        req = route.request
        path = req.url[len(ORIGIN):]
        if req.method == "POST" and path == "/_/tick":
            body = json.loads(req.post_data)
            res = box.post("/_/tick", body, member=NELL)
            ticks.append((body, res.status))
        else:
            res = box.get(path, member=NELL)
        route.fulfill(status=res.status, headers=dict(res.headers), body=res.body)

    context = new_context(chromium)
    context.route(f"{ORIGIN}/**", answer)
    page = context.new_page()
    page.clock.install()
    page.goto(f"{ORIGIN}/list")
    yield page, ticks
    close_context(context)


def joey(page):
    return page.locator(f'button.list-act[data-doc="{JOEY}"]')


def test_a_press_shows_undo_for_five_seconds_then_ticks_and_the_list_reloads_without_the_row(listed, sheaves):  # noqa: F811
    page, ticks = listed
    joey(page).click()
    assert joey(page).inner_text() == "Undo"
    page.clock.run_for(4900)
    assert ticks == []
    page.clock.run_for(200)
    until(lambda: ticks, what="the tick")
    assert [(b["action"], b["word"], s) for b, s in ticks] == [(0, "Approve", 200)]
    assert "- [x] Approve" in (sheaves / JOEY[5:]).read_text(encoding="utf-8")
    until(lambda: joey(page).count() == 0, what="the reload without the row's button")


def test_undo_in_the_five_seconds_sends_nothing_and_gives_the_button_back(listed, sheaves):  # noqa: F811
    page, ticks = listed
    before = (sheaves / JOEY[5:]).read_text(encoding="utf-8")
    joey(page).click()
    page.clock.run_for(3000)
    joey(page).click()
    assert joey(page).inner_text() == "Approve"
    page.clock.run_for(10_000)
    page.wait_for_timeout(200)
    assert ticks == []
    assert (sheaves / JOEY[5:]).read_text(encoding="utf-8") == before


def test_a_refused_press_is_said_above_the_rows_and_the_button_can_be_pressed_again(listed, sheaves):  # noqa: F811
    page, ticks = listed
    path = sheaves / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Approve", "- [x] Approve"), encoding="utf-8")
    joey(page).click()
    page.clock.run_for(5100)
    until(lambda: ticks, what="the tick")
    assert ticks[0][1] == 409
    until(lambda: page.locator(".list-error").is_visible(), what="the refusal")
    assert "reload the list" in page.locator(".list-error").inner_text()
    assert joey(page).inner_text() == "Approve" and joey(page).is_enabled()
    assert joey(page).get_attribute("aria-pressed") == "false"

