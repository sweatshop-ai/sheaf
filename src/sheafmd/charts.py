"""
sheafmd.charts — the page's own diagrams: chart fences and mermaid fences to inline SVG.

Why this exists
---------------
A sheaf page is one self-contained file: no script from a CDN, no image fetched at
view time. So a ```chart fence (a small JSON spec: bar, hbar or line, with bands and
error bars) is drawn here as plain SVG with no library, and a ```mermaid fence goes
through the mermaid CLI (mmdc) once, is cached by its source, and is inlined.

Both work on the HTML pandoc produced and replace only the matching <pre> blocks, so
a <pre> that is not a chart or a diagram is never touched. The mermaid cache folder is
read from paths.cache_dir() at call time, so SHEAF_HOME set after import is honoured.
"""

import hashlib
import html
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import paths

# A chart fence is a document's own data, and the SVG drawn from it is added after the
# sanitiser ran (SPEC 6.2) and goes unchecked into a share copy, which has no CSP. So a
# colour or an opacity the spec supplies is written out only when it is one: the shapes
# a stylesheet writes, and nothing a quote, a bracket or a url() can ride on.
COLOUR_RE = re.compile(
    r"#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})"
    r"|[A-Za-z]{1,30}"
    r"|var\(--[A-Za-z0-9_-]{1,40}\)"
    r"|(?:rgb|rgba|hsl|hsla)\([0-9 ,.%/]{1,40}\)")
PALETTE = ["var(--ink)", "#dc2626", "#7a869a", "#2e7d32", "#8e5cd9"]
BAND_GREY = "#7a869a"
BAND_OPACITY = 0.11


def safe_colour(c, default):
    """`c` when it is a plain CSS colour, else `default`."""
    return c if isinstance(c, str) and COLOUR_RE.fullmatch(c) else default


def safe_opacity(v, default=BAND_OPACITY):
    """`v` when it is a finite number (a numeric string counts), else `default`."""
    if isinstance(v, bool):
        return default
    if isinstance(v, str):
        try:
            v = float(v)
        except ValueError:
            return default
    if isinstance(v, (int, float)) and math.isfinite(v):
        return v
    return default


def nice_ticks(hi, count=4):
    """Round axis top up to a 1/2/2.5/5 x 10^k step so ticks read as human numbers."""
    import math
    if hi <= 0:
        return 1.0, [0, 1]
    raw = hi / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw - 1e-12)
    top = step * math.ceil(hi / step - 1e-12)
    n = int(round(top / step))
    return top, [step * i for i in range(n + 1)]


