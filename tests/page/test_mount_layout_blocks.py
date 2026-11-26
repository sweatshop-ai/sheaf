"""The layout divs through `page/mount.js` in real browsers: the same CASES as the server sanitiser
(tests/test_block_sanitize_layout.py). A page test: it runs in CI only."""
import pytest

from test_block_sanitize_layout import CASES
from test_mount_allowlist import ENGINES, env, pw, rebuild_into_page   # noqa: F401  (fixtures)

pytestmark = pytest.mark.page


@pytest.mark.parametrize("html,ident,cls,attrs", CASES, ids=[f"{i:02d}" for i in range(len(CASES))])
def test_a_layout_div_keeps_its_declared_attributes_and_nothing_else(env, html, ident, cls, attrs):
    rebuild_into_page(env, html)
    env.wait_for_timeout(100)
    (div,) = env.evaluate("""() => Array.from(document.querySelectorAll('#out div')).map(d => ({
        id: d.id, cls: d.getAttribute('class'), attrs: Array.from(d.attributes).map(a => [a.name, a.value])}))""")
    assert div["cls"] == cls, env.engine
    assert div["id"] == (f"u-{ident}" if ident else ""), env.engine
    assert {k: v for k, v in div["attrs"] if k not in ("id", "class")} == attrs, (env.engine, div)
