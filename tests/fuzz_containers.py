"""A fuzzer for a table inside a quote or a list (ticket 87): what pandoc renders, against what `parse` and the
writes of `sheafmd.comments` say. Run as a script it compares two source trees:

    python tests/fuzz_containers.py SEED N [BASE_SRC]

and prints, per generator, how many cases `head` gets wrong against pandoc, and "head wrong where base right",
split in lost (pandoc shows the comment, the code does not find it) and phantom (the reverse). The counters that
must be 0 are the last two. tests/test_table_in_container.py runs a few seeds of it.

Pandoc is the oracle, the bundled one: a comment written in a cell is raw HTML when pandoc does not read it as
code; `parse` must find it exactly then. A write (`add_comment`, then `reply`) is right when the comment it wrote
is found by `parse` and shown raw by pandoc, the rest of the file as it was, or when it was refused.
"""
import importlib
import random
import re
import sys
from pathlib import Path

C = '<!-- sheaf-comment id=c1 by="A" at=2026-01-01T00:00 status=open quote="b" why -->'
TARGET = "TGTWORD"

QUOTES = ["> ", ">", ">\t", ">  ", "   > ", "> "]
MARKS = ["-", "*", "+", "1.", "10.", "1)", "3)", "123456789."]
SP = [" ", " ", "  ", "   ", "    ", "\t"]
EXTRA = ["", "", "", " ", "  ", "   ", "    ", "\t"]


def width(s, col=0):
    for ch in s:
        col += 4 - col % 4 if ch == "\t" else 1
    return col


def chain(rng, plain_bias):
    out = []
    if rng.random() < plain_bias:
        if rng.random() < .5:
            for _ in range(rng.randint(1, 4)):
                out.append(("> ", "> "))
        else:
            out.append((rng.choice(MARKS) + rng.choice([" ", " ", "  ", "   "]), None))
        return out
    for _ in range(rng.randint(1, 3)):
        if rng.random() < .45:
            q = rng.choice(QUOTES)
            out.append((q, q))
        else:
            out.append((rng.choice(MARKS) + rng.choice(SP), None))
    return out


def prefixes(rng, ch):
    """The first-line prefix, the continuation prefix and the prefixes of each outer container."""
    first = "".join(f for f, _ in ch)
    cont, col = "", 0
    for f, c in ch:
        if c is not None:
            cont += c
            col = width(c, col)
        else:
            w = width(f, col) - col
            if rng.random() < .2:
                w = min(w, len(f.rstrip()) + 1)
            cont += " " * w
            col += w
    outers = []
    for j in range(len(ch)):
        pre, col = "", 0
        for f, c in ch[:j]:
            if c is not None:
                pre += c
                col = width(c, col)
            else:
                w = width(f, col) - col
                pre += " " * w
                col += w
        outers.append(pre)
    return first, cont, outers


def make(rng, word, plain_bias=.5, crlf=.08):
    """A quote or a list with one or two tables in it, `word` in the cell of one of them: in the middle of a code
    span, after it, or beside it."""
    ch = chain(rng, plain_bias)
    first, cont, outers = prefixes(rng, ch)
    lines = []
    ctx = rng.choice(["none", "para", "para-blank", "heading", "heading-nb", "item-before"])
    if ctx == "para":
        lines += [first + "q"]
        hp = cont
    elif ctx == "para-blank":
        lines += [first + "q", rng.choice([cont.rstrip(), cont, ""])]
        hp = cont
    elif ctx == "heading":
        lines += [first + "# H", cont.rstrip()]
        hp = cont
    elif ctx == "heading-nb":
        lines += [first + "# H"]
        hp = cont
    elif ctx == "item-before":
        lines += [first + "q", cont.rstrip(), rng.choice(outers) + rng.choice(MARKS) + " r"]
        hp = cont
    else:
        hp = first
    hx = rng.choice(EXTRA)
    ntab = 1 if rng.random() < .7 else 2
    k_tab = rng.randrange(ntab)
    body = []
    for t in range(ntab):
        ncol = rng.choice([2, 2, 3, 4])
        head = "|" + "|".join(" h%d " % j for j in range(ncol)) + "|"
        sep = "|" + "|".join(rng.choice(["---", ":--", "--:", ":-:"]) for _ in range(ncol)) + "|"
        if rng.random() < .1:
            sep = "|" + "|".join("---" for _ in range(ncol + rng.choice([-1, 1]))) + "|"
        cells = [head, sep] + ["|" + "|".join(rng.choice([" x ", " `y` ", " `z | ", " w` ", " v\\| "])
                                              for _ in range(ncol)) + "|" for _ in range(rng.randint(1, 3))]
        k = rng.randrange(len(cells)) if t == k_tab else None
        if k == 1:
            k = 0
        for i, c in enumerate(cells):
            if i == k:
                c = rng.choice(["| `x | `" + word + "` | y` |", "| x" + word + " | y |", "| `x` | y " + word + " |",
                                "| `x | y" + word + " |"])
            if i == 0:
                pre = (hp if t == 0 else cont) + hx
            else:
                pre = rng.choice([cont] * 4 + outers + [cont + e for e in EXTRA] + [first, cont.rstrip(" ") + "  "])
            if i >= 2 and rng.random() < .07:
                body.append(rng.choice([cont.rstrip(), "", cont]))
            body.append(pre + c)
        if t + 1 < ntab:
            body.append(rng.choice([cont.rstrip(), "", cont + "between", cont + "# H2"]))
    r = rng.random()
    if r < .1:
        body.append(rng.choice(outers + [cont]) + "para after")
    elif r < .2:
        body.append(rng.choice(outers) + rng.choice(MARKS) + " next")
    elif r < .25:
        body += ["", "after"]
    elif r < .3:
        body.append(rng.choice(outers + [""]) + "- next")
    md = "\n".join(lines + body) + "\n"
    if rng.random() < crlf:
        md = md.replace("\n", "\r\n")
    return md