def svg_chart(spec):
    """Minimal honest chart. type: bar | hbar | line. Inline SVG, no libraries."""
    t = spec.get("type", "bar")
    xs = spec.get("x", [])
    series = spec.get("series", [])
    if not xs or not series:
        return None
    horiz = t == "hbar"
    # dual: a line series with "axis": "right" gets its own scale on the right edge,
    # for two measures of different size (clicks vs impressions) on one time axis.
    dual = t == "line" and any(s_.get("axis") == "right" for s_ in series)
    W = 720
    if horiz:
        H = spec.get("height") or max(140, 30 * len(xs) + 60)
        L = min(230, 9 + int(6.6 * max(len(str(x)) for x in xs)))
        R, B = 22, 34
    else:
        H = spec.get("height", 300)
        L, R = 56, (56 if dual else 18)
        # x labels: wrap onto extra lines when a category slot is too narrow for the
        # label, and fall back to rotating when even a single word will not fit.
        # Without this, long category names silently overprint each other.
        CHW = 6.6  # DM Mono advance width at font-size 11 (600/1000 em)
        _avail = max(18.0, (W - L - R) / max(1, len(xs)) - 12)
        _maxch = max(4, int(_avail / CHW))
        xlab_lines = []
        for _lab in xs:
            _cur, _lines = "", []
            for _w in str(_lab).split():
                _t = (_cur + " " + _w).strip()
                if len(_t) <= _maxch or not _cur:
                    _cur = _t
                else:
                    _lines.append(_cur); _cur = _w
            if _cur:
                _lines.append(_cur)
            xlab_lines.append(_lines or [""])
        _deep = max(len(l) for l in xlab_lines)
        _wide = max((len(t) for l in xlab_lines for t in l), default=0)
        xlab_rot = _deep > 3 or _wide * CHW > _avail
        if xlab_rot:
            # Rotated -32 degrees, anchored at the tick, so each label runs down and to
            # the left. Truncate first, then buy the room it needs on both axes, or the
            # longest label runs off the left edge and through the bottom of the canvas.
            xlab_lines = [[(str(x)[:29] + "\u2026") if len(str(x)) > 30 else str(x)] for x in xs]
            _px = max(len(t[0]) for t in xlab_lines) * CHW
            L = max(L, int(_px * 0.848 - (W - L - R) / max(1, len(xs)) / 2) + 10)
            B = 20 + int(_px * 0.53)
            H = max(H, B + 160)
        else:
            B = 46 + (_deep - 1) * 12
    # The legend is drawn at the very bottom of the canvas. Without a band of its
    # own it overprints the x labels, which is what happens as soon as those rotate.
    # Four long series names overflow the canvas on one row, so it wraps, and the
    # band it reserves has to match the number of rows it will actually use.
    _legw = [26 + 6.4 * len(s.get("name", "")) for s in series]
    _legrows, _x = 1, 0.0
    if len(series) > 1 and not horiz:   # hbar labels its own marks and draws no legend
        for _w in _legw:
            if _x + _w > (W - L - R) and _x > 0:
                _legrows += 1
                _x = _w
            else:
                _x += _w
        B += 20 * _legrows
        H += 20 * _legrows
    T = (26 if spec.get("title") else 8) + (14 if spec.get("y_label") else 4)
    pw, ph = W - L - R, H - T - B
    vals = [v for s in series if not (dual and s.get("axis") == "right")
            for v in s["values"] if v is not None]
    errs = [e for s in series for e in (s.get("err") or [])]
    span = max(vals) + (max(errs) if errs else 0)
    hi, ticks = nice_ticks(spec.get("ymax") or span or 1)
    lo = 0  # bar charts never start off zero
    # A horizontal bar chart with negative values (a change: gained vs lost) diverges
    # from a zero line in the middle; all-positive data keeps the axis at zero on the left.
    if horiz and vals and min(vals) < 0:
        hi, ticks = nice_ticks(spec.get("ymax") or max(abs(v) for v in vals) or 1)
        lo = -hi
        ticks = [-v for v in reversed(ticks) if v > 0] + ticks
    if dual:
        _rv = [v for s in series if s.get("axis") == "right" for v in s["values"] if v is not None]
        hi2, ticks2 = nice_ticks(spec.get("ymax_right") or max(_rv) or 1)
    # invert: smallest value at the TOP. For rank-like scales (Google position,
    # league table place) where 1 is best, so "better" reads as "up".
    invert = bool(spec.get("invert")) and not horiz
    bands = spec.get("bands") or []
    given = spec.get("colors")
    given = given if isinstance(given, list) and given else PALETTE
    pal = [safe_colour(c, PALETTE[i % len(PALETTE)]) for i, c in enumerate(given)]
    p = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
         f'font-family="inherit" font-size="11" role="img">']
    if spec.get("title"):
        p.append(f'<text x="0" y="14" font-size="12.5" font-weight="700" '
                 f'fill="currentColor">{html.escape(spec["title"])}</text>')

    def y(v):
        f = (v - lo) / (hi - lo)
        return T + f * ph if invert else T + ph - f * ph

    def y2(v):
        return T + ph - (v / hi2) * ph

    BAND = {"green": "#16a34a", "orange": "#f59e0b", "amber": "#f59e0b",
            "red": "#dc2626", "grey": "#7a869a", "gray": "#7a869a"}
    def band_color(c):
        c = BAND.get(c.lower(), c) if isinstance(c, str) else c
        return safe_colour(c, BAND_GREY)
    drawn = []
    for b in bands if not horiz else []:
        b0, b1 = max(lo, float(b.get("from", lo))), min(hi, float(b.get("to", hi)))
        if b1 <= b0:
            continue          # band sits entirely outside this chart's scale
        drawn.append(b)
        yA, yB = sorted((y(b0), y(b1)))
        col = band_color(b.get("color", "grey"))
        p.append(f'<rect x="{L}" y="{yA:.1f}" width="{pw}" height="{yB-yA:.1f}" '
                 f'fill="{col}" opacity="{safe_opacity(b.get("opacity", BAND_OPACITY))}"/>')

    if horiz:
        for v in ticks:
            xx = L + (v - lo) / (hi - lo) * pw
            p.append(f'<line x1="{xx:.1f}" x2="{xx:.1f}" y1="{T}" y2="{T+ph}" '
                     f'stroke="var(--grid)" stroke-width="1"/>')
            p.append(f'<text x="{xx:.1f}" y="{T+ph+14}" text-anchor="middle" '
                     f'fill="var(--muted)" opacity=".85">{v:g}</text>')
    else:
        for v in ticks:
            yy = y(v)
            p.append(f'<line x1="{L}" x2="{W-R}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="var(--grid)" '
                     f'stroke-width="1"/>')
            p.append(f'<text x="{L-8}" y="{yy+3.5:.1f}" text-anchor="end" fill="var(--muted)" '
                     f'opacity=".85">{v:g}</text>')
    if spec.get("y_label"):
        p.append(f'<text x="0" y="{T-6}" fill="var(--muted)" font-size="10">'
                 f'{html.escape(spec["y_label"])}</text>')
    if dual:
        for v in ticks2:
            p.append(f'<text x="{W-R+8}" y="{y2(v)+3.5:.1f}" text-anchor="start" '
                     f'fill="var(--muted)" opacity=".85">{v:g}</text>')
        if spec.get("y_label_right"):
            p.append(f'<text x="{W}" y="{T-6}" text-anchor="end" fill="var(--muted)" '
                     f'font-size="10">{html.escape(spec["y_label_right"])}</text>')

    n, m = len(xs), len(series)
    if horiz:
        gh = ph / n
        bh = min(26, (gh * 0.74) / m)
        def xv(v): return L + (v - lo) / (hi - lo) * pw
        for si, s_ in enumerate(series):
            c = pal[si % len(pal)]
            for i, v in enumerate(s_["values"]):
                if v is None: continue
                cy = T + gh * i + gh / 2 + (si - (m - 1) / 2) * bh
                x0 = xv(0)
                p.append(f'<rect x="{min(x0, xv(v)):.1f}" y="{cy-bh/2:.1f}" '
                         f'width="{abs(xv(v)-x0):.1f}" '
                         f'height="{bh:.1f}" fill="{c}" opacity=".88"/>')
                tx, anc = (xv(v) + 6, "start") if v >= 0 else (xv(v) - 6, "end")
                p.append(f'<text x="{tx:.1f}" y="{cy+3.5:.1f}" fill="currentColor" '
                         f'text-anchor="{anc}" font-size="10.5">{v:g}</text>')
        for i, lab in enumerate(xs):
            p.append(f'<text x="{L-8}" y="{T+gh*i+gh/2+3.5:.1f}" text-anchor="end" '
                     f'fill="currentColor" font-size="10.5">{html.escape(str(lab))}</text>')
        p.append(f'<line x1="{xv(0):.1f}" x2="{xv(0):.1f}" y1="{T}" y2="{T+ph}" '
                 f'stroke="currentColor" stroke-width="1.5"/>')
        p.append("</svg>")
        cap0 = spec.get("note") or spec.get("caption")
        # The reference nests an f-string with a backslash inside this one, which is a
        # SyntaxError before Python 3.12; the package supports 3.11. Same output.
        capf0 = f"<div class='cap'>{html.escape(cap0)}</div>" if cap0 else ""
        return f'<div class="chart">{"".join(p)}{capf0}</div>'
    if t == "line":
        def pt_color(v, dflt):
            if m > 1:
                return dflt   # several series: the series colour must stay readable
            for b in bands:
                if float(b.get("from", lo)) <= v <= float(b.get("to", hi)):
                    return band_color(b.get("color", dflt))
            return dflt
        for si, s in enumerate(series):
            yf = y2 if (dual and s.get("axis") == "right") else y
            # "gaps": "break" ends the line at a missing value instead of bridging it,
            # so months without data do not read as a straight trend.
            runs, cur = [], []
            for i, v in enumerate(s["values"]):
                if v is None:
                    if spec.get("gaps") == "break" and cur:
                        runs.append(cur); cur = []
                    continue
                cur.append(f"{L + (pw*(i+0.5)/n):.1f},{yf(v):.1f}")
            if cur:
                runs.append(cur)
            c = pal[si % len(pal)]
            for run in runs:
                p.append(f'<polyline points="{" ".join(run)}" fill="none" stroke="{c}" '
                         f'stroke-width="2.2" stroke-linejoin="round"/>')
            for i, v in enumerate(s["values"]):
                if v is not None:
                    p.append(f'<circle cx="{L+(pw*(i+0.5)/n):.1f}" cy="{yf(v):.1f}" r="3.4" '
                             f'fill="{pt_color(v, c)}" stroke="var(--bg)" stroke-width="1"/>')
    else:
        gw = pw / n
        bw = min(46, (gw * 0.74) / m)
        for si, s in enumerate(series):
            c = pal[si % len(pal)]
            for i, v in enumerate(s["values"]):
                if v is None: continue
                cx = L + gw * i + gw / 2 + (si - (m - 1) / 2) * bw
                y0, yv = (T if invert else T + ph), y(v)
                p.append(f'<rect x="{cx-bw/2:.1f}" y="{min(yv,y0):.1f}" width="{bw:.1f}" '
                         f'height="{abs(y0-yv):.1f}" fill="{c}" opacity=".88"/>')
                e = (s.get("err") or [None]*n)[i]
                if e:
                    p.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(v-e):.1f}" y2="{y(v+e):.1f}" '
                             f'stroke="currentColor" stroke-width="1.4"/>'
                             f'<line x1="{cx-5:.1f}" x2="{cx+5:.1f}" y1="{y(v+e):.1f}" y2="{y(v+e):.1f}" '
                             f'stroke="currentColor" stroke-width="1.4"/>'
                             f'<line x1="{cx-5:.1f}" x2="{cx+5:.1f}" y1="{y(v-e):.1f}" y2="{y(v-e):.1f}" '
                             f'stroke="currentColor" stroke-width="1.4"/>')
    # x axis: heavy line on the baseline edge (top when inverted), labels stay at the bottom
    p.append(f'<line x1="{L}" x2="{W-R}" y1="{T if invert else T+ph}" y2="{T if invert else T+ph}" '
             f'stroke="currentColor" stroke-width="1.5"/>')
    if invert:
        p.append(f'<line x1="{L}" x2="{W-R}" y1="{T+ph}" y2="{T+ph}" stroke="var(--grid)" stroke-width="1"/>')
    for i, lab in enumerate(xs):
        cx = L + pw * (i + 0.5) / n
        if xlab_rot:
            p.append(f'<text x="{cx:.1f}" y="{T+ph+14:.1f}" text-anchor="end" '
                     f'fill="currentColor" transform="rotate(-32 {cx:.1f} {T+ph+14:.1f})">'
                     f'{html.escape(xlab_lines[i][0])}</text>')
        else:
            for li, ln in enumerate(xlab_lines[i]):
                p.append(f'<text x="{cx:.1f}" y="{T+ph+16+li*12:.1f}" text-anchor="middle" '
                         f'fill="currentColor">{html.escape(ln)}</text>')
    if m > 1:
        lx, ly = L, H - 14 - 20 * (_legrows - 1)
        for si, s in enumerate(series):
            c = pal[si % len(pal)]
            w_ = _legw[si]
            if lx + w_ > (W - R) and lx > L:
                lx, ly = L, ly + 20
            p.append(f'<rect x="{lx:.1f}" y="{ly:.1f}" width="10" height="10" fill="{c}"/>'
                     f'<text x="{lx+15:.1f}" y="{ly+8.5:.1f}" fill="currentColor">'
                     f'{html.escape(s.get("name",""))}</text>')
            lx += w_
    p.append("</svg>")
    cap = spec.get("note") or spec.get("caption")
    capf = f'<div class="cap">{html.escape(cap)}</div>' if cap else ""
    bleg = ""
    if any(b.get("label") for b in drawn):
        bleg = ('<div class="bandleg">' + "".join(
            f'<span><i style="background:{band_color(b.get("color","grey"))}"></i>'
            f'{html.escape(str(b["label"]))}</span>'
            for b in drawn if b.get("label")) + "</div>")
    return f'<div class="chart">{"".join(p)}{bleg}{capf}</div>'


