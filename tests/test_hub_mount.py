"""The routes the front's loader mounts a sheaf from (#116 step 2): `/_/mount?doc=` answers the page as JSON
{title, html, config, css, toc, version, assets} with the body already through the MOUNT sanitiser, `/_/mount.js` and
`/_/mount.css` are the hub's own files, read when it starts and named by their content in the address so a browser
keeps them (#179). The page route and the share copy are unchanged."""
import hashlib
import re
import json

import pytest
from helpers import browser_on, page_meta

import sheafmd
from sheafmd import __version__, paths
from sheafmd.hub import assets
from sheafmd.hub.core import Hub

DOC = "work/plan.md"
HOSTILE = """# Plan

Some text with a [fine link](https://example.com/x) and a [bad one](javascript:alert(1)).

<img src="https://evil.example/pixel.gif" alt="pixel">
<script>alert(1)</script>
<p style="position:fixed;top:0;color:#336699" onclick="alert(1)">styled</p>
<a href="https://example.com/" target="_blank">out</a>

## Second part

Closing words.
"""


@pytest.fixture
def hostile(work, hub):
    f = work / "plan.md"
    f.write_text(HOSTILE, encoding="utf-8")
    hub.roots.for_document(f)
    return f


def attach(browser, path):
    r = browser.post("/_/render", {"path": str(path), "settings": {}}, key=True, cookie=False)
    assert r.status == 200, r.text


def test_the_mount_answer_is_json_with_the_body_the_meta_and_the_title(browser, hostile):
    attach(browser, hostile)
    r = browser.get(f"/_/mount?doc={DOC}")
    assert r.status == 200 and r.headers["Content-Type"].startswith("application/json")
    got = r.json()
    assert got["title"] == "Plan" and isinstance(got["toc"], bool)
    assert "Second part" in got["html"] and "Closing words" in got["html"]
    assert got["config"]["name"] == "plan.md" and got["config"]["hash"] and got["config"]["doc"] == DOC
    assert got["config"]["edit"] is True and got["config"]["editable"]
    assert got["version"] == __version__
    assert "BASE" not in got["css"] and got["css"].strip()          # the document's own styles, no page.css


def test_the_mounted_body_went_through_the_mount_sanitiser(browser, hostile):
    attach(browser, hostile)
    html = browser.get(f"/_/mount?doc={DOC}").json()["html"]
    assert "evil.example" not in html and "<script" not in html and "onclick" not in html and "fixed" not in html  # html is the body only
    assert 'href="https://example.com/x"' in html and "javascript:" not in html
    assert "color:#336699" in html
    assert 'rel="noopener noreferrer"' in html and "_blank" not in html


def test_the_page_route_keeps_the_old_rules(browser, hostile):
    attach(browser, hostile)
    page = browser.get("/work/plan.md").text
    assert "<script>alert(1)" not in page and 'onclick="alert(1)"' not in page
    assert "position:fixed" in page            # the frame's CSP, not the sanitiser, holds a style there


def test_the_mount_answer_carries_the_state_the_page_route_puts_in_the_meta(browser, hostile):
    attach(browser, hostile)
    meta = page_meta(browser.get("/work/plan.md").text)
    cfg = browser.get(f"/_/mount?doc={DOC}").json()["config"]
    for key in ("name", "hash", "doc", "root", "boot", "version", "me", "comments", "seen", "agent", "can", "lines", "actions"):
        assert key in cfg, key
    assert cfg["hash"] == meta["hash"]


def test_the_mount_answer_needs_a_signed_in_browser_or_the_key(browser, hostile):
    attach(browser, hostile)
    assert browser.get(f"/_/mount?doc={DOC}", cookie=False).status == 401
    assert browser.get(f"/_/mount?doc={DOC}", cookie=False, key=True).status == 200


@pytest.mark.parametrize("doc", ["", "work/nothing.md", "../etc/passwd", "work/plan.txt"])
def test_a_document_that_is_not_there_is_refused_not_rendered(browser, hostile, doc):
    attach(browser, hostile)
    assert browser.get(f"/_/mount?doc={doc}").status in (400, 404)


