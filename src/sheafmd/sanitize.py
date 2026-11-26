"""
sheafmd.sanitize — the raw-HTML sanitiser (SPEC 9.5).

A markdown file can carry raw HTML, and pandoc passes it straight through. A
document that arrives from someone else, or from an agent that read a web page, can
therefore carry a script into the page the hub serves and into a share copy that goes
to a client. This module takes pandoc's output and removes what can run or phone home:

    elements removed with their content   script style iframe frame frameset object
                                          embed applet base meta link form button
                                          textarea select template noscript
    input                                 removed unless its type is exactly "checkbox", ASCII case
                                          aside (task lists)
    attributes removed                    every on*, srcdoc, formaction, srcset, ping
                                          (srcset and ping hold URLs outside the list below),
                                          contenteditable (the page sets it, never the document)
    href src action poster background     kept only for a relative URL, a fragment,
    xlink:href                            http:, https:, mailto:, file:, and
                                          data:image/(png|jpeg|gif|webp) on img src
    kept                                  HTML comments (block sentinels and sheaf
                                          comments depend on them), details, summary,
                                          tables, inline svg without scripts

The output is the parse tree written out again, never the original text with holes
cut in it. Whatever the parser did not take for markup comes out escaped, so a
construct a browser would read differently from this parser cannot carry a tag through.
Two kinds of node have no honest round trip and are always dropped: CDATA sections,
processing instructions and declarations (a browser ends them at the first ">"), and a
comment a browser could end before this parser does (a "--!>", or a start with ">").
A second pass over the result makes sure that what came out is a fixed point.

MOUNT MODE (`sanitize(..., mount=True)`, #116 step 2). The rectoverso page used to run in a frame under a CSP of its own;
mounted in the front's document it has none, so this module also closes what that CSP closed. Beyond the above:
audio, video, picture and their sources are removed, an <img> is kept only for a relative path or data:image/(png|jpeg|gif|webp)
(any other address is a tracking pixel; the alt text stays), svg <use>, <image>, <foreignObject>, animation and links, and all
MathML, are removed, a link keeps http, https, mailto and relative addresses with rel="noopener noreferrer" and no target,
a style attribute keeps only the declarations of an allow-list with a strict value grammar, and the names the page itself
uses (rd- classes and ids, data-rd-*, a name attribute) are removed. The browser rebuilds the tree again from an allow-list
(page/mount.js); neither layer relies on the other.

The hub also sends a Content-Security-Policy with a nonce (SPEC 9.5), which is the
defence that holds when this one is wrong. A share copy has no such header, so this
module is the only defence there, and the share copy has no comments at all.
"""
import re

from bs4 import BeautifulSoup, Comment
from bs4.element import PreformattedString, Tag

from .blocks import declarations

REMOVE = frozenset({
    "script", "style", "iframe", "frame", "frameset", "object", "embed", "applet", "base",
    "meta", "link", "form", "button", "textarea", "select", "template", "noscript",
})
# Obsolete elements whose content a browser reads as raw text and Python's HTML parser
# reads as raw text or as markup depending on its version (3.14 changed it). Not in the
# spec's list; nothing pandoc writes and no document needs them, and without them the
# result cannot depend on which Python runs it.
ALSO_REMOVED = frozenset({"xmp", "plaintext", "noembed", "noframes"})
# SVG animation can set an href to a javascript: URL after the attribute check ran.
_ANIMATION = frozenset({"set", "animate"})
_ANIMATED_ATTR = re.compile(r"^(?:xlink:)?href$|^on", re.I)

