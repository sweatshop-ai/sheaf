"""The `sheaf` command (SPEC 13): `sheaf FILE.md --share [--out PATH] [--pdf [PATH]] [--open]`.

Most tests call `sheafmd.cli.main(argv)` in this process and read its output with
capsys; a few run `python -m sheafmd` as a real process, so `__main__.py` and the
stdout/stderr split through real pipes are exercised too. Exit codes: 0 done, 1 failed,
2 usage error.

The browser is stubbed for every test in this file (an autouse fixture): nothing here
can open a real window.
"""
import base64
import io
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

from helpers import brand_words_in, names_in, run_module, write
from sheafmd import comments, pdf
from sheafmd.cli import write_text_atomic

NO_CHROME = "Chrome or Chromium is needed to write a PDF and neither is installed."
CREDIT = ('<p class="sheaf-credit">Made with '
          '<a href="https://github.com/sweatshop-ai/sheaf">sheaf</a></p>')
HAS_CHROME = pytest.mark.skipif(pdf.find_chrome() is None, reason="Chrome or Chromium not installed")

DOC_TEXT = "The harbour opens in spring."
SECRET_ONE = "secret-one"
SECRET_TWO = "secret-two"


# ── helpers ─────────────────────────────────────────────────────────────────

class Browser:
    def __init__(self):
        self.calls, self.result = [], True

    def __call__(self, url, *a, **k):
        self.calls.append(url)
        return self.result


@pytest.fixture(autouse=True)
def browser(monkeypatch):
    b = Browser()
    monkeypatch.setattr("sheafmd.cli.webbrowser.open", b)
    return b


@pytest.fixture
def no_chrome(monkeypatch):
    monkeypatch.setattr("sheafmd.pdf.find_chrome", lambda: None)


def commented_doc(work, name="doc.md"):
    """A document with a plain HTML comment and a review comment, each holding a secret."""
    c = comments.Comment(id="c1", by="Grace", at="2026-10-14T10:00", quote="quay",
                         body=f"{SECRET_TWO} body")
    text = (f"# Harbour plan\n\n{DOC_TEXT}\n\n<!-- {SECRET_ONE} -->\n\n"
            f"A closing paragraph about the quay.{comments.format(c, one_line=True)}\n")
    assert [x.id for x in comments.parse(text).comments] == ["c1"]     # the fixture is what it says
    return write(Path(work) / name, text)


def share_page(work, sheaf, text, *opts, name="doc.md"):
    """Share `text` with `opts`, require success, return the written page."""
    doc = write(Path(work) / name, text)
    r = sheaf(doc, "--share", *opts)
    assert r.code == 0, r.err
    return (Path(work) / (Path(name).stem + "-share.html")).read_text(encoding="utf-8")


def headings(n):
    return "".join(f"## Heading {i}\n\nText {i}.\n\n" for i in range(1, n + 1))


def write_png(path, width=200, height=100):
    from PIL import Image
    Image.frombytes("RGB", (width, height), os.urandom(width * height * 3)).save(path, "PNG")


def embedded_width(page):
    from PIL import Image
    m = re.search(r'<img src="data:image/(?:png|jpeg);base64,([^"]+)"', page)
    assert m, "no embedded image in the page"
    return Image.open(io.BytesIO(base64.b64decode(m.group(1)))).width


# ── --share: the share copy ─────────────────────────────────────────────────

@pytest.fixture
def shared(work, sheaf):
    doc = commented_doc(work)
    before = doc.read_bytes()
    r = sheaf(doc, "--share")
    return types.SimpleNamespace(doc=doc, before=before, ran=r, out=work / "doc-share.html")


def test_share_exits_0_and_writes_stem_share_html_next_to_the_md(shared):
    assert shared.ran.code == 0, shared.ran.err
    assert shared.out.is_file()


def test_share_prints_a_line_naming_the_written_file_and_its_size(shared):
    lines = [l for l in shared.ran.out.splitlines() if l.startswith("  = ")]
    assert lines == [f"  = {shared.out}  ({shared.out.stat().st_size // 1024} KB)"]


def test_share_file_is_one_html_document_that_starts_with_the_doctype(shared):
    text = shared.out.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    assert text.rstrip().endswith("</html>")


def test_share_file_contains_the_documents_text(shared):
    text = shared.out.read_text(encoding="utf-8")
    assert DOC_TEXT in text
    assert "A closing paragraph about the quay." in text
    assert "<title>Harbour plan</title>" in text


def test_share_file_holds_none_of_the_documents_html_comments(shared):
    data = shared.out.read_bytes()
    assert SECRET_ONE.encode() not in data       # a plain HTML comment
    assert SECRET_TWO.encode() not in data       # the body of a review comment
    assert b"sheaf-comment" not in data
    assert b"<!--" not in data


def test_share_says_on_stdout_for_each_comment_that_it_was_removed(shared):
    removed = [l for l in shared.ran.out.splitlines() if l.startswith("  - ")]
    assert len(removed) == 2
    assert all("internal note removed" in l for l in removed)


def test_share_file_has_no_script(shared):
    assert not re.search(rb"<script", shared.out.read_bytes(), re.I)


def test_share_leaves_the_md_byte_for_byte_unchanged(shared):
    assert shared.doc.read_bytes() == shared.before


def test_share_writes_nothing_else_next_to_the_md(shared, work):
    assert names_in(work) == ["doc-share.html", "doc.md"]


def test_share_is_quiet_on_stderr_for_a_clean_document(shared):
    assert shared.ran.err == ""


def test_share_twice_writes_the_same_bytes(shared, sheaf, work):
    first = shared.out.read_bytes()
    assert sheaf(shared.doc, "--share").code == 0
    assert shared.out.read_bytes() == first


def test_share_file_has_the_permissions_of_a_new_file_not_a_private_temp_file(shared):
    umask = os.umask(0)
    os.umask(umask)
    assert shared.out.stat().st_mode & 0o777 == 0o666 & ~umask


