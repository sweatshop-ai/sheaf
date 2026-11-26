"""The fixed list of typed Block declarations (block editor v1, ADR 0001, 0004 and 0008).

One list, in core, that members cannot extend. For each Rich block type it holds the element it is written as,
its attributes (each with the values or steps it allows and a default) and the Container rule: which child
types it may hold. It feeds everything that has to agree on what a Rich block may carry:

    check_attrs / check_children   the reader (`tree.read_tree`) and the save checks (`document`)
    allow_list()                   both sanitiser layers: `sanitize.py` and the generated block of `page/mount.js`
    css()                          the base stylesheet: structure, Theme property defaults, one rule per step

A new Block type is one entry here; nothing else is written by hand.
"""
import json
import re
from dataclasses import dataclass

# Plain Markdown blocks: what a quote, a list item or a Rich block's content may be made of.
PLAIN = ("paragraph", "heading", "list", "quote", "table", "code", "rule")
# The layout divs of ADR 0001 (amended), allowed inside a callout or a column.
LAYOUT = ("box", "image")


_BARE = frozenset({"size"})


@dataclass(frozen=True)
class Attr:
    name: str
    values: tuple          # the allowed values, or the allowed steps, as stored
    default: str
    css: object = ""       # declarations for one value, `{v}` being the value; or a dict value -> declarations. Empty: no rule.

    @property
    def wire(self) -> str:
        """The attribute as pandoc writes it into the HTML: `size` stays `size`, the others become `data-<name>`."""
        return self.name if self.name == "size" else f"data-{self.name}"

    @property
    def wire(self) -> str:
        """The attribute as pandoc writes it into HTML: `size` stays `size` (it is an HTML attribute), every other
        one becomes `data-<name>`. The checks on write use `name`, the sanitisers and the CSS use `wire`."""
        return self.name if self.name in _BARE else f"data-{self.name}"


@dataclass(frozen=True)
class BlockType:
    name: str
    tag: str
    attrs: tuple = ()
    children: tuple = ()   # the child types the Container rule allows
    top: bool = True       # False: only ever a child of another type (a column of columns), never a block of its own
    base: str = ""         # the type's structure in the base stylesheet, written once


CALLOUT = BlockType(
    "callout", "div",
    attrs=(
        Attr("tone", ("info", "success", "warning", "danger"), "info",
             "--callout-accent:var(--sheaf-callout-{v}-accent);--callout-bg:var(--sheaf-callout-{v}-bg)"),
        Attr("align", ("left", "center", "right"), "left", "text-align:{v}"),
        Attr("pad", ("none", "s", "m", "l"), "m", "padding:var(--sheaf-pad-{v})"),
    ),
    children=PLAIN + LAYOUT,
    base=("div.callout{margin:1.25rem 0;padding:var(--sheaf-pad-m);border-left:4px solid var(--callout-accent);"
          "border-radius:var(--sheaf-callout-radius);background:var(--callout-bg);"
          "--callout-accent:var(--sheaf-callout-info-accent);--callout-bg:var(--sheaf-callout-info-bg)}\n"
          "div.callout>:first-child{margin-top:0}\ndiv.callout>:last-child{margin-bottom:0}\n"),
)

ALIGN = ("left", "center", "right")
PAD = ("none", "s", "m", "l")
# A column's share of the row, in %: 5 % steps from 15 to 85 (ADR 0008), plus the thirds 33 and 67 that the 33/67 and
# 67/33 presets and the spec's wire sample write. A drag never lands on them; a preset does.
SPLIT = tuple(str(n) for n in sorted({*range(15, 86, 5), 33, 67}))
IMAGE_SIZE = ("25", "50", "75", "100")                   # an image's share of its column, in %

# Columns: a row of columns that sit side by side at their split. Below 600 px on a screen they stack in source order
# and their split is ignored; in print and the PDF they stay side by side.
COLUMNS = BlockType(
    "columns", "div", children=("column",),
    base=("div.columns{display:flex;gap:1rem;margin:1.25rem 0}\n"
          "@media screen and (max-width:599px){div.columns{flex-direction:column}"
          "div.columns>div.column{flex:0 0 auto;width:auto}}\n"),
)
COLUMN = BlockType(
    "column", "div",
    attrs=(Attr("size", SPLIT, "", "flex:0 1 {v}%"),),
    children=PLAIN + LAYOUT, top=False,
    base="div.column{flex:1 1 0;min-width:0}\ndiv.column>:first-child{margin-top:0}\ndiv.column>:last-child{margin-bottom:0}\n",
)
# A box: a plain block (or several) that carries only layout.
BOX = BlockType(
    "box", "div",
    attrs=(Attr("align", ALIGN, "left", "text-align:{v}"),
           Attr("pad", PAD, "none", "padding:var(--sheaf-pad-{v})")),
    children=PLAIN,
)
# An image on a line of its own, resized to a share of its container and aligned in it.
IMAGE = BlockType(
    "image", "div",
    attrs=(Attr("size", IMAGE_SIZE, "100", "width:{v}%"),
           Attr("align", ALIGN, "left", {"left": "margin-right:auto", "center": "margin-left:auto;margin-right:auto",
                                          "right": "margin-left:auto"})),
    children=("paragraph",),
    base="div.image{max-width:100%}\ndiv.image img{width:100%;height:auto;display:block}\ndiv.image p{margin:0}\n",
)