URL_ATTRS = frozenset({"href", "src", "action", "poster", "background", "xlink:href"})
# Attributes that go whatever they hold. srcset (several URLs, each loaded) and ping (a
# POST to each URL on a click) carry addresses that 9.5's list does not allow.
# contenteditable is the page's own to set (setEditing): a surface the document makes
# editable is outside what the page guards.
DROPPED_ATTRS = frozenset({"srcdoc", "formaction", "srcset", "ping", "contenteditable"})
SAFE_SCHEMES = frozenset({"http", "https", "mailto", "file"})
_SAFE_DATA = re.compile(r"^data:image/(?:png|jpeg|gif|webp)[;,]", re.I)
_SCHEME = re.compile(r"^([^/?#]*):")
_STRIP_CONTROL = re.compile(r"[\x00-\x20\x7f]+")
MAX_PASSES = 3

# Mount mode.
_BLOCKS = declarations.allow_list()          # {type: {"tag", "attrs": {"data-<name>": [values]}}}: one list for both layers
MOUNT_REMOVED = frozenset({
    "video", "audio", "source", "track", "canvas", "portal", "use", "image", "foreignobject", "animate", "set",
    "animatetransform", "animatemotion", "math", "maction", "annotation-xml", "mglyph", "semantics",
})
MOUNT_MAX_DEPTH = 100          # no real page nests deeper; Chromium's DOMParser costs the square of the depth (20 s at 100,000)
_MOUNT_LINK_SCHEMES = frozenset({"http", "https", "mailto"})
_MOUNT_DROPPED_ATTRS = frozenset({"target", "name", "background", "action", "poster", "longdesc", "manifest", "formtarget"})
_EXTERNAL_URL = re.compile(r"url\(\s*['\"]?\s*(?!#)", re.I)
_LENGTH = r"(?:0|\d{1,4}(?:\.\d{1,3})?(?:px|em|rem|%|pt|ch|ex))"
_COLOR = (r"(?:#[0-9a-f]{3,8}|[a-z]{3,24}|(?:rgb|hsl)a?\(\s*\d{1,3}(?:\.\d+)?%?(?:\s*,\s*\d{1,3}(?:\.\d+)?%?){2}"
          r"(?:\s*,\s*(?:0|1|0?\.\d+|\d{1,3}%))?\s*\))")
_LINE_STYLE = r"(?:none|hidden|dotted|dashed|solid|double|groove|ridge|inset|outset)"
_SIDES = r"(?:-top|-right|-bottom|-left)?"
_MOUNT_STYLE = {                       # property -> the whole value, as a regex; nothing else is kept
    "text-align": r"(?:left|right|center|justify|start|end)",
    "vertical-align": r"(?:baseline|sub|super|top|middle|bottom|text-top|text-bottom)",
    "font-weight": r"(?:normal|bold|bolder|lighter|[1-9]00)",
    "font-style": r"(?:normal|italic|oblique)",
    "text-decoration": r"(?:none|(?:underline|overline|line-through)(?: (?:underline|overline|line-through))*)",
    "color": _COLOR,
    "background-color": _COLOR,
    "fill": _COLOR,
    "stroke": _COLOR,
    "width": _LENGTH,
    "max-width": _LENGTH,
    "list-style-type": r"(?:none|disc|circle|square|decimal|lower-alpha|upper-alpha|lower-roman|upper-roman|lower-latin|upper-latin)",
}
for _side in ("", "-top", "-right", "-bottom", "-left"):
    _MOUNT_STYLE["margin" + _side] = rf"{_LENGTH}(?: {_LENGTH}){{0,3}}"
    _MOUNT_STYLE["padding" + _side] = rf"{_LENGTH}(?: {_LENGTH}){{0,3}}"
    _MOUNT_STYLE["border" + _side] = rf"(?:{_LENGTH}|{_LINE_STYLE}|{_COLOR})(?: (?:{_LENGTH}|{_LINE_STYLE}|{_COLOR})){{0,2}}"
