"""The page's script and stylesheet ship inside the package as data files.

The script finds the comment markers the .md carries (written `rd-comment` by the older
tool, `sheaf-comment` by this one) and turns each into an anchor; and neither file may
carry the name of a person or a client.
"""
import json
import re
import shutil
import subprocess
from importlib.resources import files

import pytest

PAGE = files("sheafmd") / "page"
ASSETS = ("page.js", "page.css")

# The words the page must not carry.
FORBIDDEN = ["tiroir", "acme"]

WALK_LINE = r"(?:sheaf|rd)-comment\s+id="


def text(name):
    return (PAGE / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ASSETS)
def test_the_asset_is_a_file_inside_the_package(name):
    f = PAGE / name
    assert f.is_file()
    assert len(f.read_bytes()) > 1000


def test_the_comment_walk_reads_both_markers():
    lines = [ln for ln in text("page.js").splitlines() if WALK_LINE in ln]
    assert len(lines) == 1, lines
    assert lines[0].strip().startswith("var m = /^\\s*(?:sheaf|rd)-comment")


@pytest.mark.parametrize("name", ASSETS)
def test_the_asset_names_no_person_and_no_client(name):
    body = text(name).lower()
    assert [w for w in FORBIDDEN if w in body] == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_walk_regex_matches_both_markers_with_the_id_and_no_other_word():
    line = next(ln for ln in text("page.js").splitlines() if WALK_LINE in ln)
    m = re.search(r"var m = (/.*/)\.exec\(", line)
    assert m, line
    literal = m.group(1)
    assert WALK_LINE in literal
    cases = ["rd-comment id=c1 by=x", "sheaf-comment id=c1 by=x", "  \n sheaf-comment id=c22",
             " rd-comment id=c3", "other-comment id=c1", "comment id=c1", "sheaf-comment c1",
             "xsheaf-comment id=c1"]
    script = ("const re = " + literal + ";\n"
              "const out = JSON.parse(process.argv[1]).map(s => { const m = re.exec(s); "
              "return m ? m[1] : null; });\n"
              "console.log(JSON.stringify(out));")
    r = subprocess.run(["node", "-e", script, json.dumps(cases)], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["c1", "c1", "c22", "c3", None, None, None, None]


def test_the_assets_name_neither_the_old_tool_nor_a_spec_file_of_another_repository():
    for name in ASSETS:
        body = text(name)
        assert "render" "-doc" not in body and "superpowers" not in body, name


# ---- the page talks to one hub (SPEC 8.5, 10.1) --------------------------------------

REGEX_AFTER_WORD = {"return", "typeof", "case", "in", "of", "void", "delete", "throw", "new"}


def js_strings(src):
    """Every string and template literal of a JS source, as written (escapes kept).

    A small lexer, enough for the page script: it skips comments and regex literals so
    that a quote inside either is not taken for the start of a string.
    """
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            i = src.index("*/", i) + 2
            continue
        if c in "'\"`":
            j = i + 1
            while src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i + 1:j])
            i = j + 1
            continue
        if c == "/":
            k = i - 1
            while k >= 0 and src[k].isspace():
                k -= 1
            before = src[k] if k >= 0 else ""
            word = re.search(r"(\w+)$", src[:k + 1])
            if (not before or before in "(,=:[!&|?{};+-*%<>~^"
                    or (word and word.group(1) in REGEX_AFTER_WORD)):
                j, cls = i + 1, False
                while cls or src[j] != "/":
                    if src[j] == "\\":
                        j += 1
                    elif src[j] == "[":
                        cls = True
                    elif src[j] == "]":
                        cls = False
                    j += 1
                i = j + 1
                continue
        i += 1
    return out


def js_code():
    """page.js without its whole-line comments, so a call quoted in prose is not read."""
    src = text("page.js")
    return re.sub(r"(?m)^\s*//.*$", "", src)


def test_the_string_lexer_reads_the_page_script_whole():
    strings = js_strings(text("page.js"))
    assert len(strings) > 100
    # A quoted string cannot hold a raw line break: one that does means the lexer
    # lost its place (a regex or a comment read as a string).
    assert [s for s in strings if "\n" in s] == []
    assert "rd-edit-meta" in strings


def test_no_edit_token_and_no_per_document_server_left():
    js = text("page.js")
    assert "X-Edit-Token" not in js
    assert re.search(r"CFG\.(token|ask|tell)\b", js) is None
    strings = js_strings(js)
    for gone in ("ping", "jobs", "incident", "live", "save", "comment", "export/"):
        assert gone not in strings, gone