# Inline content: a bracketed span around one link, so it sits in a paragraph, a table cell, a column or a callout.
# It is never a block of the tree, so it is not in DECLARED (the reader reads a div's class against that), and it
# holds no child types: its content is one link, checked by `button_fault`.
BUTTON = BlockType(
    "button", "span",
    attrs=(
        Attr("size", ("s", "m", "l"), "m",
             "--button-pad:var(--sheaf-button-pad-{v});--button-font:var(--sheaf-button-font-{v})"),
        Attr("variant", ("primary", "secondary", "outline"), "primary",
             "--button-bg:var(--sheaf-button-{v}-bg);--button-fg:var(--sheaf-button-{v}-fg);"
             "--button-border:var(--sheaf-button-{v}-border)"),
    ),
)

DECLARED = {t.name: t for t in (CALLOUT, COLUMNS, COLUMN, BOX, IMAGE)}
INLINE = {t.name: t for t in (BUTTON,)}
_ALL = {**DECLARED, **INLINE}

# The Theme properties: documented, stable through 1.x (ADR 0008). A Theme's `theme.css` may override any.
TONES = {"info": ("#1f5fd6", "#eef3fd"),
         "success": ("#1e7e46", "#edf8f1"),
         "warning": ("#b07a00", "#fff8e6"),
         "danger": ("#b3261e", "#fdeeed")}       # (accent, background), light: a Theme with a dark page overrides them
PADS = {"none": "0", "s": ".5rem", "m": "1rem", "l": "1.5rem"}
RADIUS = ".4rem"
# The button's Theme properties: per variant (background, text, border), per size (padding, font size) and one radius.
BUTTONS = {"primary": ("#1f5fd6", "#ffffff", "#1f5fd6"),
           "secondary": ("#e8eaee", "#1c2430", "#e8eaee"),
           "outline": ("transparent", "#1f5fd6", "#1f5fd6")}
BUTTON_SIZES = {"s": (".3rem .7rem", ".85rem"), "m": (".5rem 1.1rem", "1rem"), "l": (".7rem 1.5rem", "1.15rem")}
BUTTON_RADIUS = ".4rem"

LINK_SCHEMES = frozenset({"http", "https", "mailto"})
_CONTROL = re.compile(r"[\x00-\x20\x7f]+")
_SCHEME = re.compile(r"^([^/?#]*):")


def link_ok(url: str) -> bool:
    """The link rule of a button: http, https, mailto or a relative address. Read the way a browser reads it: control
    characters and spaces are dropped (a newline inside `java` and `script:` still reads `javascript:`), any other scheme (javascript, data, file,
    vbscript, blob, tel...) is refused, and so is a backslash, which some browsers read as a slash."""
    v = _CONTROL.sub("", url)
    if "\\" in v:
        return False
    m = _SCHEME.match(v)
    return not m or m.group(1).lower() in LINK_SCHEMES


def button_fault(ast: str) -> str | None:
    """The reason a block holds a button that is not valid, or None. `ast` is a block's canonical AST (JSON): a button
    is a Span of the class `button`; it must carry exactly the declared attributes with allowed values, no id and no
    other class, and hold one link, with no attributes of its own and an address `link_ok` accepts, around plain text."""
    try:
        doc = json.loads(ast)
    except ValueError:
        return None
    stack = [doc]
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, dict):
            if x.get("t") == "Span" and "button" in x["c"][0][1]:
                why = _button_why(x["c"])
                if why:
                    return why
            stack.append(x.get("c"))
    return None


def _button_why(c) -> str | None:
    (ident, classes, kvs), inlines = c
    if ident:
        return "a button has no id"
    if classes != ["button"]:
        return "a button has no class but button"
    why = check_attrs("button", {k: v for k, v in kvs})
    if why:
        return why
    if len(kvs) != len({k for k, _ in kvs}):
        return "a button has an attribute twice"
    if len(inlines) != 1 or inlines[0]["t"] != "Link":
        return "a button holds one link and nothing else"
    (lid, lclasses, lkvs), label, (url, _title) = inlines[0]["c"]
    if lid or lclasses or lkvs:
        return "a button link has no attributes of its own, no target"
    if not link_ok(url):
        return f"a button link {url!r} is not http, https, mailto or a relative address"
    if _inline_types(label) & {"Link", "Image", "Span", "RawInline", "Note", "Cite", "Math"}:
        return "a button label is plain text"
    return None


def _inline_types(x) -> set:
    out = set()
    stack = [x]
    while stack:
        y = stack.pop()
        if isinstance(y, list):
            stack.extend(y)
        elif isinstance(y, dict) and "t" in y:
            out.add(y["t"])
            stack.append(y.get("c"))
    return out