def test_the_mount_assets_are_the_hubs_own_files_and_cache_by_content(browser):
    js = browser.get(f"/_/mount.js?v={browser.hub.assets['mount.js'].tag}", cookie=False)
    css = browser.get(f"/_/mount.css?v={browser.hub.assets['mount.css'].tag}", cookie=False)
    assert js.status == 200 and js.headers["Content-Type"].startswith("text/javascript")
    assert css.status == 200 and css.headers["Content-Type"].startswith("text/css")
    for r in (js, css):
        assert "immutable" in r.headers["Cache-Control"] and "max-age=31536000" in r.headers["Cache-Control"]
        assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "rebuild" in js.text and ":host" in css.text
    # The page's own script and style follow the loader's (slice iii): one request each brings the whole page.
    assert "sheafPage" in js.text and "#rd-menu-btn" in css.text


@pytest.mark.parametrize("asset", sorted(assets.MOUNT_ASSETS))
def test_the_name_kept_for_a_year_is_the_hash_of_what_is_served(browser, asset):
    # #172: #152 changed mount.css under 1.0.1's `?v=`, and browsers that had kept it for a year never saw the change.
    # #179: the name is the content, so no change can keep the old name.
    r = browser.get(f"/_/{asset}?v={browser.hub.assets[asset].tag}", cookie=False)
    assert browser.hub.assets[asset].tag == hashlib.sha256(r.body).hexdigest()[:assets.TAG_LENGTH]
    assert "immutable" in r.headers["Cache-Control"]


def test_an_asset_asked_without_its_hash_is_not_cached_for_a_year(browser):
    for v in ("0.0.0-old", __version__):          # a version is no longer a name the hub keeps
        r = browser.get(f"/_/mount.js?v={v}", cookie=False)
        assert r.status == 200 and r.headers["Cache-Control"] == "no-store"
    assert browser.get("/_/mount.js", cookie=False).headers["Cache-Control"] == "no-store"


def copy_of_the_page_files(to):
    to.mkdir()
    for files in assets.MOUNT_ASSETS.values():
        for f in files:
            (to / f).write_bytes((assets.installed() / f).read_bytes())
    return to