def test_share_file_says_nothing_of_the_brand(shared, tmp_path):
    assert brand_words_in(shared.out.read_text(encoding="utf-8"), tmp_path) == []


# ── --out ───────────────────────────────────────────────────────────────────

def test_out_writes_there_and_writes_no_default_file(work, sheaf):
    doc = commented_doc(work)
    target = work / "elsewhere.html"
    r = sheaf(doc, "--share", "--out", target)
    assert r.code == 0, r.err
    assert target.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert not (work / "doc-share.html").exists()
    assert f"  = {target}" in r.out


def test_out_into_a_folder_that_does_not_exist_yet_makes_the_folder(work, sheaf, tmp_path):
    doc = commented_doc(work)
    target = tmp_path / "new" / "deeper" / "page.html"
    r = sheaf(doc, "--share", "--out", target)
    assert r.code == 0, r.err
    assert target.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert not (work / "doc-share.html").exists()


@pytest.mark.parametrize("spelling", ["doc.md", "./doc.md", "sub/../doc.md", "ABSOLUTE"])
def test_out_naming_the_md_itself_exits_2_and_leaves_it_unchanged(work, sheaf, monkeypatch, spelling):
    monkeypatch.chdir(work)
    (work / "sub").mkdir()
    doc = commented_doc(work)
    before = doc.read_bytes()
    out = str(doc) if spelling == "ABSOLUTE" else spelling
    r = sheaf("doc.md", "--share", "--out", out)
    assert r.code == 2
    assert "the document itself" in r.err
    assert str(Path(out)) in r.err                         # named as the person wrote it
    assert doc.read_bytes() == before
    assert names_in(work) == ["doc.md", "sub"]            # no share copy, no temp file


def test_out_naming_a_symlink_to_the_md_exits_2_and_leaves_it_unchanged(work, sheaf):
    doc = commented_doc(work)
    before = doc.read_bytes()
    link = work / "link.md"
    link.symlink_to(doc)
    r = sheaf(doc, "--share", "--out", link)
    assert r.code == 2
    assert link.is_symlink() and not doc.is_symlink()
    assert doc.read_bytes() == before
    assert names_in(work) == ["doc.md", "link.md"]


def test_out_naming_the_md_when_the_md_is_given_as_a_symlink_exits_2(work, sheaf):
    doc = commented_doc(work)
    before = doc.read_bytes()
    link = work / "link.md"
    link.symlink_to(doc)
    r = sheaf(link, "--share", "--out", doc)
    assert r.code == 2
    assert doc.read_bytes() == before
    assert names_in(work) == ["doc.md", "link.md"]


def test_out_naming_a_hard_link_to_the_md_exits_2_and_leaves_it_unchanged(work, sheaf):
    doc = commented_doc(work)
    before = doc.read_bytes()
    hard = work / "hard.md"
    os.link(doc, hard)
    r = sheaf(doc, "--share", "--out", hard)
    assert r.code == 2
    assert doc.read_bytes() == before and hard.read_bytes() == before


def test_out_naming_an_existing_file_replaces_it_completely(work, sheaf):
    doc = commented_doc(work)
    target = write(work / "old.html", "OLD CONTENT " * 20000)
    r = sheaf(doc, "--share", "--out", target)
    assert r.code == 0, r.err
    new = target.read_text(encoding="utf-8")
    assert new.startswith("<!doctype html>")
    assert "OLD CONTENT" not in new
    fresh = work / "fresh.html"
    assert sheaf(doc, "--share", "--out", fresh).code == 0
    assert target.read_bytes() == fresh.read_bytes()      # the whole new file, nothing left of the old


def test_a_successful_write_leaves_no_temp_file_in_the_folder(work, sheaf):
    doc = commented_doc(work)
    out_dir = work / "out"
    assert sheaf(doc, "--share", "--out", out_dir / "page.html").code == 0
    assert names_in(out_dir) == ["page.html"]
    assert names_in(work) == ["doc.md", "out"]


def test_write_text_atomic_that_fails_keeps_the_old_file_and_leaves_no_temp_file(work, monkeypatch):
    target = write(work / "page.html", "the old page")

    def boom(src, dst):
        raise OSError("disk went away")

    with monkeypatch.context() as m:
        m.setattr("sheafmd.cli.os.replace", boom)
        with pytest.raises(OSError, match="disk went away"):
            write_text_atomic(target, "the new page")
    assert target.read_text(encoding="utf-8") == "the old page"
    assert names_in(work) == ["page.html"]


# ── --pdf, with a real Chrome ───────────────────────────────────────────────

@HAS_CHROME
def test_bare_pdf_writes_stem_share_pdf_next_to_the_md(work, sheaf, short_tmp):
    doc = commented_doc(work)
    r = sheaf(doc, "--share", "--pdf")
    assert r.code == 0, r.err
    pdf_file = work / "doc-share.pdf"
    assert pdf_file.read_bytes().startswith(b"%PDF")
    assert (work / "doc-share.html").is_file()
    assert f"  = {pdf_file}  (" in r.out


@HAS_CHROME
def test_bare_pdf_after_out_names_the_pdf_after_the_out_file(work, sheaf, short_tmp):
    doc = commented_doc(work)
    r = sheaf(doc, "--share", "--out", work / "x" / "y.html", "--pdf")
    assert r.code == 0, r.err
    assert (work / "x" / "y.pdf").read_bytes().startswith(b"%PDF")
    assert (work / "x" / "y.html").is_file()
    assert not (work / "doc-share.pdf").exists() and not (work / "doc-share.html").exists()


@HAS_CHROME
def test_pdf_with_a_path_writes_there(work, sheaf, short_tmp):
    doc = commented_doc(work)
    target = work / "chosen.pdf"
    r = sheaf(doc, "--share", "--pdf", target)
    assert r.code == 0, r.err
    assert target.read_bytes().startswith(b"%PDF")
    assert (work / "doc-share.html").is_file()
    assert not (work / "doc-share.pdf").exists()