def check_attrs(type_: str, attrs: dict):
    """The reason `attrs` do not fit the declaration of `type_`, or None."""
    decl = _ALL[type_]
    declared = {a.name: a for a in decl.attrs}
    for name, value in attrs.items():
        a = declared.get(name)
        if a is None:
            return f"{type_} has no attribute {name!r}"
        if value not in a.values:
            return f"{type_} {name} {value!r} is not one of {', '.join(a.values)}"
    return None


def check_children(type_: str, kids) -> str | None:
    """The reason the child types `kids` may not sit in a `type_`, or None."""
    allowed = _ALL[type_].children
    for k in kids:
        if k not in allowed:
            return f"a {k} may not sit inside a {type_}"
    return None


def top_fault(type_: str) -> str | None:
    """The reason a block of `type_` may not stand on its own at the top of a document, or None."""
    if not DECLARED[type_].top:
        holders = [t.name for t in DECLARED.values() if type_ in t.children]
        return f"a {type_} may not stand alone: it belongs inside a {' or a '.join(holders)}"
    return None




def check_plain_container(container: str, kids) -> str | None:
    """A quote or a list item holds plain blocks only: a Rich block inside is refused."""
    for k in kids:
        if k in DECLARED:
            return f"a {k} may not sit inside a {container}"
    return None


def allow_list() -> dict:
    """`{type: {"tag", "attrs": {"data-<name>": [values]}}}`: what a sanitiser lets through on `<tag class=type>`."""
    return {t.name: {"tag": t.tag, "attrs": {a.wire: list(a.values) for a in t.attrs}} for t in _ALL.values()}


def _properties() -> str:
    tones = []
    for tone, (accent, bg) in TONES.items():
        tones += [f"--sheaf-callout-{tone}-accent:{accent}", f"--sheaf-callout-{tone}-bg:{bg}"]
    pads = [f"--sheaf-pad-{k}:{v}" for k, v in PADS.items()]
    buttons = []
    for v, (bg, fg, border) in BUTTONS.items():
        buttons += [f"--sheaf-button-{v}-bg:{bg}", f"--sheaf-button-{v}-fg:{fg}", f"--sheaf-button-{v}-border:{border}"]
    for v, (pad, font) in BUTTON_SIZES.items():
        buttons += [f"--sheaf-button-pad-{v}:{pad}", f"--sheaf-button-font-{v}:{font}"]
    buttons.append(f"--sheaf-button-radius:{BUTTON_RADIUS}")
    return f":root{{{';'.join(tones + pads + [f'--sheaf-callout-radius:{RADIUS}'] + buttons)}}}\n"


def css() -> str:
    """The base stylesheet's block rules: Theme property defaults, each type's structure, and one rule per
    allowed step of each attribute. Loaded before every Theme, so a Theme written before blocks lays them out."""
    out = [_properties()]
    for t in DECLARED.values():
        out.append(t.base)
    out.append(
        "span.button{display:inline-block;--button-pad:var(--sheaf-button-pad-m);--button-font:var(--sheaf-button-font-m);"
        "--button-bg:var(--sheaf-button-primary-bg);--button-fg:var(--sheaf-button-primary-fg);"
        "--button-border:var(--sheaf-button-primary-border);line-height:1.2}\n"
        "span.button>a{display:inline-block;padding:var(--button-pad);font-size:var(--button-font);font-weight:600;"
        "color:var(--button-fg);background:var(--button-bg);border:1px solid var(--button-border);"
        "border-radius:var(--sheaf-button-radius);text-decoration:none}\n"
        "span.button>a:hover{filter:brightness(.94)}\n")
    for t in _ALL.values():
        for a in t.attrs:
            for v in a.values:
                rule = a.css.get(v) if isinstance(a.css, dict) else a.css.format(v=v)
                if rule:
                    out.append(f'{t.tag}.{t.name}[{a.wire}="{v}"]{{{rule}}}\n')
    return "".join(out)


def mount_js() -> str:
    """The block of `page/mount.js` between its markers, generated from the allow list."""
    return ("/* BLOCKS:begin (generated from sheafmd.blocks.declarations: python -m sheafmd.blocks.declarations --write) */\n"
            f"  const BLOCK_TYPES = {json.dumps(allow_list(), sort_keys=True)};\n"
            "  /* BLOCKS:end */")


if __name__ == "__main__":      # python -m sheafmd.blocks.declarations --write: put the list into page/mount.js
    import re
    import sys
    from pathlib import Path
    target = Path(__file__).resolve().parent.parent / "page" / "mount.js"
    text = target.read_text(encoding="utf-8")
    new = re.sub(r"/\* BLOCKS:begin.*?/\* BLOCKS:end \*/", lambda m: mount_js(), text, flags=re.S)
    if "--write" in sys.argv:
        target.write_text(new, encoding="utf-8")
    else:
        sys.exit(0 if new == text else "page/mount.js is not what the declarations generate")
