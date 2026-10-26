"""Local images become data: URIs, downscaled to the page width and captioned."""
import base64
import io
import os
import re

import pytest
from PIL import Image

import sheafmd
from sheafmd import images


def png(path, width=40, height=20, mode="RGB", noise=False):
    """Write a small PNG. Noise makes it big enough that a downscale visibly shrinks it."""
    if noise:
        size = width * height * len(mode)
        im = Image.frombytes(mode, (width, height), os.urandom(size))
    else:
        im = Image.new(mode, (width, height), (200, 30, 30, 255)[:len(mode)])
    im.save(path, "PNG")
    return path


def decode(uri):
    """The mime type and the bytes inside a data: URI."""
    m = re.fullmatch(r"data:([\w/+.-]+);base64,([A-Za-z0-9+/=]+)", uri)
    assert m, uri[:60]
    return m.group(1), base64.b64decode(m.group(2))


def src_of(out):
    return re.search(r'<img src="([^"]+)"', out).group(1)


def test_a_local_image_becomes_a_figure_with_a_data_uri(tmp_path):
    p = png(tmp_path / "pic.png")
    log = []
    out = images.process_images('<p><img src="pic.png" alt="x"></p>', tmp_path, 700, log)
    assert out.startswith('<p><figure><img src="data:image/png;base64,')
    assert out.endswith('alt="x" loading="lazy"><figcaption>x</figcaption></figure></p>')
    mime, raw = decode(src_of(out))
    assert mime == "image/png"
    assert raw == p.read_bytes()              # narrower than max_w: the bytes are untouched
    assert log == ["  + embedded pic.png (0 KB)"]


def test_the_caption_is_the_title_else_the_alt_text_else_none(tmp_path):
    png(tmp_path / "pic.png")
    both = images.process_images('<img src="pic.png" alt="Alt words" title="Title words">',
                                 tmp_path, 700, [])
    assert "<figcaption>Title words</figcaption>" in both
    assert "Alt words" in both.split("<figcaption>")[0]                   # kept as the alt attribute
    only_alt = images.process_images('<img src="pic.png" alt="Alt words">', tmp_path, 700, [])
    assert "<figcaption>Alt words</figcaption>" in only_alt
    empty_title = images.process_images('<img src="pic.png" alt="Alt words" title="">', tmp_path, 700, [])
    assert "<figcaption>Alt words</figcaption>" in empty_title
    for tag in ('<img src="pic.png">', '<img src="pic.png" alt="">'):
        bare = images.process_images(tag, tmp_path, 700, [])
        assert "figcaption" not in bare
        assert bare.startswith('<figure><img src="data:image/png;base64,')
        assert bare.endswith('loading="lazy"></figure>')


def test_an_image_is_found_relative_to_the_document_folder(tmp_path):
    (tmp_path / "docs" / "img").mkdir(parents=True)
    p = png(tmp_path / "docs" / "img" / "pic.png")
    out = images.process_images('<img src="img/pic.png" alt="x">', tmp_path / "docs", 700, [])
    assert decode(src_of(out))[1] == p.read_bytes()


def test_an_absolute_path_is_used_as_it_is(tmp_path):
    p = png(tmp_path / "pic.png")
    elsewhere = tmp_path / "docs"
    elsewhere.mkdir()
    out = images.process_images(f'<img src="{p}" alt="x">', elsewhere, 700, [])
    assert decode(src_of(out))[1] == p.read_bytes()


def test_an_image_wider_than_max_w_is_downscaled(tmp_path):
    png(tmp_path / "wide.png", 400, 200, noise=True)
    raw_size = (tmp_path / "wide.png").stat().st_size
    log = []
    out = images.process_images('<img src="wide.png" alt="x">', tmp_path, 100, log)
    mime, raw = decode(src_of(out))
    assert mime == "image/jpeg"               # an opaque PNG goes out as a JPEG
    im = Image.open(io.BytesIO(raw))
    assert im.size == (100, 50)               # width max_w, height in proportion
    assert len(raw) < raw_size
    assert log == ["  + embedded wide.png (downscaled 400px -> 100px)"]


