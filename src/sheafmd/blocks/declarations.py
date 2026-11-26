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
from dataclasses import dataclass

# Plain Markdown blocks: what a quote, a list item or a Rich block's content may be made of.
PLAIN = ("paragraph", "heading", "list", "quote", "table", "code", "rule")
# The layout divs of ADR 0001 (amended), allowed inside a callout or a column.
LAYOUT = ("box", "image")


@dataclass(frozen=True)
class Attr:
    name: str
    values: tuple          # the allowed values, or the allowed steps, as stored
    default: str
    css: str = ""          # declarations for one value; `{v}` is the value. Empty: no rule is generated.


@dataclass(frozen=True)
class BlockType:
    name: str
    tag: str
    attrs: tuple = ()
    children: tuple = ()   # the child types the Container rule allows


CALLOUT = BlockType(
    "callout", "div",
    attrs=(
        Attr("tone", ("info", "success", "warning", "danger"), "info",
             "--callout-accent:var(--sheaf-callout-{v}-accent);--callout-bg:var(--sheaf-callout-{v}-bg)"),
        Attr("align", ("left", "center", "right"), "left", "text-align:{v}"),
        Attr("pad", ("none", "s", "m", "l"), "m", "padding:var(--sheaf-pad-{v})"),
    ),
    children=PLAIN + LAYOUT,
)

DECLARED = {t.name: t for t in (CALLOUT,)}

# The Theme properties: documented, stable through 1.x (ADR 0008). A Theme's `theme.css` may override any.
TONES = {"info": ("#1f5fd6", "#eef3fd", "#8ab4f8", "#17243a"),
         "success": ("#1e7e46", "#edf8f1", "#6fcf97", "#14291d"),
         "warning": ("#b07a00", "#fff8e6", "#e0a800", "#2e2712"),
         "danger": ("#b3261e", "#fdeeed", "#f2766e", "#33181a")}
PADS = {"none": "0", "s": ".5rem", "m": "1rem", "l": "1.5rem"}
RADIUS = ".4rem"


def check_attrs(type_: str, attrs: dict):
    """The reason `attrs` do not fit the declaration of `type_`, or None."""
    decl = DECLARED[type_]
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
    allowed = DECLARED[type_].children
    for k in kids:
        if k not in allowed:
            return f"a {k} may not sit inside a {type_}"
    return None


def check_plain_container(container: str, kids) -> str | None:
    """A quote or a list item holds plain blocks only: a Rich block inside is refused."""
    for k in kids:
        if k in DECLARED:
            return f"a {k} may not sit inside a {container}"
    return None


def allow_list() -> dict:
    """`{type: {"tag", "attrs": {"data-<name>": [values]}}}`: what a sanitiser lets through on `<tag class=type>`."""
    return {t.name: {"tag": t.tag, "attrs": {f"data-{a.name}": list(a.values) for a in t.attrs}}
            for t in DECLARED.values()}


def _properties() -> str:
    light, dark = [], []
    for tone, (accent, bg, daccent, dbg) in TONES.items():
        light += [f"--sheaf-callout-{tone}-accent:{accent}", f"--sheaf-callout-{tone}-bg:{bg}"]
        dark += [f"--sheaf-callout-{tone}-accent:{daccent}", f"--sheaf-callout-{tone}-bg:{dbg}"]
    pads = [f"--sheaf-pad-{k}:{v}" for k, v in PADS.items()]
    base = ";".join(light + pads + [f"--sheaf-callout-radius:{RADIUS}"])
    return (f":root{{{base}}}\n"
            f"@media(prefers-color-scheme:dark){{:root{{{';'.join(dark)}}}}}\n")


def css() -> str:
    """The base stylesheet's block rules: Theme property defaults, each type's structure, and one rule per
    allowed step of each attribute. Loaded before every Theme, so a Theme written before blocks lays them out."""
    out = [_properties()]
    out.append(
        "div.callout{margin:1.25rem 0;padding:var(--sheaf-pad-m);border-left:4px solid var(--callout-accent);"
        "border-radius:var(--sheaf-callout-radius);background:var(--callout-bg);"
        "--callout-accent:var(--sheaf-callout-info-accent);--callout-bg:var(--sheaf-callout-info-bg)}\n"
        "div.callout>:first-child{margin-top:0}\ndiv.callout>:last-child{margin-bottom:0}\n")
    for t in DECLARED.values():
        for a in t.attrs:
            if a.css:
                for v in a.values:
                    out.append(f'{t.tag}.{t.name}[data-{a.name}="{v}"]{{{a.css.format(v=v)}}}\n')
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