_MOUNT_STYLE = {k: re.compile(v + r"\Z", re.I) for k, v in _MOUNT_STYLE.items()}
# What the pre-pass walks over, in the order a browser meets it: an empty comment opener
# (`<!-->` or `<!--->`), which is the one to rewrite; a whole comment; the body of a title or
# a textarea, which is text; a tag with its quoted attribute values. Only the first is changed.
_MARKUP_RE = re.compile(r"""
      (?P<empty><!---?>)
    | <!--[\s\S]*?(?:-->|--!>|\Z)
    | <(?P<raw>title|textarea)(?=[\s/>])[^>]*>[\s\S]*?(?:</(?P=raw)\s*>|\Z)
    | </?[A-Za-z](?:=\s*"[^"]*"?|=\s*'[^']*'?|[^>])*>?
    """, re.X | re.I)


def _end_empty_comments(fragment: str) -> str:
    """Write each empty comment opener, `<!-->` and `<!--->`, as the whole comment `<!---->`.
    A browser ends the comment at the `>`. Python's parser, up to 3.11.13, 3.12.11 and 3.13.5,
    reads the opener as text or as the start of a comment that runs to a later `-->`, and from
    3.11.14, 3.12.12 and 3.13.6 it ends the comment at the `>` only when no later `-->` exists,
    so the markup after it comes out differently by version, and a result must not depend on
    the Python that runs."""
    return _MARKUP_RE.sub(lambda m: "<!---->" if m["empty"] else m[0], fragment)


class _Tag(Tag):
    """A tag that is equal to itself and to no other. bs4 writes a tree out with a loop that asks
    `tag != stop`, and `!=` on two tags compares their contents, one level of the stack for each
    level the two nest, so a document of quotes 248 levels deep (on 3.11; 496 on 3.12) raised
    RecursionError from `str(soup)`. How deep a document may nest is not for the interpreter to
    say, and the recursion limit is the process's, which the hub's other threads share, so it is
    not raised. Nothing here compares one tag with another by what it holds."""

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other

    __hash__ = object.__hash__

    # `tag.decomposed` reads `_decomposed`, and on a tag that was never decomposed bs4 does not find
    # the attribute and falls through to `tag.find("_decomposed")`, a search of everything below the
    # tag: for each tag of a tree nested n levels, n steps. With the attribute here, it is read at once.
    _decomposed = False


def _url_ok(tag, attr: str, value: str) -> bool:
    # A browser ignores tab, newline and carriage return anywhere in a URL and trims
    # leading and trailing control characters and spaces, so "java\nscript:" is
    # "javascript:". Test the URL the way the browser will read it.
    v = _STRIP_CONTROL.sub("", value)
    m = _SCHEME.match(v)
    if not m:
        return True            # relative URL, fragment, query, or protocol-relative
    scheme = m.group(1).lower()
    if scheme in SAFE_SCHEMES:
        return True
    return (scheme == "data" and tag.name == "img" and attr == "src"
            and bool(_SAFE_DATA.match(v)))


def _flatten_deep(soup, log: list[str]) -> None:
    """Replace every element nested deeper than MOUNT_MAX_DEPTH by its text. Walks with a stack, not recursion."""
    stack = [(child, 1) for child in soup.contents]
    while stack:
        node, depth = stack.pop()
        if not isinstance(node, Tag):
            continue
        if depth > MOUNT_MAX_DEPTH:
            log.append(f"  - <{node.name}> nested deeper than {MOUNT_MAX_DEPTH} replaced by its text")
            node.replace_with(node.get_text())
            continue
        stack.extend((child, depth + 1) for child in node.contents)


_EDITABLE_OR_ESCAPE = re.compile(r"user-modify|\\", re.I)


_UNQUOTED_URL = re.compile(r"(?![ \t\n\r\f]*[\"'])[ \t\n\r\f]*(?:\\.|[^)\\])*(?:\)|\\?\Z)", re.S)
_NAME_RUN = re.compile(r"(?:[\w\-\x00]|[^\x00-\x7f]|\\(?:[0-9a-fA-F]{1,6}(?:\r\n|[ \t\n\r\f])?|[^\n\r\f]|\Z))+")
_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})(?:\r\n|[ \t\n\r\f])?|(.))", re.S)
_STRING_ESCAPE = re.compile(r"\\(?:[0-9a-fA-F]{1,6}(?:\r\n|[ \t\n\r\f])?|\r\n|.)", re.S)
_CLOSER = {"(": ")", "[": "]", "{": "}"}


