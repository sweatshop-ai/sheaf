"""A page served through the proxy socket (SPEC 9.9, 10.1, 10.6, 10.8): its meta block says `proxy`
and the member's id, so it keeps drafts under keys that hold that id, says to sign in to the front
again where it would say `sheaf open`, and shows the line of 10.6 under Ask and Tell. The page is
served here by the loopback port with a member's meta block: what the script does with it is the
same whichever listener served it."""
import base64
import json
import os

import pytest

from helpers import BEA
from pagehelp import P2, type_at_end, until
from sheafmd.hub import proxy

pytestmark = pytest.mark.page


@pytest.fixture
def as_member(site, work):
    """The site's pages carry Bea's meta block."""
    hub = site.hub
    bea = proxy.Member(BEA, "Bea", (str(work),))
    real = hub.page
    hub.page = lambda e, nonce, member=None: real(e, nonce, member=bea)
    return bea


def notice(page):
    return page.evaluate("(() => { const n = document.querySelector('#rd-notice');"
                         " return n.hidden ? '' : n.textContent; })()")


def keys(page):
    return json.loads(page.evaluate("JSON.stringify(Object.keys(localStorage))"))


def test_a_members_draft_is_kept_under_their_id_not_the_port(tab, site, as_member):
    tab.open()
    type_at_end(tab.page, P2, " and plums")
    until(lambda: f"sheaf-draft:m:{BEA}:work/plan.md" in keys(tab.page), what="the member's draft")
    assert not any(k.startswith(f"sheaf-draft:{site.port}:") for k in keys(tab.page))


def test_a_member_is_told_to_sign_in_to_the_front_again_not_to_run_sheaf_open(tab, site, as_member):
    tab.open()
    site.kill()
    site.start(key=base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode())   # its cookie is no good now
    until(lambda: "not signed in" in notice(tab.page), timeout=15, what="the sign-in message")
    n = notice(tab.page)
    assert "Sign in to this site again" in n and "sheaf open" not in n and "signin-url" not in n


def test_ask_and_tell_show_the_line_of_10_6(tab, site, as_member):
    tab.open()
    assert proxy.PROXY_LINE in tab.page.content()