@HAS_CHROME
def test_pdf_with_a_relative_path_is_relative_to_where_the_command_runs(work, sheaf, short_tmp, monkeypatch):
    commented_doc(work)
    monkeypatch.chdir(work)
    r = sheaf("doc.md", "--share", "--pdf", "rel.pdf")
    assert r.code == 0, r.err
    assert (work / "rel.pdf").read_bytes().startswith(b"%PDF")


# ── --pdf, without Chrome ───────────────────────────────────────────────────

def test_pdf_without_chrome_exits_1_and_says_what_is_needed(work, sheaf, no_chrome):
    doc = commented_doc(work)
    r = sheaf(doc, "--share", "--pdf")
    assert r.code == 1
    assert NO_CHROME in r.err
    hint = "brew install --cask google-chrome" if sys.platform == "darwin" \
        else "google-chrome-stable comes from Google, for amd64 and arm64"
    assert hint in r.err
    assert not (work / "doc-share.pdf").exists()


def test_pdf_without_chrome_still_writes_the_share_copy_and_says_so(work, sheaf, no_chrome):
    doc = commented_doc(work)
    r = sheaf(doc, "--share", "--pdf")
    assert r.code == 1
    html = work / "doc-share.html"
    assert html.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert f"the share copy is written: {html}" in r.err
    assert f"  = {html}" in r.out


def test_pdf_without_chrome_and_with_out_says_where_the_share_copy_is(work, sheaf, no_chrome):
    doc = commented_doc(work)
    r = sheaf(doc, "--share", "--out", work / "o" / "page.html", "--pdf")
    assert r.code == 1
    assert (work / "o" / "page.html").is_file()
    assert f"the share copy is written: {work / 'o' / 'page.html'}" in r.err


def test_pdf_naming_an_existing_folder_exits_1_with_the_pdf_not_written_lines(work, sheaf, monkeypatch):
    chrome = write(work / "fake-chrome", '#!/bin/sh\nfor a in "$@"; do case "$a" in --print-to-pdf=*) '
                   'printf "%%PDF-new" > "${a#--print-to-pdf=}";; esac; done\n')
    chrome.chmod(0o755)
    monkeypatch.setattr("sheafmd.pdf.find_chrome", lambda: str(chrome))
    doc = write(work / "doc.md", "# T\n\ntext\n")
    folder = work / "taken"
    folder.mkdir()
    r = sheaf(doc, "--share", "--pdf", folder)
    assert r.code == 1
    assert "PDF not written" in r.err and str(folder) in r.err and "Traceback" not in r.err
    assert f"the share copy is written: {work / 'doc-share.html'}" in r.err
    assert (work / "doc-share.html").exists() and names_in(folder) == []


def test_pdf_naming_the_md_exits_2_and_leaves_the_md_unchanged(work, sheaf):
    doc = commented_doc(work)
    before = doc.read_bytes()
    r = sheaf(doc, "--share", "--pdf", doc)
    assert r.code == 2
    assert doc.read_bytes() == before
    assert names_in(work) == ["doc.md"]


def test_pdf_naming_the_share_copy_exits_2_and_writes_nothing(work, sheaf):
    doc = commented_doc(work)
    same = work / "page.html"
    r = sheaf(doc, "--share", "--out", same, "--pdf", same)
    assert r.code == 2
    assert names_in(work) == ["doc.md"]


# ── --open ──────────────────────────────────────────────────────────────────

def test_open_calls_the_browser_once_with_the_file_uri_of_the_written_file(work, sheaf, browser):
    doc = commented_doc(work)
    r = sheaf(doc, "--share", "--open")
    assert r.code == 0, r.err
    out = work / "doc-share.html"
    assert browser.calls == [out.resolve().as_uri()]
    assert browser.calls[0].startswith("file://")


def test_open_with_out_opens_the_out_file(work, sheaf, browser, tmp_path):
    doc = commented_doc(work)
    target = tmp_path / "elsewhere" / "page.html"
    assert sheaf(doc, "--share", "--out", target, "--open").code == 0
    assert browser.calls == [target.resolve().as_uri()]


def test_without_open_the_browser_is_never_called(work, sheaf, browser):
    doc = commented_doc(work)
    assert sheaf(doc, "--share").code == 0
    assert sheaf(doc, "--share", "--no-browser").code == 0
    assert browser.calls == []


def test_open_with_no_browser_does_not_open_and_says_why(work, sheaf, browser):
    doc = commented_doc(work)
    r = sheaf(doc, "--share", "--open", "--no-browser")
    assert r.code == 0, r.err
    assert browser.calls == []
    assert "not opened" in r.out and "--no-browser" in r.out
    assert (work / "doc-share.html").is_file()


def test_open_with_the_environment_switch_does_not_open_and_says_why(work, sheaf, browser, monkeypatch):
    monkeypatch.setenv("SHEAF_NO_BROWSER", "1")
    doc = commented_doc(work)
    r = sheaf(doc, "--share", "--open")
    assert r.code == 0, r.err
    assert browser.calls == []
    assert "not opened" in r.out and "SHEAF_NO_BROWSER" in r.out


def test_open_with_browser_false_in_config_does_not_open_and_says_why(work, sheaf, browser):
    write(Path(os.environ["SHEAF_HOME"]) / "config.toml", "browser = false\n")
    doc = commented_doc(work)
    r = sheaf(doc, "--share", "--open")
    assert r.code == 0, r.err
    assert browser.calls == []
    assert "not opened" in r.out and "config.toml" in r.out


