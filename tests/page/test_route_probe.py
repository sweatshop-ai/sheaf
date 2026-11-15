"""The probe of conftest.py's route wrapper (tickets 100 and 119), tested on a replacement page: no browser, so these
carry no `page` mark and run in the plain suite too."""
import re

from conftest import until_live


class ReplacementPage:
    """A page that answers the probe of `until_live` like a browser that has not started to intercept: `answers` in turn."""
    url = "http://127.0.0.1:1/doc"

    def __init__(self, answers):
        self.answers, self.asked = list(answers), []

    def evaluate(self, expression):
        self.asked.append(expression)
        return self.answers.pop(0)

    def wait_for_timeout(self, ms):
        pass


def test_the_probe_of_a_route_is_sent_until_the_route_has_caught_it():
    page, log = ReplacementPage([0, 0, 204]), []
    until_live(page, "**/_/comment", log)
    assert len(page.asked) == 3 and all("x-route-probe" in a and "/_/comment" in a for a in page.asked)
    assert "caught its probe at try 3" in log[-1][1]


def test_a_route_of_another_url_is_not_probed():
    page = ReplacementPage([])
    for pattern in ("**/_/save", re.compile(r"/_/tell$"), re.compile(r"/_/doc\?")):
        until_live(page, pattern, [])
    assert page.asked == []