def test_a_transparent_png_stays_a_png_when_downscaled(tmp_path):
    png(tmp_path / "clear.png", 300, 100, mode="RGBA", noise=True)
    log = []
    out = images.process_images('<img src="clear.png" alt="x">', tmp_path, 100, log)
    mime, raw = decode(src_of(out))
    assert mime == "image/png"
    im = Image.open(io.BytesIO(raw))
    assert im.size == (100, 33) and im.mode == "RGBA"
    assert "downscaled 300px -> 100px" in log[0]


def test_an_image_exactly_max_w_wide_is_not_resized(tmp_path):
    p = png(tmp_path / "exact.png", 100, 50, noise=True)
    log = []
    out = images.process_images('<img src="exact.png" alt="x">', tmp_path, 100, log)
    assert decode(src_of(out))[1] == p.read_bytes()
    assert "downscaled" not in log[0]


def test_a_downscale_that_would_not_shrink_the_file_keeps_the_original_bytes(tmp_path):
    # A flat colour PNG of 120x60 is 218 bytes; the 100px JPEG it would be rewritten
    # as is 329 bytes (a JPEG has a fixed header), so the original stays.
    p = png(tmp_path / "flat.png", 120, 60)
    assert p.stat().st_size < 300
    log = []
    out = images.process_images('<img src="flat.png" alt="x">', tmp_path, 100, log)
    mime, raw = decode(src_of(out))
    assert raw == p.read_bytes()
    assert Image.open(io.BytesIO(raw)).size == (120, 60)
    assert log == ["  + embedded flat.png (0 KB)"]


def test_a_file_that_is_not_an_image_is_embedded_as_it_is_and_says_so(tmp_path):
    (tmp_path / "broken.png").write_bytes(b"this is not a png")
    log = []
    out = images.process_images('<img src="broken.png" alt="x">', tmp_path, 100, log)
    assert decode(src_of(out)) == ("image/png", b"this is not a png")
    assert log[0].startswith("  + embedded broken.png (embedded as-is (")


def test_a_missing_file_leaves_a_red_marker_and_a_log_line(tmp_path):
    log = []
    out = images.process_images('<p><img src="nope.png" alt="x"></p>', tmp_path, 700, log)
    assert out == '<p><span style="color:#c00">[missing image: nope.png]</span></p>'
    assert log == [f"  ! image not found: {(tmp_path / 'nope.png').resolve()}"]


def test_the_missing_marker_escapes_the_source_path(tmp_path):
    out = images.process_images('<img src="a&b<c>.png">', tmp_path, 700, [])
    assert "[missing image: a&amp;b&lt;c&gt;.png]" in out


def test_a_remote_image_is_left_as_it_is_and_the_log_says_it_breaks_self_containment(tmp_path):
    tags = ['<img src="https://example.com/a.png" alt="a">',
            '<img src="http://example.com/b.png" alt="b" title="t">']
    log = []
    out = images.process_images("".join(tags), tmp_path, 700, log)
    assert out == "".join(tags)
    assert log == [
        "  ! remote image left as-is (breaks self-containment): https://example.com/a.png",
        "  ! remote image left as-is (breaks self-containment): http://example.com/b.png",
    ]


def test_a_data_image_is_left_alone_with_no_log(tmp_path):
    tag = '<img src="data:image/png;base64,iVBORw0KGgo=" alt="a">'
    log = []
    assert images.process_images(tag, tmp_path, 700, log) == tag
    assert log == []