# The generators: (name, plain bias). The first two are the shapes a person writes; the third mixes in every
# marker, tab and nesting that the parts of `make` can produce.
GENERATORS = {"plain": .85, "mixed": .5, "nested": .0}


def load(src):
    """`sheafmd.comments` of the source tree `src`, a fresh import."""
    for k in list(sys.modules):
        if k == "sheafmd" or k.startswith("sheafmd."):
            del sys.modules[k]
    sys.path.insert(0, src)
    try:
        return importlib.import_module("sheafmd.comments")
    finally:
        sys.path.remove(src)


def pandoc_html(pandoc, md):
    return pandoc(["-f", "gfm", "-t", "html"], md)


def pandoc_sees(pandoc, md, word=C):
    """Whether pandoc shows `word` as raw HTML, not as code or as escaped text."""
    html = pandoc_html(pandoc, md)
    return "&lt;!-- sheaf" not in html and "<!-- sheaf-comment" in html


def parse_sees(m, md):
    try:
        return [c.id for c in m.parse(md).comments] == ["c1"]
    except Exception as e:      # noqa: BLE001  a crash is a wrong answer, not the end of the run
        return "EXC:" + repr(e)


def write_outcome(m, pandoc, md):
    """What `add_comment` and `reply` do with `md`, the comment word being `TGTWORD`: "refused", "ok", or what
    was wrong ("lost": written but `parse` does not find it, "phantom": found where pandoc shows it as code or
    as text, "changed": the file changed beyond the comment)."""
    stage = "find"
    try:
        found = m.find_quote(md, TARGET)
        out, cid = m.add_comment(md, found[0], found[1], found[2], TARGET, "why\nmore", "A", "2026-01-01T00:00")
        stage = "add"
        sees = [c.id for c in m.parse(out).comments] == [cid]
        shown = pandoc_sees(pandoc, out.replace(cid, "c1"))
        if sees != shown:
            return "lost" if shown else "phantom"
        if not sees:
            return "lost"
        if re.sub(r"<!--.*?-->", "", out, count=1, flags=re.S) != md:
            return "changed"
        again = m.reply(out, cid, "an answer\nin two lines", "B", "2026-01-01T01:00")
        stage = "reply"
        if [c.id for c in m.parse(again).comments] != [cid] or not pandoc_sees(pandoc, again.replace(cid, "c1")):
            return "lost"
        return "ok"
    except m.AnchorError:
        return "refused"
    except Exception as e:      # noqa: BLE001
        return f"EXC:{stage} " + repr(e)[:60]


def run(seed, n, head, base, pandoc, gens=None):
    """Counters per generator: {"parse": {...}, "write": {...}}, each with `wrong` (per tree, against the
    oracle), `lost` and `phantom` (head wrong where base is right) and `shown` (the first such inputs)."""
    result = {}
    for name, bias in GENERATORS.items():
        if gens and name not in gens:
            continue
        rng = random.Random(f"{seed}/{name}")
        parse = {"cases": 0, "wrong_head": 0, "wrong_base": 0, "lost": 0, "phantom": 0, "shown": []}
        write = {"cases": 0, "wrong_head": 0, "wrong_base": 0, "lost": 0, "phantom": 0, "shown": []}
        for _ in range(n):
            md = make(rng, C, bias)
            truth = pandoc_sees(pandoc, md)
            h, b = parse_sees(head, md), parse_sees(base, md) if base else truth
            parse["cases"] += 1
            parse["wrong_head"] += h != truth
            parse["wrong_base"] += b != truth
            if h != truth and b == truth:
                parse["lost" if truth else "phantom"] += 1
                parse["shown"].append(md)
            wmd = md.replace(C, TARGET)
            if TARGET not in pandoc_html(pandoc, wmd).replace("&lt;", "<"):
                continue
            ho = write_outcome(head, pandoc, wmd)
            bo = write_outcome(base, pandoc, wmd) if base else "ok"
            write["cases"] += 1
            write["wrong_head"] += ho not in ("ok", "refused")
            write["wrong_base"] += bo not in ("ok", "refused")
            if ho not in ("ok", "refused") and bo in ("ok", "refused"):
                write["lost" if ho != "phantom" else "phantom"] += 1
                write["shown"].append((wmd, ho))
        result[name] = {"parse": parse, "write": write}
    return result


def main(argv):
    from helpers import pandoc
    seed, n = argv[0], int(argv[1])
    base_src = argv[2] if len(argv) > 2 else None
    own_src = str(Path(__file__).resolve().parents[1] / "src")
    base = load(base_src) if base_src else None
    head = load(own_src)
    res = run(seed, n, head, base, pandoc)
    for name, r in res.items():
        for what in ("parse", "write"):
            c = r[what]
            print(f"seed {seed} {name:6} {what:5} n={c['cases']} wrong: head {c['wrong_head']} base {c['wrong_base']}"
                  f" | head wrong where base right: lost {c['lost']} phantom {c['phantom']}")
            for s in c["shown"][:3]:
                print("   ", repr(s))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main(sys.argv[1:])
