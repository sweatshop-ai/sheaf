"""sheafmd.links — every page, article, tool or document a text names is a link.

A reader who meets "the employee-buyout page" has to go and find it. A reader who meets
a link clicks. So the rule is the same for whoever writes: the author of a document, the
session that answers a Tell, the fork that answers an Ask.

Two halves, both here so they cannot drift apart:

  RULE                 the sentence the page hands an agent (Tell, Ask).
  unlinked_mentions()  the check at render time: host names and site paths that stand in
                       prose without a link. A warning, never a block. It cannot see a page
                       named in words alone ("the pricing page"); that is what RULE is for.
"""

import functools
import html
import re

RULE = (
    "Every page, article, tool or document you name, in text you write into the document "
    "or in a reply, is a markdown link [words](https://full-url) to its URL, checked with "
    "curl that it answers. Link only what the text names, and never a generic page (a home "
    "page, a search page) where a specific one is meant."
)

# Only the endings common in ordinary web writing. A general "word.word"
# pattern reads notes.txt, config.json and Node.js as sites, and a warning that
# cries wolf is read once and then never again. A caller can add endings for its own
# sites with unlinked_mentions(extra_tlds=...); the list below is what it starts from.
TLDS = ("com|org|net|edu|gov|io|ai|co|dev|app|me|eu|be|nl|fr|de|it|es|pt|ch|at|lu|uk|us|ca|"
        "se|dk|fi|info|biz|tv|shop|store|online|site|agency|tech|cloud|blog|xyz")
_LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_DEFAULT_TLDS = frozenset(TLDS.split("|"))
_EXTRA_TLD = re.compile(r"[a-z0-9]+")


@functools.lru_cache(maxsize=None)
def _host_regex(extra):
    """The host regex for the default endings plus `extra`, a tuple of endings already
    cleaned by _clean_extra(). One compiled regex per distinct set."""
    tlds = TLDS + "".join("|" + re.escape(e) for e in extra)
    return re.compile(
        rf"(?<![\w@./-])(?:https?://)?(?:{_LABEL}\.)+(?P<tld>{tlds})(?![\w-])(?:[/?#][^\s<>\"']*)?",
        re.I)


def _clean_extra(extra_tlds):
    """The extra endings as a sorted tuple, one each: lowercased, without a leading dot,
    and only those made of letters and digits. Anything else is dropped without a word
    (the config layer is where a bad ending is reported), so no input can make the regex
    invalid. An ending already in the default list adds nothing and is dropped too, which
    keeps one cache entry per distinct set. A bare string is one ending, not a list of
    letters."""
    if extra_tlds is None:
        return ()
    if isinstance(extra_tlds, str):
        extra_tlds = (extra_tlds,)
    kept = set()
    for e in extra_tlds:
        if not isinstance(e, str):
            continue
        e = e.lower().removeprefix(".")
        if _EXTRA_TLD.fullmatch(e) and e not in _DEFAULT_TLDS:
            kept.add(e)
    return tuple(sorted(kept))


HOST = _host_regex(())
TRAILING = ".,;:!?)]}"
_SKIP = re.compile(r"<!--[\s\S]*?-->|<(script|style|pre|a)\b[\s\S]*?</\1>", re.I)
_CODE = re.compile(r"<code\b[^>]*>([\s\S]*?)</code>", re.I)
_TAG = re.compile(r"<[^>]+>")


def _mention(m):
    """The matched text without the punctuation that ends a sentence, or None when the
    ending is not lowercase: `Done.It` is a missing space, not a site."""
    if not m.group("tld").islower():
        return None
    return m.group(0).rstrip(TRAILING)


def _lone_host(code, host):
    """Inline code that is nothing but one host or site path is a reference. Code with
    anything else in it is a sample (`curl www.example.com`) and is left alone. `host` is
    the regex of the call that is reading the text."""
    inner = html.unescape(_TAG.sub("", code)).strip()
    m = host.fullmatch(inner)
    return f" {inner} " if m and _mention(m) else " "


def unlinked_mentions(fragment, extra_tlds=()):
    """[(mention, context)] for each host name or site path in the prose of an HTML
    fragment that is not inside a link. Once per mention, context from its first place.

    Not prose, so not read: links, fenced code, comments, and every tag attribute.

    `extra_tlds` is an iterable of endings added to the default list (TLDS), for sites
    the default list does not know: ["studio", ".lu"]."""
    host = _host_regex(_clean_extra(extra_tlds))
    text = _SKIP.sub(" ", fragment)
    text = _CODE.sub(lambda m: _lone_host(m.group(1), host), text)
    text = html.unescape(_TAG.sub(" ", text))
    text = re.sub(r"\s+", " ", text)
    found, seen = [], set()
    for m in host.finditer(text):
        mention = _mention(m)
        if not mention or mention in seen:
            continue
        seen.add(mention)
        found.append((mention, text[max(0, m.start() - 40):m.start() + len(mention) + 40].strip()))
    return found


def warning(found, limit=12):
    """The stderr text for a non-empty result of unlinked_mentions()."""
    lines = [f"  ! {len(found)} host name(s) or site path(s) named in the text without a link:"]
    for mention, context in found[:limit]:
        lines.append(f"      {mention}    in: …{context}…")
    if len(found) > limit:
        lines.append(f"      … and {len(found) - limit} more")
    lines.append("    Make each one a markdown link, [words](https://full-url), checked with "
                 "curl that it answers.")
    return "\n".join(lines)