def _unescaped(name: str) -> str:
    """A CSS name with its escapes read (`\\75 rl` is `url`), as CSS Syntax 3 does when it decides what a name is."""
    return _ESCAPE.sub(lambda m: (chr(int(m[1], 16)) if m[1] and 0 < int(m[1], 16) <= 0x10FFFF and not 0xD800 <= int(m[1], 16) <= 0xDFFF else "\ufffd") if m[1] else (m[2] if m[2] and m[2] != "\x00" else "\ufffd"), name)


def _declarations(value: str) -> list[str]:
    """A style attribute cut at the `;` that end a declaration, by the rules of the CSS Syntax 3 tokenizer. A `;` inside a CSS
    string (a quote ends at the same quote, or at a newline, and a backslash takes an escape: a hex one with the white space after it, a newline included, or the next character, CRLF counting as one), inside a comment or inside
    a `()`, `[]` or `{}` block (`url(data:image/png;base64,…)`) does not end one; a block ends only at its own closer, so
    `(]` leaves a `(` open, and a closer that does not close the innermost open block is ignored. A name is read whole, escapes included (CR and FF are newlines, so a backslash before one is no escape, and NUL is a name character), so `\\75 url(` and
    `a\\:url(` are functions called something else, `@url(` and `#url(` an at-keyword and a hash followed by a `(`, and only a
    name that reads `url` (any letter case), that no `@` or `#` leads and that `(` follows, is a url. A `url(` that no quote
    follows, white space aside, is one token up to its first `)` (a backslash takes the next character), so a `/*` or a quote
    inside it opens no comment and no string. A block left open runs to the end, as in a browser. Only the pieces are cut here:
    the name is searched in each piece whole, so a split that differs from a browser's can keep more or less, never hide the name."""
    parts, start, i, n, quote, blocks = [], 0, 0, len(value), "", []
    while i < n:
        c = value[i]
        if quote:
            if c == "\\":
                i = m.end() if (m := _STRING_ESCAPE.match(value, i)) else i + 1
                continue
            if c == quote or c in "\n\r\f":
                quote = ""
        elif c in "\"'":
            quote = c
        elif value.startswith("/*", i):
            end = value.find("*/", i + 2)
            i = n if end < 0 else end + 1
        elif value.startswith("<!--", i):
            i += 4
            continue
        elif c in "@#" and (m := _NAME_RUN.match(value, i + 1)):
            i = m.end()
            continue
        elif m := _NAME_RUN.match(value, i):
            i = m.end()
            if i < n and value[i] == "(" and _unescaped(m[0]).lower() == "url" and (u := _UNQUOTED_URL.match(value, i + 1)):
                i = u.end()
            continue
        elif c == "\\":
            i += 2
            continue
        elif c in _CLOSER:
            blocks.append(_CLOSER[c])
        elif blocks and c == blocks[-1]:
            blocks.pop()
        elif c == ";" and not blocks:
            parts.append(value[start:i])
            start = i + 1
        i += 1
    parts.append(value[start:])
    return parts


def _without_user_modify(value: str) -> str:
    """A style attribute without the declarations that make text editable (`-webkit-user-modify`, `-moz-user-modify`,
    `user-modify`): Chromium and WebKit let the reader type into such a span, and the page does not guard it. A declaration with
    a backslash is dropped too (an escape can spell the name; this also drops an ordinary `content:"\\201C"`), and the whole
    declaration is searched, not the text before its colon, so a comment before the name does not hide it, whatever the comment
    holds. Where this splits differently from a browser (see `_declarations`), the text is still searched whole: a piece that
    holds the name is dropped."""
    return ";".join(d for d in _declarations(value) if not _EDITABLE_OR_ESCAPE.search(d))


