"""
sheafmd.images — local images become data: URIs, downscaled, captioned.

Why this exists
---------------
A sheaf page is one self-contained file that works over file://, offline and when
forwarded. A local <img src="figure.png"> would break the moment the page moves, so
each one is read, downscaled to the page width and inlined as base64, then wrapped in
a <figure> captioned from its title, else its alt text. Remote and data: images are
left as they are (a remote one is logged, because it breaks self-containment).

The source is an attribute value, so it is a URL as pandoc wrote it: `a&amp;b.png` is
the file `a&b.png`, `my%20plot.png` is `my plot.png`, and a query or a fragment is not
part of the name. A name that reads differently as a URL than as written (`C#.png`,
`50%25.png`) is still found as written.
"""

import base64
import html
import io
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


def embed_image(path: Path, max_w: int):
    """Downscale + base64 into a data: URI. Returns (uri, note) or (None, reason). A file this
    account cannot reach or read is missing, like one that is not there."""
    if not os.path.exists(path):
        return None, f"not found: {path}"
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}.get(
                path.suffix.lower())
    if not mime:
        return None, f"unsupported type: {path.suffix}"
    try:
        raw, note = path.read_bytes(), ""
    except OSError as e:
        return None, f"cannot be read: {path} ({e.strerror})"
    if mime != "image/svg+xml":
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(raw))
            if im.width > max_w:
                orig = im.width
                im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
                buf = io.BytesIO()
                if mime == "image/png" and im.mode in ("RGBA", "LA", "P"):
                    im.save(buf, "PNG", optimize=True)
                else:
                    im.convert("RGB").save(buf, "JPEG", quality=82, optimize=True)
                    mime = "image/jpeg"
                if buf.tell() < len(raw):
                    raw, note = buf.getvalue(), f"downscaled {orig}px -> {max_w}px"
        except Exception as e:
            note = f"embedded as-is ({e})"
    return (f"data:{mime};base64," + base64.b64encode(raw).decode(),
            note or f"{len(raw)//1024} KB")

REMOTE = ("http://", "https://", "//")


def local_paths(src: str, base: Path):
    """The files a local source may name, best reading first: as a URL (escapes decoded,
    query and fragment cut off; only for a source with no scheme or `file:`, so
    `ftp://host/etc/x.png` is never the local `/etc/x.png`), then as written. A reading that
    holds a NUL (`%00`) names no file and is left out (SPEC 6.2)."""
    names = []
    try:
        url = urlsplit(src)
        if url.scheme in ("", "file"):
            names.append(unquote(url.path))
    except ValueError:
        pass
    names.append(src)
    out = []
    for n in names:
        if not n or "\0" in n:
            continue
        p = Path(n) if n.startswith("/") else base / n
        if p not in out:
            out.append(p)
    return out


def process_images(hml, base: Path, max_w: int, log, allow=None):
    """Every local <img> of `hml` embedded. `allow(path)`, when given, says which files may be: a
    local image whose file it refuses is left out, element and all, and the log says so, whether
    or not the file exists (proxy mode, SPEC 9.9 "Local images"). A symlink loop is a file that is
    not there (6.2): `os.path.realpath`, unlike `Path.resolve` before Python 3.13, does not raise on one."""
    def missing(src, note):
        log.append(f"  ! image {note}")
        return (f'<span style="color:#c00">[missing image: {html.escape(src)}]</span>')

    def repl(m):
        tag = m.group(0)
        src = html.unescape(m.group(1))
        low = src.lower()
        if low.startswith("data:") or low.startswith(REMOTE):
            if low.startswith(REMOTE):
                log.append(f"  ! remote image left as-is (breaks self-containment): {src}")
            return tag
        found = local_paths(src, base)
        if not found:                       # every reading holds a NUL: no file has such a name
            return missing(src, f"not found: {src}")
        if allow is not None:
            found = [c for c in found if allow(Path(os.path.realpath(c)))]
            if not found:
                log.append(f"  ! image outside this document's root left out: {src}")
                return ""
        p = next((c for c in found if os.path.isfile(c)), found[0])
        uri, note = embed_image(Path(os.path.realpath(p)), max_w)
        if not uri:
            return missing(src, note)
        log.append(f"  + embedded {p.name} ({note})")
        alt = re.search(r'alt="([^"]*)"', tag)
        title = re.search(r'title="([^"]*)"', tag)
        cap = (title.group(1) if title else "") or (alt.group(1) if alt else "")
        img = f'<img src="{uri}" alt="{alt.group(1) if alt else ""}" loading="lazy">'
        if cap:
            # `cap` is an attribute value, already escaped: read it before escaping it
            # for the element, or `&amp;` shows up on the page as the text "&amp;".
            return f'<figure>{img}<figcaption>{html.escape(html.unescape(cap))}</figcaption></figure>'
        return f"<figure>{img}</figure>"
    return re.sub(r'<img\b[^>]*?src="([^"]+)"[^>]*>', repl, hml)
