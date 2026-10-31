"""The list's action buttons in Chromium (SPEC 9.10, #107): a press waits 5 seconds with Undo before it posts the
tick, Undo in that window sends nothing, and a refusal gives the button back. The page and its `/_/tick` are the
hub's own, through the proxy handler of tests/test_hub_list.py; the page's clock is Playwright's."""
import json

import pytest
from pagehelp import close_context, new_context, until
from test_hub_list import JOEY, NELL, box, github, sheaves  # noqa: F401  (the hub with its list, as there)

pytestmark = pytest.mark.page

ORIGIN = "http://list.test"


def on_the_list(chromium, box, **options):  # noqa: F811
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

    context = new_context(chromium, **options)
    context.route(f"{ORIGIN}/**", answer)
    page = context.new_page()
    page.clock.install()
    page.goto(f"{ORIGIN}/list")
    yield page, ticks
    close_context(context)


@pytest.fixture
def listed(chromium, box):  # noqa: F811
    yield from on_the_list(chromium, box)


PHONE = {"viewport": {"width": 360, "height": 780}, "has_touch": True, "is_mobile": True}


@pytest.fixture
def phone(chromium, box, sheaves):  # noqa: F811
    """The list on a 360 px phone, Joey's row holding four buttons, one a Move to whose long slug has no hyphen."""
    path = sheaves / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace(
        "- [ ] Approve\n", "- [ ] Approve\n- [ ] Done\n- [ ] Share\n"
        "- [ ] Move to klium_website_relaunch_international_2026_phase_two (ref 18f3a9c2)\n"),
        encoding="utf-8")
    box.hub.the_list.poll()
    yield from on_the_list(chromium, box, **PHONE)


GA4 = "list/initech/website/2026-10-27-ga4-property.md"


def joey(page):
    """The button of Joey's sheaf, Approve: its one action unless a test gave it more."""
    return page.locator(f'button.list-act[data-doc="{JOEY}"]')


def ga4(page):
    """The button of the GA4 sheaf, Done @dora."""
    return page.locator(f'button.list-act[data-doc="{GA4}"]')


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


def test_a_refused_press_is_said_above_the_rows_and_the_button_comes_back(listed, sheaves):  # noqa: F811
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
    assert joey(page).get_attribute("aria-pressed") is None
    assert page.locator(".list-error").get_attribute("role") == "alert"


def test_a_press_on_another_row_in_the_five_seconds_is_sent_too_and_the_list_reloads_after_both(listed, sheaves):  # noqa: F811
    page, ticks = listed
    joey(page).click()
    page.clock.run_for(2000)
    ga4(page).click()
    page.clock.run_for(3100)
    until(lambda: ticks, what="Joey's tick")
    page.wait_for_timeout(300)
    assert ga4(page).inner_text() == "Undo"             # Joey's reload waits for the press still in its window
    page.clock.run_for(2100)
    until(lambda: len(ticks) == 2, what="the GA4 tick")
    assert [(b["doc"], b["word"], s) for b, s in ticks] == [(JOEY, "Approve", 200), (GA4, "Done", 200)]
    until(lambda: joey(page).count() == 0 and ga4(page).count() == 0, what="the reload without both rows' buttons")


def test_while_a_press_of_a_row_waits_its_other_buttons_cannot_be_pressed(listed, box, sheaves):  # noqa: F811
    page, ticks = listed
    path = sheaves / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Approve\n", "- [ ] Approve\n- [ ] Done\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    page.reload()
    approve, done = joey(page).nth(0), joey(page).nth(1)
    approve.click()
    assert done.is_disabled()
    approve.click()                                     # Undo
    assert done.is_enabled()
    done.click()
    assert approve.is_disabled()
    page.clock.run_for(5100)
    until(lambda: ticks, what="the tick")
    assert [(b["action"], b["word"], s) for b, s in ticks] == [(1, "Done", 200)]
    # The tick reloads the list: the test ends on the reloaded page, as its siblings do, never while the reload's
    # requests are still routed, which hung the context's teardown on CI (#118).
    until(lambda: joey(page).count() == 0, what="the reload without the row's buttons")


