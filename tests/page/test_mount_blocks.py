"""A declared Rich block through `page/mount.js` in real browsers (block editor v1, ticket 04): the same CASES as the server
sanitiser (tests/test_block_sanitize.py). Both let through exactly the declared `data-<attr>` with an allowed value on
`div.<type>`, its id (prefixed `u-` by mount.js) and its type as the only class. A page test: CI and t-compute only."""
import pytest

from test_block_sanitize import CASES
from test_mount_allowlist import ENGINES, env, pw, rebuild_into_page   # noqa: F401  (fixtures)

pytestmark = pytest.mark.page


def blocks_of(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll('#out div')).map(d => ({
        id: d.id, cls: d.getAttribute('class'), attrs: Array.from(d.attributes).map(a => [a.name, a.value])}))""")


@pytest.mark.parametrize("html,ident,cls,data", CASES, ids=[f"{i:02d}" for i in range(len(CASES))])
def test_a_declared_block_keeps_its_declared_data_attributes_and_nothing_else(env, html, ident, cls, data):
    rebuild_into_page(env, html)
    env.wait_for_timeout(100)
    (div,) = blocks_of(env)
    assert div["cls"] == cls, env.engine
    assert div["id"] == (f"u-{ident}" if ident else ""), env.engine
    got = {k: v for k, v in div["attrs"] if k.startswith("data-")}
    assert got == data, (env.engine, div)
    assert {k for k, _ in div["attrs"]} <= {"id", "class"} | set(data), (env.engine, div)
    assert env.evaluate("window.__pwned || 0") == 0


def test_the_list_in_mount_js_is_the_one_the_declarations_generate():
    import subprocess
    import sys
    assert subprocess.run([sys.executable, "-m", "sheafmd.blocks.declarations"]).returncode == 0