def test_open_that_finds_no_browser_warns_on_stderr_and_still_exits_0(work, sheaf, browser):
    browser.result = False
    doc = commented_doc(work)
    r = sheaf(doc, "--share", "--open")
    assert r.code == 0
    bang = [l for l in r.err.splitlines() if l.startswith("  !")]
    assert len(bang) == 1
    assert str(work / "doc-share.html") in bang[0]
    assert (work / "doc-share.html").is_file()


# ── render options reach the page ───────────────────────────────────────────

def test_title_option_sets_the_page_title(work, sheaf):
    assert "<title>X</title>" in share_page(work, sheaf, "# Heading\n\ntext\n", "--title", "X")


def test_title_option_is_escaped(work, sheaf):
    assert "<title>A &amp; B &lt;c&gt;</title>" in share_page(
        work, sheaf, "# Heading\n\ntext\n", "--title", "A & B <c>")


def test_title_without_the_option_is_the_first_heading(work, sheaf):
    assert "<title>Harbour plan</title>" in share_page(work, sheaf, "# Harbour plan\n\ntext\n")


def test_title_without_a_heading_is_the_file_stem_with_dashes_as_spaces(work, sheaf):
    page = share_page(work, sheaf, "just text\n", name="my-quay-notes.md")
    assert "<title>my quay notes</title>" in page


def test_toc_always_gives_a_contents_nav_for_a_one_heading_document(work, sheaf):
    assert '<nav id="toc">' in share_page(work, sheaf, "# Only heading\n\ntext\n", "--toc", "always")


def test_toc_never_gives_none_for_a_seven_heading_document(work, sheaf):
    assert '<nav id="toc">' not in share_page(work, sheaf, headings(7), "--toc", "never")


def test_toc_auto_shows_from_six_headings(work, sheaf):
    assert '<nav id="toc">' in share_page(work, sheaf, headings(6), "--toc", "auto", name="six.md")
    assert '<nav id="toc">' not in share_page(work, sheaf, headings(5), name="five.md")


def test_toc_that_is_not_a_choice_exits_2(work, sheaf):
    doc = write(work / "doc.md", "# T\n\ntext\n")
    r = sheaf(doc, "--share", "--toc", "bogus")
    assert r.code == 2
    assert "bogus" in r.err
    assert names_in(work) == ["doc.md"]


def test_by_option_sets_the_byline(work, sheaf):
    page = share_page(work, sheaf, "# T\n\ntext\n", "--by", "Grace")
    assert "Document prepared by Grace</p>" in page


def test_by_without_the_option_is_the_users_name(work, sheaf):
    page = share_page(work, sheaf, "# T\n\ntext\n")
    assert "Document prepared by Ada</p>" in page


def test_no_for_is_shown_without_a_root_config(work, sheaf):
    page = share_page(work, sheaf, "# T\n\ntext\n", "--by", "Grace")
    assert "Document prepared by Grace</p>" in page
    assert "Grace for" not in page


def test_for_in_the_root_config_is_in_the_byline(work, sheaf):
    write(work / ".sheaf.toml", 'for = "Acme"\n')
    page = share_page(work, sheaf, "# T\n\ntext\n", "--by", "Grace")
    assert "Document prepared by Grace for Acme</p>" in page


def test_for_option_sets_the_for_of_the_byline(work, sheaf):
    page = share_page(work, sheaf, "# T\n\ntext\n", "--by", "Grace", "--for", "Globex")
    assert "Document prepared by Grace for Globex</p>" in page


def test_for_option_overrides_the_for_of_the_root_config(work, sheaf):
    write(work / ".sheaf.toml", 'for = "Acme"\n')
    page = share_page(work, sheaf, "# T\n\ntext\n", "--by", "Grace", "--for", "Globex")
    assert "Document prepared by Grace for Globex</p>" in page and "Acme" not in page


def test_an_empty_for_option_leaves_the_for_of_the_root_config_out(work, sheaf):
    write(work / ".sheaf.toml", 'for = "Acme"\n')
    page = share_page(work, sheaf, "# T\n\ntext\n", "--by", "Grace", "--for", "")
    assert "Document prepared by Grace</p>" in page and "Acme" not in page


def test_the_pdf_is_printed_from_the_page_that_has_the_for(work, sheaf, monkeypatch):
    printed = {}

    def fake(html, out):
        printed["html"] = html
        Path(out).write_bytes(b"%PDF-fake")
    monkeypatch.setattr("sheafmd.pdf.write_pdf", fake)
    write(work / ".sheaf.toml", 'for = "Acme"\n')
    doc = write(work / "doc.md", "# T\n\ntext\n")
    r = sheaf(doc, "--share", "--pdf", "--by", "Grace", "--for", "Globex")
    assert r.code == 0, r.err
    assert "Document prepared by Grace for Globex</p>" in printed["html"]


def test_credit_is_off_by_default(work, sheaf):
    assert CREDIT not in share_page(work, sheaf, "# T\n\ntext\n")


def test_credit_true_in_the_root_config_adds_the_credit_line(work, sheaf):
    write(work / ".sheaf.toml", "credit = true\n")
    page = share_page(work, sheaf, "# T\n\ntext\n")
    assert page.count(CREDIT) == 1


def test_credit_option_adds_the_credit_line_without_the_file(work, sheaf):
    assert share_page(work, sheaf, "# T\n\ntext\n", "--credit").count(CREDIT) == 1


def test_max_image_width_downscales_a_wider_image(work, sheaf):
    write_png(work / "fig.png", 200, 100)
    page = share_page(work, sheaf, "# T\n\n![A figure](fig.png)\n", "--max-image-width", "50")
    assert embedded_width(page) == 50


def test_image_narrower_than_the_limit_keeps_its_width(work, sheaf):
    write_png(work / "fig.png", 200, 100)
    assert embedded_width(share_page(work, sheaf, "# T\n\n![A figure](fig.png)\n")) == 200


def test_max_image_width_logs_the_downscale(work, sheaf):
    write_png(work / "fig.png", 200, 100)
    doc = write(work / "doc.md", "# T\n\n![A figure](fig.png)\n")
    r = sheaf(doc, "--share", "--max-image-width", "50")
    assert "downscaled 200px -> 50px" in r.out


