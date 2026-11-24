"""The name of a session and its click (session.js) reach a page opened on its own address, not only the mount bundle:
a member's bookmarked page has the page script and nothing else, and its byline must still link to the chat, the Remote
Control link or AgentView (SPEC 6.2 item 11)."""
import json
import shutil
import subprocess
from importlib.resources import files

import pytest

from sheafmd.hub.assets import MOUNT_ASSETS
from sheafmd.render import page_script

NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def test_the_script_of_a_page_defines_the_session_kit_before_the_page_uses_it():
    script = page_script()
    assert "window.sheafSession = " in script
    assert script.index("window.sheafSession = ") < script.index("takeWayBack")


def test_the_mount_bundle_holds_the_kit_once_and_before_the_sheaf_view():
    files_ = MOUNT_ASSETS["mount.js"]
    assert files_.count("session.js") == 1 and files_.index("session.js") < files_.index("sheaf.js")
    assert "window.sheafSession = " not in (files("sheafmd") / "page" / "sheaf.js").read_text(encoding="utf-8")


@NODE
def test_the_kit_of_a_page_script_makes_the_chat_link_of_a_way_back():
    js = (page_script() + """
    ;var made = [];
    var doc = {createElement: function (t) { var e = {tagName: t.toUpperCase(), attrs: {}, dataset: {},
      setAttribute: function (k, v) { this.attrs[k] = v; }, hasAttribute: function (k) { return k in this.attrs; }};
      return e; }, createTextNode: function (t) { return {text: t}; }};
    var a = window.sheafSession.node(doc, 'Cosima', {kind: 'chat', href: '/chat/42'});
    var b = window.sheafSession.node(doc, 'Cosima', {kind: 'chat', href: 'https://elsewhere.example/x'});
    console.log(JSON.stringify([a.tagName, a.attrs.href, b.text]));
    """)
    # page.js needs a browser; only the kit is run: the part of the script before page.js starts
    kit = js.replace(page_script(), (files("sheafmd") / "page" / "session.js").read_text(encoding="utf-8"))
    out = subprocess.run(["node", "-e", "var window = {};\n" + kit], capture_output=True, text=True, timeout=30, check=True)
    assert json.loads(out.stdout) == ["A", "/chat/42", "Cosima"]
