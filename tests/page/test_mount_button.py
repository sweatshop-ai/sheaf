"""The inline button through `page/mount.js` in real browsers (block editor v1, ticket 06): the same CASES as the server
sanitiser (tests/test_block_button.py). Both let through exactly the declared `size` and `data-variant` on `span.button`
(no id, no other class, no style or handler) and, on the link inside, an href of http, https, mailto or a relative address
and nothing else. A page test: it runs in CI only."""
import pytest

from test_block_button import CASES
from test_mount_allowlist import ENGINES, env, pw, rebuild_into_page   # noqa: F401  (fixtures)

pytestmark = pytest.mark.page


def button_of(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll('#out span')).map(s => ({
        attrs: Object.fromEntries(Array.from(s.attributes).map(a => [a.name, a.value])),
        link: s.querySelector('a') ? Object.fromEntries(Array.from(s.querySelector('a').attributes).map(a => [a.name, a.value])) : null,
        text: s.textContent}))""")


@pytest.mark.parametrize("html,span,link", CASES, ids=[f"{i:02d}" for i in range(len(CASES))])
def test_a_button_keeps_its_declared_attributes_and_a_safe_link_and_nothing_else(env, html, span, link):
    rebuild_into_page(env, html)
    env.wait_for_timeout(100)
    (button,) = button_of(env)
    assert button["attrs"] == span, (env.engine, button)
    got = dict(button["link"])
    if link:
        assert got.pop("rel") == "noopener noreferrer"
    assert got == link, (env.engine, button)
    assert button["text"] == "Go"
    assert env.evaluate("window.__pwned || 0") == 0

