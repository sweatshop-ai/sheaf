"""
sheafmd.sanitize — the raw-HTML sanitiser (SPEC 9.5).

A markdown file can carry raw HTML, and pandoc passes it straight through. A
document that arrives from someone else, or from an agent that read a web page, can
therefore carry a script into the page the hub serves and into a share copy that goes
to a client. This module takes pandoc's output and removes what can run or phone home:

    elements removed with their content   script style iframe frame frameset object
                                          embed applet base meta link form button
                                          textarea select template noscript
    input                                 removed unless type="checkbox" (task lists)
    attributes removed                    every on*, srcdoc, formaction, srcset, ping
                                          (srcset and ping hold URLs outside the list below)
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

The hub also sends a Content-Security-Policy with a nonce (SPEC 9.5), which is the
defence that holds when this one is wrong. A share copy has no such header, so this
module is the only defence there, and the share copy has no comments at all.
"""
import re

from bs4 import BeautifulSoup, Comment
from bs4.element import PreformattedString, Tag

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
DROPPED_ATTRS = frozenset({"srcdoc", "formaction", "srcset", "ping"})
SAFE_SCHEMES = frozenset({"http", "https", "mailto", "file"})
_SAFE_DATA = re.compile(r"^data:image/(?:png|jpeg|gif|webp)[;,]", re.I)
_SCHEME = re.compile(r"^([^/?#]*):")
_STRIP_CONTROL = re.compile(r"[\x00-\x20\x7f]+")
MAX_PASSES = 3
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


def _comment_ok(text: str) -> bool:
    """A comment that every parser reads as ending at the same place as this one."""
    return not (text.startswith((">", "->")) or "--!>" in text or "<!--" in text)


def _pass(fragment: str, comments: bool, log: list[str]) -> str:
    soup = BeautifulSoup(_end_empty_comments(fragment), "html.parser", element_classes={Tag: _Tag})

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
        if name == "input" and str(tag.get("type", "")).strip().lower() != "checkbox":
            log.append("  - <input> removed from the document")
            tag.decompose()
            continue
        if name in _ANIMATION and _ANIMATED_ATTR.match(str(tag.get("attributename", "")).strip()):
            log.append(f"  - <{name}> that sets a link removed from the document")
            tag.decompose()
            continue
        for attr in list(tag.attrs):
            a = attr.lower()
            if a.startswith("on") or a in DROPPED_ATTRS:
                log.append(f"  - {attr} removed from <{name}>")
                del tag[attr]
            elif a in URL_ATTRS:
                value = tag[attr]
                if isinstance(value, list):
                    value = " ".join(value)
                if not _url_ok(tag, a, str(value)):
                    log.append(f"  - {attr} removed from <{name}>: not an allowed address")
                    del tag[attr]
    return str(soup)


def sanitize(fragment: str, *, comments: bool = True, log: list[str] | None = None) -> str:
    """Pandoc's HTML with everything that can run, load or navigate removed.

    comments=False also drops every HTML comment: the share copy has none. Each
    removal is appended to `log` as a "  - ..." line when a list is given."""
    log = log if log is not None else []
    out = fragment
    for _ in range(MAX_PASSES):
        again = _pass(out, comments, log)
        if again == out:
            break
        out = again
    return out