def test_two_installs_with_different_files_name_their_assets_differently(tmp_path):
    a, b = copy_of_the_page_files(tmp_path / "a"), copy_of_the_page_files(tmp_path / "b")
    assert assets.load("1.0.0", a) == assets.load("1.0.0", b)
    (b / "page.css").write_text((b / "page.css").read_text(encoding="utf-8") + "\n.x{color:red}\n", encoding="utf-8")
    old, new = assets.load("1.0.0", a), assets.load("1.0.0", b)
    assert old["mount.css"].tag != new["mount.css"].tag and old["mount.css"].body != new["mount.css"].body
    assert old["mount.js"] == new["mount.js"]
    # mount.js carries the hub's version: another version is another file, under another name, of the same scripts
    assert assets.load("1.0.1", a)["mount.js"].tag != old["mount.js"].tag
    assert assets.load("1.0.1", a)["mount.js"].source == old["mount.js"].source
    # other scripts under the same version are other scripts: a page in memory takes it for an upgrade
    (b / "page.js").write_text((b / "page.js").read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
    assert assets.load("1.0.0", b)["mount.js"].source != old["mount.js"].source


def test_a_hub_serves_the_files_it_started_with_while_a_reinstall_changes_them_under_it(work, tmp_path, monkeypatch):
    """#179: an upgrade in place reinstalls the package, then restarts the hub. In between, the old hub must not hand
    out the new files under the name it gave the old ones, which browsers keep for a year; nor a rollback the reverse."""
    page = copy_of_the_page_files(tmp_path / "page")
    monkeypatch.setattr(assets, "installed", lambda: page)
    old = browser_on(Hub(port=27419, key=paths.ensure_key(), started_by="test"))
    tag, body = old.hub.assets["mount.css"].tag, old.get("/_/mount.css", cookie=False).body
    (page / "mount.css").write_text(":host{color:red}\n", encoding="utf-8")        # the reinstall, before the restart
    r = old.get(f"/_/mount.css?v={tag}", cookie=False)
    assert r.body == body and "immutable" in r.headers["Cache-Control"]
    new = browser_on(Hub(port=27419, key=paths.ensure_key(), started_by="test"))   # the restart
    assert new.hub.assets["mount.css"].tag != tag
    assert new.get(f"/_/mount.css?v={new.hub.assets['mount.css'].tag}", cookie=False).body.startswith(b":host{color:red}")
    assert new.get(f"/_/mount.css?v={tag}", cookie=False).headers["Cache-Control"] == "no-store"


def test_the_mount_answer_names_the_style_the_loader_links_and_the_scripts_the_hub_serves(browser, hostile):
    attach(browser, hostile)
    got = browser.get(f"/_/mount?doc={DOC}").json()
    assert got["assets"] == {n: a.tag for n, a in browser.hub.assets.items()}
    assert got["script"] == browser.hub.assets["mount.js"].source


def test_the_mount_json_cannot_be_framed_or_sniffed_into_a_page(browser, hostile):
    attach(browser, hostile)
    r = browser.get(f"/_/mount?doc={DOC}")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and "html" not in r.headers["Content-Type"]
    assert json.loads(r.text)["title"] == "Plan"


def test_the_mounted_css_selects_the_host_and_the_wrapper_where_a_page_of_its_own_selects_its_root_and_body(browser, hostile):
    """In a shadow root there is no `html`, `:root` or `body`: the theme's variables go on `:host` and the body's rules on
    the wrapper `.rd-root`, so a mounted page has the fonts, colours and wrapping (#128) a page of its own has."""
    attach(browser, hostile)
    css = browser.get(f"/_/mount?doc={DOC}").json()["css"]
    bare = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    selectors = re.findall(r"(?:^|[{}])\s*([^{}@][^{}]*?)\s*\{", bare)
    words = {w for s in selectors for part in s.split(",") for w in [part.strip().split()[0] if part.strip() else ""]}
    assert not {w for w in words if re.match(r"(?:html|body|:root)(?![\w-])", w)}, sorted(words)
    assert re.search(r":host\s*\{[^}]*--bg", css) and re.search(r"\.rd-root\s*\{[^}]*overflow-wrap:break-word", css)


def test_only_the_mounted_styles_take_the_fronts_font_and_the_page_and_the_share_copy_keep_the_themes(browser, hostile):
    """#152: the rule that hands the wrapper the host's `--front-font` is in the hub's `/_/mount.css`, which a mounted list
    loads, and first in a mounted page's styles, which are never kept: before the theme, which cannot swallow it there."""
    attach(browser, hostile)
    rule = ':host([style*="--front-font"]) .rd-root{font-family:var(--front-font)}'
    assert browser.get("/_/mount.css", cookie=False).text.count(rule) == 1
    css = browser.get(f"/_/mount?doc={DOC}").json()["css"]
    assert css.startswith(rule + "\n") and css.count(rule) == 1
    page = browser.get("/work/plan.md")
    assert page.status == 200 and "--front-font" not in page.text
    assert "--front-font" not in sheafmd.render(hostile, share=True)


def test_the_mount_script_knows_the_version_of_the_hub_that_served_it(browser):
    """A hub upgraded under a mounted page answers with a new version; the script in memory is the old one, and it can only
    tell by knowing its own (#116 slice v, Ines's P2)."""
    js = browser.get("/_/mount.js", cookie=False).text
    assert f"const VERSION = {json.dumps(__version__)};" in js
    assert f"const SCRIPT = {json.dumps(browser.hub.assets['mount.js'].source)};" in js       # and its scripts' (#179)
    assert "@@SHEAF_VERSION@@" not in js and "@@SHEAF_SCRIPT@@" not in js