@pytest.mark.parametrize("bad", ["0", "abc", "-5", "1.5"])
def test_max_image_width_that_is_not_a_whole_number_above_zero_exits_2(work, sheaf, bad):
    doc = write(work / "doc.md", "# T\n\ntext\n")
    r = sheaf(doc, "--share", "--max-image-width", bad)
    assert r.code == 2
    assert "--max-image-width" in r.err
    assert names_in(work) == ["doc.md"]


# ── --theme ─────────────────────────────────────────────────────────────────

WORDMARK = '<p class="doc-mark"><b>Acme Co</b>'


def make_theme(folder, wordmark="Acme Co"):
    write(Path(folder) / "theme.toml", f'name = "brand"\nwordmark = "{wordmark}"\n')
    return Path(folder)


def test_theme_with_a_relative_folder_is_looked_up_where_the_command_runs(work, sheaf, tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    make_theme(cwd / "brand")
    doc = write(work / "doc.md", "# T\n\ntext\n")           # the document is elsewhere: its root has no "brand"
    monkeypatch.chdir(cwd)
    r = sheaf(doc, "--share", "--theme", "brand")
    assert r.code == 0, r.err
    assert WORDMARK in (work / "doc-share.html").read_text(encoding="utf-8")


def test_theme_with_an_absolute_folder_loads(work, sheaf, tmp_path):
    make_theme(tmp_path / "abs-brand")
    assert WORDMARK in share_page(work, sheaf, "# T\n\ntext\n", "--theme", tmp_path / "abs-brand")


def test_theme_folder_in_the_current_directory_wins_over_the_same_name_in_the_root(
        work, sheaf, tmp_path, monkeypatch):
    make_theme(work / "brand", "From Root")
    make_theme(tmp_path / "cwd" / "brand", "Acme Co")
    monkeypatch.chdir(tmp_path / "cwd")
    page = share_page(work, sheaf, "# T\n\ntext\n", "--theme", "brand")
    assert WORDMARK in page and "From Root" not in page


def test_theme_name_of_a_built_in_stays_a_name_even_when_a_folder_has_it(work, sheaf, tmp_path, monkeypatch):
    make_theme(tmp_path / "cwd" / "plain", "Imposter")
    monkeypatch.chdir(tmp_path / "cwd")
    page = share_page(work, sheaf, "# T\n\ntext\n", "--theme", "plain")
    assert "Imposter" not in page and 'class="doc-mark"' not in page.split("</style>")[1]


def test_theme_in_the_root_config_applies_and_the_option_overrides_it(work, sheaf):
    make_theme(work / "brand")
    write(work / ".sheaf.toml", 'theme = "brand"\n')
    assert WORDMARK in share_page(work, sheaf, "# T\n\ntext\n", name="a.md")
    plain = share_page(work, sheaf, "# T\n\ntext\n", "--theme", "plain", name="b.md")
    assert "Acme Co" not in plain


def test_theme_that_does_not_exist_exits_1_names_it_and_writes_nothing(work, sheaf):
    doc = write(work / "doc.md", "# T\n\ntext\n")
    r = sheaf(doc, "--share", "--theme", "nonexistent")
    assert r.code == 1
    assert "nonexistent" in r.err
    assert names_in(work) == ["doc.md"]


def test_theme_behind_a_folder_that_may_not_be_entered_is_refused_with_the_folder_and_the_reason(
        work, sheaf, tmp_path, closed):
    """Python 3.14's `is_dir` says False there: "there is no folder at", for a folder that is there."""
    brand = make_theme(tmp_path / "srv" / "brand")
    closed(tmp_path / "srv")
    doc = write(work / "doc.md", "# T\n\ntext\n")
    r = sheaf(doc, "--share", "--theme", brand)
    assert r.code == 1 and "Traceback" not in r.err
    assert f"the folder {brand} cannot be entered: Permission denied" in r.err
    assert names_in(work) == ["doc.md"]


def test_a_relative_theme_whose_folder_may_not_be_entered_is_not_looked_for_in_the_root(
        work, sheaf, tmp_path, monkeypatch, closed):
    """The theme is looked up where the command runs; one that cannot be looked at there is refused,
    and never taken from the document's root, which has a theme by the same path."""
    make_theme(work / "closed" / "brand", "From Root")
    cwd = tmp_path / "cwd"
    make_theme(cwd / "closed" / "brand")
    closed(cwd / "closed")
    monkeypatch.chdir(cwd)
    doc = write(work / "doc.md", "# T\n\ntext\n")
    r = sheaf(doc, "--share", "--theme", "closed/brand")
    assert r.code == 1 and "Traceback" not in r.err
    assert f"the folder {cwd / 'closed' / 'brand'} cannot be entered: Permission denied" in r.err
    assert not (work / "doc-share.html").exists()


# ── errors ──────────────────────────────────────────────────────────────────

def test_a_missing_file_exits_1_and_names_it(work, sheaf, monkeypatch):
    monkeypatch.chdir(work)
    r = sheaf("nothere.md", "--share")
    assert r.code == 1
    assert "nothere.md" in r.err
    assert names_in(work) == []


def test_an_unclosed_comment_exits_1_names_the_document_and_the_line_and_writes_no_share_copy(work, sheaf):
    doc = write(work / "doc.md", "# T\n\nFine.\n\n<!-- never closed\n\nmore text\n")
    r = sheaf(doc, "--share")
    assert r.code == 1
    assert str(doc) in r.err
    assert "line 5" in r.err
    assert names_in(work) == ["doc.md"]                    # no share copy, no temp file


def test_an_unclosed_comment_is_reported_at_its_line_in_the_document_as_written(work, sheaf):
    # A closed two-line comment above it is removed from the source before the check, and
    # must not move the number: the person looks the line up in their own file.
    doc = write(work / "doc.md", "# T\n\n<!-- a closed\nnote -->\n\nFine text.\n\n<!-- never closed\n\nmore\n")
    r = sheaf(doc, "--share")
    assert r.code == 1
    assert "line 8" in r.err


def test_a_reviewers_comment_that_lost_its_closing_arrow_exits_1_and_writes_no_share_copy(work, sheaf):
    doc = write(work / "doc.md", "# T\n\nThe budget is fine.<!-- sheaf-comment id=c1 by=\"Ada\" "
                "at=2026-10-14T10:00 status=open quote=\"budget\"\nInternal: ZQ-LOST.\n\nNext.\n")
    old = write(work / "doc-share.html", "OLD SHARE COPY")
    r = sheaf(doc, "--share")
    assert r.code == 1
    assert str(doc) in r.err and "line 3" in r.err and "Close it" in r.err and "delete the comment" in r.err
    assert "ZQ-LOST" not in r.err and "ZQ-LOST" not in r.out
    assert old.read_text(encoding="utf-8") == "OLD SHARE COPY"
    assert names_in(work) == ["doc-share.html", "doc.md"]


def test_an_unclosed_comment_leaves_an_older_share_copy_alone(work, sheaf):
    doc = write(work / "doc.md", "# T\n\n<!-- never closed\n")
    old = write(work / "doc-share.html", "OLD SHARE COPY")
    assert sheaf(doc, "--share").code == 1
    assert old.read_text(encoding="utf-8") == "OLD SHARE COPY"


def test_a_toml_error_in_the_root_config_exits_1_and_names_the_file(work, sheaf):
    write(work / ".sheaf.toml", "for = \n")
    doc = write(work / "doc.md", "# T\n\ntext\n")
    r = sheaf(doc, "--share")
    assert r.code == 1
    assert str(work / ".sheaf.toml") in r.err
    assert names_in(work) == [".sheaf.toml", "doc.md"]


def test_a_value_of_the_wrong_type_in_the_root_config_exits_1_and_names_the_file(work, sheaf):
    write(work / ".sheaf.toml", 'credit = "yes"\n')
    doc = write(work / "doc.md", "# T\n\ntext\n")
    r = sheaf(doc, "--share")
    assert r.code == 1
    assert str(work / ".sheaf.toml") in r.err and "credit" in r.err


def test_an_unknown_key_in_the_root_config_is_a_warning_that_names_the_file(work, sheaf):
    write(work / ".sheaf.toml", "bogus = 1\n")
    doc = write(work / "doc.md", "# T\n\ntext\n")
    r = sheaf(doc, "--share")
    assert r.code == 0
    assert "bogus" in r.err and str(work / ".sheaf.toml") in r.err
    assert (work / "doc-share.html").is_file()


def test_an_out_that_cannot_be_written_exits_1_with_a_message_naming_it(work, sheaf):
    doc = write(work / "doc.md", "# T\n\ntext\n")
    blocker = write(work / "blocker", "a regular file")
    r = sheaf(doc, "--share", "--out", blocker / "x.html")
    assert r.code == 1
    assert str(blocker) in r.err
    assert "Traceback" not in r.err


def test_a_document_that_is_not_utf8_exits_1_and_names_it(work, sheaf):
    doc = work / "doc.md"
    doc.write_bytes(b"\xff\xfe not text\n")
    r = sheaf(doc, "--share")
    assert r.code == 1
    assert "doc.md" in r.err
    assert "Traceback" not in r.err
    assert names_in(work) == ["doc.md"]


def test_an_out_that_is_an_existing_folder_exits_1_and_names_it_and_leaves_no_temp_file(work, sheaf):
    doc = write(work / "doc.md", "# T\n\ntext\n")
    folder = work / "taken"
    folder.mkdir()
    r = sheaf(doc, "--share", "--out", folder)
    assert r.code == 1
    assert str(folder) in r.err
    assert names_in(folder) == []
    assert names_in(work) == ["doc.md", "taken"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_an_out_in_a_folder_that_cannot_be_written_exits_1_and_names_it(work, sheaf):
    doc = write(work / "doc.md", "# T\n\ntext\n")
    locked = work / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        r = sheaf(doc, "--share", "--out", locked / "x.html")
    finally:
        locked.chmod(0o700)
    assert r.code == 1
    assert str(locked) in r.err
    assert names_in(locked) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read anything")
def test_a_document_that_cannot_be_read_exits_1_and_names_it(work, sheaf):
    doc = write(work / "doc.md", "# T\n\ntext\n")
    doc.chmod(0)
    try:
        r = sheaf(doc, "--share")
    finally:
        doc.chmod(0o600)
    assert r.code == 1
    assert "doc.md" in r.err
    assert "Traceback" not in r.err
    assert names_in(work) == ["doc.md"]


# ── warnings: the link rule ─────────────────────────────────────────────────

def test_a_bare_host_in_prose_warns_on_stderr_not_stdout_and_still_exits_0(work, sheaf):
    doc = write(work / "doc.md", "# T\n\nSee example.com/pricing for the plans.\n")
    r = sheaf(doc, "--share")
    assert r.code == 0
    assert "named in the text without a link" in r.err
    assert "example.com/pricing" in r.err
    assert "named in the text without a link" not in r.out
    assert (work / "doc-share.html").is_file()


def test_a_markdown_link_to_the_host_gives_no_warning(work, sheaf):
    doc = write(work / "doc.md", "# T\n\nSee [the plans](https://example.com/pricing).\n")
    r = sheaf(doc, "--share")
    assert r.code == 0
    assert r.err == ""


def test_links_false_in_the_root_config_turns_the_warning_off(work, sheaf):
    write(work / ".sheaf.toml", "links = false\n")
    doc = write(work / "doc.md", "# T\n\nSee example.com/pricing for the plans.\n")
    r = sheaf(doc, "--share")
    assert r.code == 0
    assert r.err == ""


def test_link_tlds_in_the_root_config_add_endings_to_the_rule(work, sheaf):
    write(work / ".sheaf.toml", 'link_tlds = ["studio"]\n')
    doc = write(work / "doc.md", "# T\n\nSee example.studio/work for the plans.\n")
    r = sheaf(doc, "--share")
    assert r.code == 0
    assert "example.studio/work" in r.err


# ── usage ───────────────────────────────────────────────────────────────────

def test_no_arguments_exits_2_and_prints_the_usage_on_stderr(sheaf):
    r = sheaf()
    assert r.code == 2
    assert "usage:" in r.err and "sheaf FILE.md --share" in r.err
    assert r.out == ""


@pytest.mark.parametrize("word", ["--help", "-h", "help"])
def test_help_exits_0_and_prints_the_usage_on_stdout(sheaf, word):
    r = sheaf(word)
    assert r.code == 0
    assert "usage:" in r.out and "--share" in r.out and "Exit codes: 0 done, 1 failed, 2 usage error." in r.out
    assert r.err == ""


def test_help_after_a_file_exits_0_and_describes_the_options(work, sheaf):
    doc = write(work / "doc.md", "# T\n")
    r = sheaf(doc, "--help")
    assert r.code == 0
    for flag in ("--share", "--out", "--pdf", "--open", "--no-browser", "--title", "--toc",
                 "--max-image-width", "--by", "--for", "--theme", "--credit"):
        assert flag in r.out, flag
    assert names_in(work) == ["doc.md"]


def test_an_unknown_word_exits_2_and_names_it(sheaf):
    r = sheaf("bogus")
    assert r.code == 2
    assert "'bogus'" in r.err
    assert "commands: open, start, stop, status, hub, comments, comment, reply, resolve, reopen, diag, version" in r.err


def test_an_option_in_the_place_of_the_file_exits_2(work, sheaf):
    r = sheaf("--share")
    assert r.code == 2
    assert "--share" in r.err


def test_an_unknown_option_exits_2_and_writes_nothing(work, sheaf):
    doc = write(work / "doc.md", "# T\n")
    r = sheaf(doc, "--share", "--bogus")
    assert r.code == 2
    assert "--bogus" in r.err
    assert names_in(work) == ["doc.md"]


@pytest.mark.parametrize("extra", [("--out", "x"), ("--pdf",), ("--open",), ("--pdf", "x.pdf")])
def test_out_pdf_and_open_without_share_exit_2_and_write_nothing(work, sheaf, browser, extra):
    doc = write(work / "doc.md", "# T\n")
    r = sheaf(doc, *extra)
    assert r.code == 2
    assert "--share" in r.err
    assert names_in(work) == ["doc.md"]
    assert browser.calls == []


# ── the first argument ──────────────────────────────────────────────────────

def test_an_existing_first_argument_that_does_not_end_in_md_is_a_file(work, sheaf, monkeypatch):
    monkeypatch.chdir(work)
    write(work / "notes.txt", "Plain notes about the quay.\n")
    r = sheaf("notes.txt", "--share")
    assert r.code == 0, r.err
    assert "Plain notes about the quay." in (work / "notes-share.html").read_text(encoding="utf-8")


def test_a_first_argument_that_does_not_exist_and_does_not_end_in_md_is_a_command_word(work, sheaf, monkeypatch):
    monkeypatch.chdir(work)
    r = sheaf("notes.txt", "--share")
    assert r.code == 2
    assert "'notes.txt'" in r.err and "neither a .md file nor a command" in r.err


def test_a_first_argument_that_ends_in_md_is_a_file_even_when_it_does_not_exist(work, sheaf, monkeypatch):
    monkeypatch.chdir(work)
    r = sheaf("later.md", "--share")
    assert r.code == 1
    assert "later.md" in r.err and "no such file" in r.err


def test_a_folder_as_the_first_argument_is_a_file_that_is_not_one(work, sheaf, monkeypatch):
    monkeypatch.chdir(work)
    (work / "adir").mkdir()
    r = sheaf("adir", "--share")
    assert r.code == 1
    assert "adir" in r.err and "no such file" in r.err


# ── nothing says the brand ──────────────────────────────────────────────────

def _scn_no_arguments(work, mp):
    return []


def _scn_help(work, mp):
    return ["--help"]


def _scn_help_word(work, mp):
    return ["help"]


def _scn_file_help(work, mp):
    return [commented_doc(work), "--help"]


def _scn_share(work, mp):
    return [commented_doc(work), "--share"]


def _scn_share_with_warning(work, mp):
    return [write(work / "w.md", "# T\n\nSee example.com/pricing.\n"), "--share"]


def _scn_share_open_no_browser(work, mp):
    return [commented_doc(work), "--share", "--open", "--no-browser"]


def _scn_share_pdf_without_chrome(work, mp):
    mp.setattr("sheafmd.pdf.find_chrome", lambda: None)
    return [commented_doc(work), "--share", "--pdf"]


def _scn_missing_file(work, mp):
    return [work / "nothere.md", "--share"]


def _scn_unclosed_comment(work, mp):
    return [write(work / "u.md", "# T\n\n<!-- never closed\n"), "--share"]


def _scn_toml_error(work, mp):
    write(work / ".sheaf.toml", "for = \n")
    return [commented_doc(work), "--share"]


def _scn_unknown_key(work, mp):
    write(work / ".sheaf.toml", "bogus = 1\n")
    return [commented_doc(work), "--share"]


def _scn_missing_theme(work, mp):
    return [commented_doc(work), "--share", "--theme", "nonexistent"]


def _scn_bad_toc(work, mp):
    return [commented_doc(work), "--share", "--toc", "bogus"]


def _scn_bad_width(work, mp):
    return [commented_doc(work), "--share", "--max-image-width", "abc"]


def _scn_no_share(work, mp):
    return [commented_doc(work)]


def _scn_out_without_share(work, mp):
    return [commented_doc(work), "--out", "x"]


def _scn_out_is_the_document(work, mp):
    doc = commented_doc(work)
    return [doc, "--share", "--out", doc]


def _scn_unknown_word(work, mp):
    return ["bogus"]


SCENARIOS = {name[5:]: fn for name, fn in sorted(globals().items()) if name.startswith("_scn_")}
# Every other command's --help (tests/test_cli_comments.py and test_cli_diag.py check what
# those commands print when they run).
for _cmd in ("comments", "comment", "reply", "resolve", "reopen", "diag", "version", "token", "mcp", "init"):
    SCENARIOS[f"{_cmd}_help"] = lambda work, mp, _cmd=_cmd: [_cmd, "--help"]
SCENARIOS["diag_note_help"] = lambda work, mp: ["diag", "note", "--help"]
SCENARIOS["token_add_help"] = lambda work, mp: ["token", "add", "--help"]


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_nothing_says_the_brand_in_what_the_command_prints(scenario, work, sheaf, tmp_path, monkeypatch):
    argv = SCENARIOS[scenario](work, monkeypatch)
    r = sheaf(*argv)
    text = r.out + r.err
    assert text.strip(), "the scenario printed nothing, so the check proves nothing"
    assert brand_words_in(text, tmp_path) == []


# ── the command as a real process ───────────────────────────────────────────

def test_module_run_writes_the_share_copy_and_exits_0(work):
    commented_doc(work)
    p = run_module("doc.md", "--share", cwd=work)
    assert p.returncode == 0, p.stderr
    out = work / "doc-share.html"
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert "  = doc-share.html  (" in p.stdout
    assert SECRET_ONE.encode() not in out.read_bytes()


def test_module_run_without_arguments_exits_2_with_the_usage_on_stderr(work):
    p = run_module(cwd=work)
    assert p.returncode == 2
    assert "usage:" in p.stderr and p.stdout == ""


def test_module_run_help_exits_0_with_the_usage_on_stdout(work):
    p = run_module("--help", cwd=work)
    assert p.returncode == 0
    assert "usage:" in p.stdout and p.stderr == ""


def test_module_run_with_a_missing_file_exits_1_and_names_it(work):
    p = run_module("nothere.md", "--share", cwd=work)
    assert p.returncode == 1
    assert "nothere.md" in p.stderr and p.stdout == ""


def test_module_run_with_an_out_that_cannot_be_written_exits_1_without_a_traceback(work):
    write(work / "doc.md", "# T\n\ntext\n")
    blocker = write(work / "blocker", "a regular file")
    p = run_module("doc.md", "--share", "--out", blocker / "x.html", cwd=work)
    assert p.returncode == 1
    assert "blocker" in p.stderr
    assert "Traceback" not in p.stderr


def test_module_run_with_a_document_that_is_not_utf8_exits_1_without_a_traceback(work):
    (work / "doc.md").write_bytes(b"\xff\xfe not text\n")
    p = run_module("doc.md", "--share", cwd=work)
    assert p.returncode == 1
    assert "doc.md" in p.stderr
    assert "Traceback" not in p.stderr


def test_module_run_with_an_unknown_word_exits_2(work):
    p = run_module("bogus", cwd=work)
    assert p.returncode == 2
    assert "'bogus'" in p.stderr


def test_module_run_sends_the_link_warning_to_stderr_through_a_real_pipe(work):
    write(work / "doc.md", "# T\n\nSee example.com/pricing for the plans.\n")
    p = run_module("doc.md", "--share", cwd=work)
    assert p.returncode == 0
    assert "named in the text without a link" in p.stderr
    assert "named in the text without a link" not in p.stdout
    assert "  = doc-share.html" in p.stdout


def test_module_run_with_an_unclosed_comment_exits_1_and_writes_no_file(work):
    write(work / "doc.md", "# T\n\n<!-- never closed\n")
    p = run_module("doc.md", "--share", cwd=work)
    assert p.returncode == 1
    assert "doc.md" in p.stderr and "line 3" in p.stderr
    assert names_in(work) == ["doc.md"]


def test_module_run_says_nothing_of_the_brand(work, tmp_path):
    commented_doc(work)
    for argv in (["--help"], ["doc.md", "--share"], ["nothere.md", "--share"], ["bogus"], []):
        p = run_module(*argv, cwd=work)
        assert brand_words_in(p.stdout + p.stderr, tmp_path) == [], argv


@HAS_CHROME
def test_module_run_with_pdf_writes_both_files(work, short_tmp):
    commented_doc(work)
    p = run_module("doc.md", "--share", "--pdf", cwd=work)
    assert p.returncode == 0, p.stderr
    assert (work / "doc-share.pdf").read_bytes().startswith(b"%PDF")
    assert (work / "doc-share.html").is_file()
    assert "  = doc-share.pdf  (" in p.stdout


def test_the_sheaf_console_script_is_the_same_command(work):
    script = Path(sys.executable).parent / "sheaf"
    if not script.is_file():
        pytest.skip("the sheaf console script is not installed next to this Python")
    commented_doc(work)
    p = subprocess.run([str(script), "doc.md", "--share"], cwd=work, capture_output=True,
                       text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    assert (work / "doc-share.html").is_file()


@pytest.mark.parametrize("opts", [["--agent", "codex"], ["--agent", "none"], ["--session", "s-1"], ["--browser"],
                                  ["--agent", "none", "--session", "s-1", "--browser", "--no-browser"]])
def test_the_options_of_sheaf_file_that_a_share_copy_has_no_use_for_are_accepted(work, sheaf, browser, opts):
    doc = commented_doc(work)
    r = sheaf(doc, "--share", *opts)
    assert r.code == 0, r.err
    assert (work / "doc-share.html").is_file() and browser.calls == []