def test_a_refusal_beside_a_press_that_went_through_is_still_said_after_the_reload(listed, sheaves):  # noqa: F811
    page, ticks = listed
    path = sheaves / GA4[5:]
    joey(page).click()
    ga4(page).click()
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Done", "- [x] Done"), encoding="utf-8")
    page.clock.run_for(5100)
    until(lambda: len(ticks) == 2, what="both ticks")
    assert sorted(s for _, s in ticks) == [200, 409]
    until(lambda: joey(page).count() == 0, what="the reload without Joey's button")
    until(lambda: page.locator(".list-error").is_visible(), what="the refusal, said after the reload")
    assert "Done" in page.locator(".list-error").inner_text()
    # The GA4 sheaf, whose tick was refused, gets an action again, for a press that goes through.
    path.write_text(path.read_text(encoding="utf-8").replace("- [x] Done", "- [x] Done\n- [ ] Approve"), encoding="utf-8")
    page.reload()                                           # a reload by hand
    assert page.locator(".list-error").is_hidden()
    page.evaluate("sessionStorage.setItem('sheaf-list-said', 'an old refusal')")
    page.reload()                                           # said once, after the reload that kept it
    assert page.locator(".list-error").inner_text() == "an old refusal"
    ga4(page).filter(has_text="Approve").click()            # beside its Done, pressed and locked (#110)
    page.clock.run_for(5100)
    until(lambda: len(ticks) == 3, what="the third tick")
    assert ticks[2][1] == 200
    until(lambda: ga4(page).count() == 0, what="the reload after GA4's Approve")
    page.wait_for_timeout(200)
    assert page.locator(".list-error").is_hidden()          # not said again after a later press's reload


def test_a_pressed_one_off_stays_locked_when_a_press_beside_it_is_undone(listed, box, sheaves):  # noqa: F811
    page, ticks = listed
    path = sheaves / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Approve\n", "- [x] Approve\n- [ ] Done\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    page.reload()
    approve, done = joey(page).nth(0), joey(page).nth(1)
    assert approve.inner_text() == "Approve ✓" and approve.is_disabled()
    done.click()
    done.click()                                        # Undo
    assert done.is_enabled() and approve.is_disabled()
    approve.click(force=True)                           # a locked button sends nothing
    page.clock.run_for(5100)
    page.wait_for_timeout(200)
    assert ticks == []


def test_the_owner_releases_a_pressed_share_after_its_five_seconds(listed, box, sheaves):  # noqa: F811
    page, ticks = listed
    path = sheaves / JOEY[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Approve\n", "- [ ] Approve\n- [x] Share\n"),
                    encoding="utf-8")
    box.hub.the_list.poll()
    page.reload()
    share = page.locator(f'button.list-act[data-doc="{JOEY}"][data-word="Share"]')
    assert share.get_attribute("aria-pressed") == "true"
    share.click()
    assert share.inner_text() == "Undo"
    page.clock.run_for(5100)
    until(lambda: ticks, what="the release")
    assert [(b["action"], b["word"], b.get("release"), s) for b, s in ticks] == [(0, "Share", True, 200)]
    until(lambda: share.count() == 0 or share.get_attribute("aria-pressed") == "false", what="the reload")


def test_on_a_phone_a_rows_buttons_wrap_under_its_title_44_px_high_and_the_list_never_scrolls_sideways(phone):
    page, _ = phone
    title = page.locator(".list-row", has=joey(page).first).locator(".list-title").bounding_box()
    boxes = [joey(page).nth(k).bounding_box() for k in range(joey(page).count())]
    assert len(boxes) == 4
    assert all(b["y"] >= title["y"] + title["height"] for b in boxes), "a button beside the title"
    assert len({b["y"] for b in boxes}) > 1, "four buttons on one line of 360 px"
    assert all(b["height"] >= 44 and b["width"] >= 44 for b in boxes), boxes
    assert all(b["x"] >= 0 and b["x"] + b["width"] <= 360 for b in boxes), boxes
    assert page.evaluate("document.documentElement.scrollWidth") <= 360