_COMMENT = re.compile(r"/\*.*?(?:\*/|$)", re.S)


def _has_declaration(value: str) -> bool:
    """Whether a style attribute holds anything but separators, comments and white space."""
    return any(_COMMENT.sub("", d).strip() for d in _declarations(value))


def _mount_style(value: str) -> str:
    """The declarations of a style attribute that the allow-list names, written out normalised; "" when none is left.
    Each declaration stands or falls alone, and the value grammar has no quote, backslash, slash, bang or function
    call but colours, so a comment, an escape or a url() cannot get through however the text is split."""
    kept = []
    for decl in value.split(";"):
        prop, sep, val = decl.partition(":")
        prop, val = prop.strip().lower(), " ".join(val.split()).lower()
        grammar = _MOUNT_STYLE.get(prop)
        if sep and grammar and grammar.match(val):
            kept.append(f"{prop}:{val}")
    return ";".join(kept)


def _mount_img_ok(value: str) -> bool:
    v = _STRIP_CONTROL.sub("", value)
    if "\\" in v or v.startswith("//"):
        return False
    return not _SCHEME.match(v) or bool(_SAFE_DATA.match(v))


def _mount_link_ok(value: str) -> bool:
    v = _STRIP_CONTROL.sub("", value)
    if "\\" in v:
        return False
    m = _SCHEME.match(v)
    return not m or m.group(1).lower() in _MOUNT_LINK_SCHEMES


def _mount_attrs(tag, name: str, log: list[str]) -> None:
    for attr in list(tag.attrs):
        a = attr.lower()
        value = tag[attr]
        value = " ".join(value) if isinstance(value, list) else str(value)
        drop = None
        if a in _MOUNT_DROPPED_ATTRS or a.startswith(("rd-", "data-rd")):
            drop = "reserved or not needed on a mounted page"
        elif a == "src" and name != "img":
            drop = "only an image loads"
        elif a in ("href", "xlink:href"):
            if name == "a" and a == "href":
                if not _mount_link_ok(value):
                    drop = "not an allowed address"
            elif not value.strip().startswith("#"):
                drop = "only a fragment may be referenced here"
        elif a == "id" and value.strip().lower().startswith("rd-"):
            drop = "the page's own name"
        elif a == "style":
            clean = _mount_style(value)
            if clean != value:
                if clean:
                    tag[attr] = clean
                else:
                    drop = "nothing the page allows"
                log.append(f"  - style trimmed on <{name}>")
        elif a == "class":
            kept = [c for c in value.split() if not c.lower().startswith("rd-")]
            if kept != value.split():
                if kept:
                    tag[attr] = " ".join(kept)
                else:
                    drop = "the page's own class"
        elif _EXTERNAL_URL.search(value):
            drop = "an address outside the page"
        if drop:
            log.append(f"  - {attr} removed from <{name}>: {drop}")
            del tag[attr]
    if name == "a" and "href" in tag.attrs:
        tag["rel"] = "noopener noreferrer"


def _block_attrs(tag, log: list[str]) -> None:
    """A declared Rich block (`div.<type>`, `blocks.declarations`) keeps its id, its type as the only class and exactly its
    declared `data-<attr>` with an allowed value. No style, free class, title or handler, whatever the mode."""
    bt = next((c for c in (tag.get("class") or []) if c in _BLOCKS), None)
    if tag.name != "div" or bt is None:
        return
    allowed = _BLOCKS[bt]["attrs"]
    for attr in list(tag.attrs):
        a = attr.lower()
        value = tag[attr]
        value = " ".join(value) if isinstance(value, list) else str(value)
        if a == "id" or (a in allowed and value in allowed[a]):
            continue
        if a != "class":
            log.append(f"  - {attr} removed from <div class={bt}>: not declared")
        del tag[attr]
    tag["class"] = [bt]


