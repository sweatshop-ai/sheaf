"""Every copy Chrome prints carries a CSP of its own (SPEC 6.5, 9.5, 9.9 "Local images"): a
`<meta http-equiv="Content-Security-Policy">` as the first element of its `head`, so headless
Chrome loads no `file:` address and no remote one into a PDF, whatever element or property names
it. In loopback mode as in proxy mode, so a `url(file:…)` a git collaborator wrote does not print the
owner's file into a share PDF either.

The copy Chrome is handed is checked everywhere with a stand-in Chrome that keeps it. The case
that found the gap runs where a real Chrome and poppler's `pdfimages` are installed: a span
whose `style` paints a PNG from outside every root gives a PDF with no image, and the same copy
printed without the `<meta>` gives one, 600 by 400, so the test cannot pass on a Chrome that loads
nothing."""
import json
import shutil
import stat
import subprocess
from html.parser import HTMLParser

import pytest
from PIL import Image

from helpers import BEA, UnixHTTP, write
from sheafmd import pdf

CSP = ("<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
       "style-src 'unsafe-inline'; img-src data:; font-src data:\">")
HAS_PDFIMAGES = pdf.find_chrome() is not None and shutil.which("pdfimages") is not None
NEEDS_CHROME_AND_PDFIMAGES = pytest.mark.skipif(
    not HAS_PDFIMAGES, reason="needs Chrome or Chromium and poppler's pdfimages")


def keeping_chrome(folder, kept):
    """A stand-in Chrome that copies the page it was handed to `kept` and prints a small PDF."""
    exe = folder / "keeping-chrome"
    exe.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do case "$a" in\n'
        f'  file://*) cp "${{a#file://}}" "{kept}";;\n'
        '  --print-to-pdf=*) printf "%%PDF-kept" > "${a#--print-to-pdf=}";;\n'
        "esac; done\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return str(exe)