def test_an_svg_is_embedded_as_svg_and_never_resized(tmp_path):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="10"><rect width="5" height="5"/></svg>'
    (tmp_path / "logo.svg").write_bytes(svg)
    log = []
    out = images.process_images('<img src="logo.svg" alt="Logo">', tmp_path, 100, log)
    assert decode(src_of(out)) == ("image/svg+xml", svg)
    assert "<figcaption>Logo</figcaption>" in out
    assert log == ["  + embedded logo.svg (0 KB)"]


def test_an_unsupported_extension_is_reported_and_not_embedded(tmp_path):
    Image.new("RGB", (4, 4)).save(tmp_path / "pic.bmp", "BMP")
    log = []
    out = images.process_images('<img src="pic.bmp" alt="x">', tmp_path, 700, log)
    assert out == '<span style="color:#c00">[missing image: pic.bmp]</span>'
    assert "data:" not in out
    assert log == ["  ! image unsupported type: .bmp"]


def test_the_extension_check_ignores_case(tmp_path):
    png(tmp_path / "PIC.PNG")
    out = images.process_images('<img src="PIC.PNG" alt="x">', tmp_path, 700, [])
    assert src_of(out).startswith("data:image/png;base64,")


def test_every_image_in_a_page_is_handled_and_the_text_around_it_is_not_touched(tmp_path):
    png(tmp_path / "one.png")
    png(tmp_path / "two.png", 30, 30)
    log = []
    page = ('<h1>T</h1><p>See <img src="one.png" alt="first"> and '
            '<img src="https://example.com/r.png" alt="r"> then <img src="two.png" title="second">.</p>')
    out = images.process_images(page, tmp_path, 700, log)
    assert out.startswith("<h1>T</h1><p>See <figure>")
    assert out.endswith("</figure>.</p>")
    assert '<img src="https://example.com/r.png" alt="r">' in out
    assert out.count("<figure>") == 2
    assert "<figcaption>first</figcaption>" in out and "<figcaption>second</figcaption>" in out
    assert [line.split("(")[0].strip() for line in log] == [
        "+ embedded one.png", "! remote image left as-is", "+ embedded two.png"]


def test_embed_image_returns_the_reason_when_it_cannot_embed(tmp_path):
    assert images.embed_image(tmp_path / "gone.png", 100) == (None, f"not found: {tmp_path / 'gone.png'}")
    (tmp_path / "x.tiff").write_bytes(b"II*\x00")
    assert images.embed_image(tmp_path / "x.tiff", 100) == (None, "unsupported type: .tiff")


# ── the source is a URL, as pandoc writes it ─────────────────────────────────

@pytest.mark.parametrize("name, src", [
    ("a&b.png", "a&amp;b.png"),                  # pandoc escapes the ampersand in the attribute
    ("my plot.png", "my%20plot.png"),            # a percent escape is a space
    ("my plot.png", "my plot.png"),              # <my plot.png> in markdown: no escape at all
    ("naïve é.png", "na%C3%AFve%20%C3%A9.png"),  # UTF-8 escapes
    ("fig.png", "fig.png#small"),                # a fragment is not part of the name
    ("fig.png", "fig.png?v=2"),                  # nor is a query
    ("a&b.png", "a&amp;b.png#x"),
])
def test_a_source_is_read_as_a_url_before_it_is_a_file_name(tmp_path, name, src):
    p = png(tmp_path / name)
    log = []
    out = images.process_images(f'<img src="{src}" alt="x">', tmp_path, 700, log)
    assert decode(src_of(out))[1] == p.read_bytes()
    assert log == [f"  + embedded {name} (0 KB)"]


def test_an_absolute_path_may_carry_escapes_too(tmp_path):
    (tmp_path / "docs").mkdir()
    p = png(tmp_path / "a b&c.png")
    src = str(p).replace(" ", "%20").replace("&", "&amp;")
    out = images.process_images(f'<img src="{src}" alt="x">', tmp_path / "docs", 700, [])
    assert decode(src_of(out))[1] == p.read_bytes()