def _comment_ok(text: str) -> bool:
    """A comment that every parser reads as ending at the same place as this one."""
    return not (text.startswith((">", "->")) or "--!>" in text or "<!--" in text)


def _pass(fragment: str, comments: bool, log: list[str], mount: bool = False) -> str:
    soup = BeautifulSoup(_end_empty_comments(fragment), "html.parser", element_classes={Tag: _Tag})
    if mount:
        _flatten_deep(soup, log)

    for node in list(soup.find_all(string=True)):
        if not isinstance(node, PreformattedString):
            continue
        if type(node) is not Comment:
            log.append(f"  - {type(node).__name__} removed from the document")
            node.extract()
        elif not comments:
            node.extract()
        elif not _comment_ok(str(node)):
            log.append("  - a comment a browser would read differently was removed")
            node.extract()

    for tag in soup.find_all(True):
        if tag.decomposed:
            continue
        name = tag.name.lower()
        if name in REMOVE or name in ALSO_REMOVED:
            log.append(f"  - <{name}> removed from the document")
            tag.decompose()
            continue
        # the browser matches `type` exactly, ASCII case aside: no trimming, and no str.lower() on its own, which turns
        # U+212A (Kelvin sign) into an ASCII k
        kind = str(tag.get("type", ""))
        if name == "input" and not (kind.isascii() and kind.lower() == "checkbox"):
            log.append("  - <input> removed from the document")
            tag.decompose()
            continue
        if name in _ANIMATION and _ANIMATED_ATTR.match(str(tag.get("attributename", "")).strip()):
            log.append(f"  - <{name}> that sets a link removed from the document")
            tag.decompose()
            continue
        if mount:
            if name in MOUNT_REMOVED:
                log.append(f"  - <{name}> removed from the document")
                tag.decompose()
                continue
            if name == "source" or (name in ("picture", "a") and (name == "picture" or tag.find_parent("svg"))):
                tag.unwrap()
                continue
            if name == "img":
                src = tag.get("src")
                if not _mount_img_ok(" ".join(src) if isinstance(src, list) else str(src or "")):
                    log.append("  - <img> removed from the document: not an address the page loads")
                    alt = str(tag.get("alt") or "").strip()
                    tag.replace_with(alt) if alt else tag.decompose()
                    continue
        for attr in list(tag.attrs):
            a = attr.lower()
            if a.startswith("on") or a in DROPPED_ATTRS:
                log.append(f"  - {attr} removed from <{name}>")
                del tag[attr]
            elif a == "style" and not mount:
                value = str(tag[attr])
                clean = _without_user_modify(value)
                if clean != value:
                    log.append(f"  - style trimmed on <{name}>")
                    if _has_declaration(clean):
                        tag[attr] = clean
                    else:
                        del tag[attr]
            elif a in URL_ATTRS:
                value = tag[attr]
                if isinstance(value, list):
                    value = " ".join(value)
                if not _url_ok(tag, a, str(value)):
                    log.append(f"  - {attr} removed from <{name}>: not an allowed address")
                    del tag[attr]
        if mount:
            _mount_attrs(tag, name, log)
        _block_attrs(tag, log)
    return str(soup)


def sanitize(fragment: str, *, comments: bool = True, log: list[str] | None = None, mount: bool = False) -> str:
    """Pandoc's HTML with everything that can run, load or navigate removed.

    comments=False also drops every HTML comment: the share copy has none. mount=True is the stricter
    mode for a page mounted in the front's document (see the module text). Each
    removal is appended to `log` as a "  - ..." line when a list is given."""
    log = log if log is not None else []
    out = fragment
    for _ in range(MAX_PASSES):
        again = _pass(out, comments, log, mount)
        if again == out:
            break
        out = again
    return out