def render_charts(hml):
    def repl(m):
        try:
            spec = json.loads(html.unescape(m.group(1)))
        except Exception as e:
            return f'<pre><code>chart spec error: {html.escape(str(e))}</code></pre>'
        try:
            return svg_chart(spec) or m.group(0)
        except Exception as e:
            # Well-formed JSON with a value of the wrong kind (a string for a height,
            # a list for the spec): say so in place, like bad JSON, and draw the rest.
            return f'<pre><code>chart spec error: {html.escape(type(e).__name__)}: {html.escape(str(e))}</code></pre>'
    return re.sub(r'<pre[^>]*class="(?:language-)?chart"[^>]*>\s*<code[^>]*>([\s\S]*?)</code>\s*</pre>',
                  repl, hml)

MERMAID_RE = re.compile(r'<pre[^>]*class="(?:language-)?mermaid"[^>]*>\s*<code[^>]*>([\s\S]*?)</code>\s*</pre>')


def render_mermaid(hml, log):
    """```mermaid fences -> inline SVG, through the mermaid CLI (mmdc).

    Inline, like the charts, so the page stays self-contained: no mermaid.js from a
    CDN. Each diagram is cached by its source, so only a new or changed diagram pays
    for mmdc, and all of those go through ONE mmdc run (markdown mode): mmdc starts
    a headless Chrome each time, about 8 s, so one run per diagram would make a page
    with seven diagrams take a minute. mmdc names every SVG "my-svg" and its <style>
    selects on that id, so two diagrams on one page restyle each other; each gets
    its own id. Without mmdc the diagram stays a code block and the log says so.
    """
    found = MERMAID_RE.findall(hml)
    if not found:
        return hml
    srcs = [html.unescape(f) for f in found]
    keys = [hashlib.sha256(x.encode()).hexdigest()[:12] for x in srcs]
    cache = paths.cache_dir() / "mermaid"
    todo = [(k, x) for k, x in dict(zip(keys, srcs)).items() if not (cache / f"{k}.svg").exists()]
    if todo:
        exe = shutil.which("mmdc")
        if not exe:
            log.append(f"  ! {len(found)} mermaid diagram(s) left as code: mmdc is not installed "
                       "(npm install -g @mermaid-js/mermaid-cli)")
            return hml
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "pp.json").write_text('{"args":["--no-sandbox"]}')
            (d / "in.md").write_text("".join(f"```mermaid\n{x.rstrip()}\n```\n\n" for _, x in todo))
            r = subprocess.run([exe, "-q", "-p", str(d / "pp.json"), "-i", str(d / "in.md"),
                                "-o", str(d / "out.md"), "-b", "white", "-t", "neutral"],
                               capture_output=True, text=True, timeout=300)
            for n, (k, _) in enumerate(todo, 1):
                svg = d / f"out-{n}.svg"
                if svg.exists():
                    (cache / f"{k}.svg").write_text(svg.read_text().replace("my-svg", f"mmd-{k}"))
            if r.returncode != 0:
                log.append("  ! mermaid: " + " ".join((r.stderr or r.stdout).split())[:300])
    def repl(m):
        k = hashlib.sha256(html.unescape(m.group(1)).encode()).hexdigest()[:12]
        f = cache / f"{k}.svg"
        if not f.exists():
            return m.group(0)
        return f'<div class="mermaid-svg">{f.read_text()}</div>'
    out = MERMAID_RE.sub(repl, hml)
    made = sum(1 for k, _ in todo if (cache / f"{k}.svg").exists())
    left = sum(1 for k in keys if not (cache / f"{k}.svg").exists())
    log.append(f"  + {len(found)} mermaid diagram(s), {made} rendered now"
               + (f", {left} left as code (see the mermaid error above)" if left else ""))
    return out
