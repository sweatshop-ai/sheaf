"""A client's page opened through the agency (SPEC 9.9): its address is under `Clients/`, which the agency never streams. The page
polls `/_/doc` for it and opens no `/_/live`; the agency answering is the hub answering, so it never says the hub is unreachable.
The agency's relay is not here: the served page is given the address of a client page, and its own hub answers `/_/doc` for it."""
import pytest
from pagehelp import DOC, T0, clock_at, run_clock, until

pytestmark = pytest.mark.page

CLIENT_DOC = "Clients/acme/" + DOC


def as_client_page(page, older_client=False):
    """The page for DOC, with the address of a client page in its meta; a request for that address is answered as the hub of DOC would,
    and a stream for it is refused as the agency refuses it (404). Returns the list of what the page asked, as (path, doc)."""
    seen = []

    def serve(route):
        got = route.fetch()
        route.fulfill(response=got, body=got.text().replace(f'"doc": "{DOC}"', f'"doc": "{CLIENT_DOC}"'))

    def answer(route):
        url = route.request.url
        seen.append(url.split("/_/")[1].split("?")[0])
        if "/_/live" in url:
            route.fulfill(status=404, content_type="application/json", body='{"error": "no such document"}')
        elif older_client:       # an older client hub still sends its agent, its targets and its Work
            got = route.fetch(url=url.replace("Clients/acme/", "").replace("Clients%2Facme%2F", "")).json()
            route.fulfill(json={**got, "work": {}, "targets": [{"id": "agent:x", "name": "x"}], "capabilities": ["deliver"]})
        else:
            route.fulfill(response=route.fetch(url=url.replace("Clients/acme/", "").replace("Clients%2Facme%2F", "")))
    page.route(f"**/{DOC}", serve)
    page.route("**/_/live*", answer)
    page.route("**/_/doc*", answer)
    return seen


def banner(page):
    return page.evaluate("document.body.innerText.includes('Hub unreachable')")


def test_a_client_page_opens_no_stream_and_never_says_the_hub_is_unreachable(tab, site):
    page = tab.page
    seen = as_client_page(page)
    page.clock.install(time=clock_at(T0))
    tab.open()
    run_clock(page, 40_000)
    assert "live" not in seen and not banner(page)


def test_a_client_page_is_polled_through_doc_every_30_seconds(tab, site):
    page = tab.page
    seen = as_client_page(page)
    page.clock.install(time=clock_at(T0))
    tab.open()
    run_clock(page, 1_000)
    first = seen.count("doc")
    run_clock(page, 28_000)
    assert seen.count("doc") == first          # not before the interval
    run_clock(page, 3_000)
    until(lambda: seen.count("doc") > first, what="the poll through /_/doc")
    assert "live" not in seen and not banner(page)


def test_a_poll_never_brings_the_clients_agent_work_or_targets_back_on_the_page(tab, site):
    page = tab.page
    seen = as_client_page(page, older_client=True)
    page.clock.install(time=clock_at(T0))
    tab.open()
    run_clock(page, 1_000)
    first = seen.count("doc")
    run_clock(page, 31_000)
    until(lambda: seen.count("doc") > first, what="the poll through /_/doc")
    assert page.evaluate("document.querySelectorAll('#rd-work-btn, button.rd-target, #rd-target-change').length") == 0