class _Head(HTMLParser):
    """The tags of a page in the order a reader meets them, up to the first one in `body`."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    handle_startendtag = handle_starttag


def first_tag_after_head_opens(html):
    """The first element a browser puts in `head`: the first tag that is not `html` or `head`."""
    p = _Head()
    p.feed(html)
    return next(t for t in p.tags if t[0] not in ("html", "head"))


def test_the_copy_chrome_is_handed_opens_its_head_with_the_csp(tmp_path, monkeypatch):
    kept = tmp_path / "kept.html"
    monkeypatch.setattr(pdf, "find_chrome", lambda: keeping_chrome(tmp_path, kept))
    pdf.write_pdf('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>t</title>'
                  "</head><body><h1>Hello</h1></body></html>", tmp_path / "out.pdf")
    copy = kept.read_text(encoding="utf-8")
    assert first_tag_after_head_opens(copy) == ("meta", {
        "http-equiv": "Content-Security-Policy",
        "content": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:"})
    assert copy.startswith('<!doctype html>\n<html lang="en"><head>' + CSP + '<meta charset="utf-8">')


@pytest.mark.parametrize("html", [
    "<!doctype html><title>t</title><h1>Hello</h1>",                 # no html and no head tag
    "<!DOCTYPE html>\n<HTML><HEAD lang=x><TITLE>t</TITLE></HEAD><body>x",
    "<html><head><title>t</title></head>x",
    "<h1>only a fragment</h1>",
    "<!-- a note --><html><head><title>t</title></head>x",
])
def test_a_page_of_any_shape_gets_the_csp_as_its_first_head_element(html):
    copy = pdf.with_print_csp(html)
    assert first_tag_after_head_opens(copy)[1].get("http-equiv") == "Content-Security-Policy"
    assert copy.replace(CSP, "", 1) == html


# ── the case that found the gap, with a real Chrome ─────────────────────────

@pytest.fixture
def outside_png(tmp_path_factory):
    """A PNG of 600 by 400 in a folder that is no root, striped so no printer can fold it away."""
    png = tmp_path_factory.mktemp("outside") / "secret.png"
    img = Image.new("RGB", (600, 400), (200, 30, 30))
    for x in range(0, 600, 40):
        img.paste((20, 20, 160), (x, 0, x + 20, 400))
    img.save(png)
    return png


def painting_span(png):
    return ('<span style="display:inline-block; width:600px; height:400px; print-color-adjust:exact; '
            f'background:url({png.as_uri()})"></span>')


def images_in(pdf_file):
    """The images `pdfimages -list` finds in a PDF, as (width, height)."""
    out = subprocess.run(["pdfimages", "-list", str(pdf_file)], capture_output=True, text=True,
                         check=True, timeout=60).stdout.splitlines()
    return [(int(cols[3]), int(cols[4])) for cols in (line.split() for line in out[2:]) if cols]


@NEEDS_CHROME_AND_PDFIMAGES
def test_a_style_url_of_a_file_prints_no_image_and_does_without_the_csp(tmp_path, short_tmp, outside_png):
    html = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>t</title></head>'
            f"<body><h1>Plan</h1><p>{painting_span(outside_png)}</p></body></html>")
    pdf.write_pdf(html, tmp_path / "with.pdf")
    assert images_in(tmp_path / "with.pdf") == []
    bare = write(tmp_path / "bare.html", html)                 # the control: printed as it is
    pdf.print_pdf(bare, tmp_path / "without.pdf")
    assert images_in(tmp_path / "without.pdf") == [(600, 400)]


# ── through the CLI and through /_/export (loopback mode) ───────────────────

def test_the_cli_hands_chrome_the_share_copy_with_the_csp(work, sheaf, monkeypatch, tmp_path):
    kept = tmp_path / "kept.html"
    monkeypatch.setattr(pdf, "find_chrome", lambda: keeping_chrome(tmp_path, kept))
    doc = write(work / "doc.md", "# Plan\n\nThe harbour opens in spring.\n")
    r = sheaf(doc, "--share", "--pdf")
    assert r.code == 0, r.err
    copy = kept.read_text(encoding="utf-8")
    assert first_tag_after_head_opens(copy)[1].get("http-equiv") == "Content-Security-Policy"
    assert CSP not in (work / "doc-share.html").read_text(encoding="utf-8")   # only the printed copy


def test_the_export_hands_chrome_the_share_copy_with_the_csp(browser, plan, monkeypatch, tmp_path):
    kept = tmp_path / "kept.html"
    monkeypatch.setattr(pdf, "find_chrome", lambda: keeping_chrome(tmp_path, kept))
    r = browser.post("/_/export", {"doc": "work/plan.md", "kind": "pdf"})
    assert r.status == 200 and r.body == b"%PDF-kept"
    assert first_tag_after_head_opens(kept.read_text(encoding="utf-8"))[1].get("http-equiv") \
        == "Content-Security-Policy"


@NEEDS_CHROME_AND_PDFIMAGES
def test_a_share_pdf_of_the_cli_prints_no_file_a_style_names(work, sheaf, short_tmp, outside_png):
    doc = write(work / "doc.md", f"# Plan\n\n{painting_span(outside_png)}\n\nText.\n")
    r = sheaf(doc, "--share", "--pdf")
    assert r.code == 0, r.err
    assert painting_span(outside_png) in (work / "doc-share.html").read_text(encoding="utf-8")
    assert images_in(work / "doc-share.pdf") == []


@NEEDS_CHROME_AND_PDFIMAGES
def test_a_pdf_export_prints_no_file_a_style_names(browser, work, short_tmp, outside_png, tmp_path):
    f = write(work / "plan.md", f"# Plan\n\n{painting_span(outside_png)}\n\nText.\n")
    browser.hub.roots.for_document(f)
    r = browser.post("/_/export", {"doc": "work/plan.md", "kind": "pdf"})
    assert r.status == 200 and r.body.startswith(b"%PDF")
    printed = tmp_path / "export.pdf"
    printed.write_bytes(r.body)
    assert images_in(printed) == []


@NEEDS_CHROME_AND_PDFIMAGES
def test_a_pdf_exported_through_the_proxy_socket_prints_no_file_a_style_names(proxy_served, work, short_tmp,
                                                                             outside_png, tmp_path):
    hub = proxy_served
    write(work / "plan.md", f"# Plan\n\n{painting_span(outside_png)}\n\nText.\n")
    c = UnixHTTP(hub.proxy.socket, timeout=120)
    body = json.dumps({"doc": "work/plan.md", "kind": "pdf"}).encode()
    c.request("POST", "/_/export", body=body, headers={
        "Host": hub.proxy.host, "Origin": hub.proxy.origin, "X-Sheaf-Member": BEA,
        "Content-Type": "application/json", "Content-Length": str(len(body))})
    r = c.getresponse()
    data = r.read()
    c.close()
    assert r.status == 200 and data.startswith(b"%PDF")
    printed = tmp_path / "proxy.pdf"
    printed.write_bytes(data)
    assert images_in(printed) == []