@pytest.mark.parametrize("name, src", [
    ("50%25.png", "50%25.png"),                  # the file really is called that
    ("C#.png", "C#.png"),
    ("what?.png", "what?.png"),
    ("100%.png", "100%.png"),                    # not an escape at all
])
def test_a_name_that_is_not_a_url_is_still_found_as_written(tmp_path, name, src):
    p = png(tmp_path / name)
    out = images.process_images(f'<img src="{src}" alt="x">', tmp_path, 700, [])
    assert decode(src_of(out))[1] == p.read_bytes()


def test_the_url_reading_wins_when_both_readings_name_a_file(tmp_path):
    asked = png(tmp_path / "my plot.png", 40, 20)
    png(tmp_path / "my%20plot.png", 30, 30)
    out = images.process_images('<img src="my%20plot.png" alt="x">', tmp_path, 700, [])
    assert decode(src_of(out))[1] == asked.read_bytes()


@pytest.mark.parametrize("src", ["//cdn.example/x.png", "//cdn.example/x.png?v=1", "HTTPS://example.com/a.png",
                                 "Http://example.com/a.png"])
def test_a_protocol_relative_or_upper_case_remote_source_is_remote_not_a_path(tmp_path, src):
    tag = f'<img src="{src}" alt="a">'
    log = []
    assert images.process_images(tag, tmp_path, 700, log) == tag
    assert log == [f"  ! remote image left as-is (breaks self-containment): {src}"]


def test_a_file_url_is_the_file_it_names(tmp_path):
    p = png(tmp_path / "my plot.png")
    out = images.process_images(f'<img src="file://{str(p).replace(" ", "%20")}" alt="x">',
                                tmp_path / "elsewhere", 700, [])
    assert decode(src_of(out))[1] == p.read_bytes()


def test_a_source_with_another_scheme_is_never_read_as_a_local_path(tmp_path):
    p = png(tmp_path / "pic.png")
    log = []
    out = images.process_images(f'<img src="ftp://host{p}" alt="x">', tmp_path, 700, log)
    assert "[missing image:" in out and "data:image" not in out
    assert len(log) == 1 and log[0].startswith("  ! image not found: ")


def test_a_missing_image_names_its_source_once_escaped(tmp_path):
    log = []
    out = images.process_images('<img src="a&amp;b%20c.png" alt="x">', tmp_path, 700, log)
    assert "[missing image: a&amp;b%20c.png]" in out and "amp;amp" not in out
    assert len(log) == 1 and log[0].startswith("  ! image not found: ")


def test_a_markdown_document_finds_images_written_with_escapes(tmp_path):
    a = png(tmp_path / "a&b.png", 40, 20)
    b = png(tmp_path / "my plot.png", 30, 30)
    md = tmp_path / "doc.md"
    md.write_text("# T\n\n![one](a&b.png) ![two](my%20plot.png) ![three](<my plot.png>)\n")
    out = sheafmd.render(md)
    uris = re.findall(r'<img src="(data:[^"]+)"', out)
    assert [decode(u)[1] for u in uris] == [a.read_bytes(), b.read_bytes(), b.read_bytes()]
    assert "missing image" not in out


def test_a_caption_with_an_ampersand_is_escaped_once(tmp_path):
    """The attribute arrives escaped (`&amp;`); the caption must not escape it again,
    or the page shows the text `&amp;`. A fix against the reference, which did."""
    png(tmp_path / "pic.png")
    out = images.process_images('<img src="pic.png" alt="Q &amp; A" title="Tom &amp; Jerry &quot;live&quot; &lt;3">',
                                tmp_path, 700, [])
    assert "<figcaption>Tom &amp; Jerry &quot;live&quot; &lt;3</figcaption>" in out
    alt_only = images.process_images('<img src="pic.png" alt="Q &amp; A">', tmp_path, 700, [])
    assert "<figcaption>Q &amp; A</figcaption>" in alt_only
    assert 'alt="Q &amp; A"' in alt_only                       # the alt attribute is left as it came