def test_every_request_goes_to_an_absolute_hub_path():
    js = js_code()
    defs = dict(re.findall(r"function\s+(\w+)\s*\(\s*(\w+)", js))
    calls = re.findall(r"\b(fetch|new EventSource)\s*\(\s*([^,)]+)", js)
    assert calls
    wrappers = set()
    for fn, arg in calls:
        arg = arg.strip()
        if arg.startswith("'/_/"):
            continue
        assert re.fullmatch(r"\w+", arg), (fn, arg)
        named = {f for f, p in defs.items() if p == arg}
        assert named, f"{fn}({arg}): {arg} is the first parameter of no function"
        wrappers |= named
    for w in wrappers:
        sites = [m for m in re.finditer(r"(?<![\w.])" + w + r"\s*\(\s*([^,)]+)", js)
                 if not js[:m.start()].rstrip().endswith("function")]
        assert sites, w
        for m in sites:
            assert m.group(1).strip().startswith("'/_/"), (w, m.group(0))


def test_the_document_streams_and_reads_name_the_document():
    js = text("page.js")
    assert "new EventSource('/_/live?doc=' + encodeURIComponent(CFG.doc))" in js
    assert "'/_/doc?doc=' + encodeURIComponent(CFG.doc)" in js
    assert "doc: CFG.doc" in js


def test_read_state_lives_on_the_hub_not_in_local_storage():
    js = text("page.js")
    assert "rd-seen" not in js
    assert "'/_/seen'" in js
    assert "CFG.seen" in js


def test_no_inline_handler_no_javascript_url_no_eval():
    js = text("page.js")
    strings = js_strings(js)
    assert [s for s in strings if re.search(r"\bon[a-z]+\s*=", s, re.I)] == []
    assert [s for s in strings if "javascript:" in s.lower()] == []
    assert re.search(r"setAttribute\(\s*'on", js) is None
    assert re.search(r"\beval\s*\(|new\s+Function\b|setTimeout\(\s*'", js) is None
    assert re.search(r"src=\\?[\"']?https?:", js) is None


def test_thread_colours_come_from_the_reply_role_and_no_agent_is_named():
    js = text("page.js")
    assert "Claude" not in js
    assert "role === 'answer'" in js and "role === 'action'" in js
    assert "CFG.can" in js
    assert "Render this page from an agent session to Ask and Tell it." in js


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_script_parses(tmp_path):
    f = tmp_path / "page.js"
    f.write_text(text("page.js"), encoding="utf-8")
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


def test_the_page_takes_a_comments_only_change_in_place_only_from_the_version_it_holds():
    """`textSame` is the hub's word about its own last text. A page that missed a save and took
    the new hash over old text would overwrite that save at its next save, with no merge. The
    page's behaviour is checked by hand (two tabs, an outside reply); this pins the guard."""
    js = text("page.js")
    assert re.search(r"d\.textSame && d\.base === hash && applyComments\(d\)", js)


def test_the_menu_names_the_target_the_hub_recorded_and_the_buttons_it_cannot_serve_are_disabled():
    """The page's behaviour is checked by hand in a browser against a scratch hub (Claude Code,
    Codex, no agent, a session without a socket); this pins the pieces: the line reads
    "Ask and Tell → <label> · <product>" from CFG.agent, which never holds a session id; a button
    the agent cannot serve is disabled with its line from CFG.lines, in the popover, the reply
    form and the new-comment form; `/_/doc` refreshes all three at load."""
    js = text("page.js")
    assert "'Ask and Tell'" in js and "' → ' + a.label + ' · ' + a.product" in js
    assert "a.session" not in js
    assert js.count("agentButtons(") == 3                 # the definition, the reply form, the new comment
    assert "offButton('ask'" in js and "offButton('tell'" in js and "offLines(" in js
    assert "CFG.lines" in js and "'capabilities' in j" in js and "CFG.agent = j.target" in js
    assert "rd-na" in text("page.css") and "rd-agent-line" in text("page.css")


def test_an_answer_from_an_ask_is_taken_in_place_only_from_the_version_the_page_holds():
    js = text("page.js")
    m = re.search(r"addEventListener\('ask-done'.*?\n      \}\);", js, re.S)
    assert m and re.search(r"d\.textSame && d\.base === hash && applyComments\(d\)", m.group(0))


def test_the_page_knows_the_eight_words_as_the_hub_reads_them():
    # #148: a box no button names yet is told an action's by its line, with the hub's words, in the hub's order.
    from sheafmd.hub import the_list
    m = re.search(r"var ACTION_WORDS = \[(.*?)\];", (PAGE / "page.js").read_text(encoding="utf-8"))
    assert m, "page.js names no ACTION_WORDS"
    words = [w.replace("\\'", "'") for w in re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(1))]
    assert words == list(the_list.WORDS)
