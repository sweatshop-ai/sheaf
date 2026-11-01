"""The library API (SPEC 16): the names `import sheafmd` promises to keep through 1.x.

    sheafmd.render(path, *, share=True, theme=None, title=None, toc="auto",
                   max_image_width=1400, by=None, for_=None, credit=None, log=None) -> str
    sheafmd.write_pdf(html, out)            # raises sheafmd.PdfError
    sheafmd.Source(path).read() / .update(change, expected_hash=None)
    sheafmd.strip_comments(text)
    sheafmd.comments.parse(text)
    sheafmd.load_root_config(root), sheafmd.load_theme(spec, root)

Inside the package `sheafmd.render` is the function, not the module sheafmd/render.py;
this file only ever uses it as the function.
"""
import base64
import hashlib
import inspect
import io
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import pytest
from helpers import write

import sheafmd
from sheafmd import comments, pdf

NO_CHROME = "Chrome or Chromium is needed to write a PDF and neither is installed."
CREDIT = ('<p class="sheaf-credit">Made with '
          '<a href="https://github.com/sweatshop-ai/sheaf">sheaf</a></p>')
HAS_CHROME = pytest.mark.skipif(pdf.find_chrome() is None, reason="Chrome or Chromium not installed")
META_RE = re.compile(r'<script id="rd-edit-meta" type="application/json">(.*?)</script>', re.S)

DOC_TEXT = "The harbour opens in spring."
SECRET_ONE = "secret-one"
SECRET_TWO = "secret-two"


# ── helpers ─────────────────────────────────────────────────────────────────

def commented_doc(work, name="doc.md"):
    """A document with a plain HTML comment and a review comment of each marker."""
    new = comments.Comment(id="c1", by="Grace", at="2026-10-14T10:00", quote="quay",
                           body=f"{SECRET_TWO} body")
    old = comments.Comment(id="c2", by="Ada", at="2026-10-14T10:05", quote="harbour",
                           body="legacy-body", marker="rd-comment")
    text = (f"# Harbour plan\n\n{DOC_TEXT}\n\n<!-- {SECRET_ONE} -->\n\n"
            f"A paragraph about the quay.{comments.format(new, one_line=True)}\n\n"
            f"A paragraph about the harbour.{comments.format(old, one_line=False)}\n")
    assert [c.id for c in comments.parse(text).comments] == ["c1", "c2"]
    return write(Path(work) / name, text)


def meta_of(page):
    m = META_RE.search(page)
    assert m, "the page has no rd-edit-meta block"
    return json.loads(m.group(1))


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


def make_theme(folder, wordmark="Acme Co", extra=""):
    write(Path(folder) / "theme.toml", f'name = "brand"\nwordmark = "{wordmark}"\n{extra}')
    return Path(folder)


MISSING_FONT = '[[font]]\nfamily = "Brand Sans"\nfile = "fonts/missing.woff2"\n'
WARNING = "  ! theme brand: font fonts/missing.woff2 missing, this page is OFF THEME"


# ── the public names ────────────────────────────────────────────────────────

PUBLIC = ["render", "write_pdf", "Source", "strip_comments", "comments", "load_root_config",
          "load_theme", "PdfError", "StaleError", "__version__"]


@pytest.mark.parametrize("name", PUBLIC)
def test_the_public_name_exists(name):
    assert hasattr(sheafmd, name), name


@pytest.mark.parametrize("name", [n for n in PUBLIC if n != "__version__"])
def test_the_public_name_is_listed_in_all(name):
    assert name in sheafmd.__all__


def test_every_name_in_all_exists():
    assert [n for n in sheafmd.__all__ if not hasattr(sheafmd, n)] == []


def test_render_is_the_function_and_not_the_module_of_the_same_name():
    assert inspect.isfunction(sheafmd.render)
    assert not inspect.ismodule(sheafmd.render)


def test_comments_is_the_module_with_parse_and_format():
    assert inspect.ismodule(sheafmd.comments)
    assert callable(sheafmd.comments.parse) and callable(sheafmd.comments.format)


def test_version_is_a_version_string():
    assert re.fullmatch(r"\d+\.\d+\.\d+([.\-+]\w+)*", sheafmd.__version__)


def test_render_takes_exactly_the_arguments_of_the_spec_and_all_but_the_path_by_keyword():
    params = inspect.signature(sheafmd.render).parameters
    assert list(params) == ["path", "share", "theme", "title", "toc", "max_image_width", "by",
                            "for_", "credit", "log"]
    assert params["path"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for n, p in params.items() if n != "path")
    assert {n: p.default for n, p in params.items() if n != "path"} == {
        "share": True, "theme": None, "title": None, "toc": "auto", "max_image_width": 1400,
        "by": None, "for_": None, "credit": None, "log": None}


def test_the_errors_are_exceptions_and_unclosed_comment_is_a_render_error():
    assert issubclass(sheafmd.PdfError, Exception)
    assert issubclass(sheafmd.StaleError, Exception)
    assert issubclass(sheafmd.ConfigError, Exception)
    assert issubclass(sheafmd.UnclosedComment, sheafmd.RenderError)
    assert issubclass(sheafmd.RenderError, Exception)


# ── render: the share copy ──────────────────────────────────────────────────

def test_render_returns_a_share_copy_by_default_with_no_comment_and_no_script(work):
    doc = commented_doc(work)
    page = sheafmd.render(doc)
    assert page.startswith("<!doctype html>")
    assert DOC_TEXT in page
    assert "<!--" not in page
    for secret in (SECRET_ONE, SECRET_TWO, "legacy-body", "sheaf-comment", "rd-comment"):
        assert secret not in page, secret
    assert not re.search(r"<script", page, re.I)


def test_render_accepts_a_string_path_and_a_path_alike(work):
    doc = commented_doc(work)
    assert sheafmd.render(str(doc)) == sheafmd.render(doc)


def test_render_does_not_touch_the_document_or_write_any_file(work):
    doc = commented_doc(work)
    before = doc.read_bytes()
    sheafmd.render(doc)
    sheafmd.render(doc, share=False)
    assert doc.read_bytes() == before
    assert sorted(p.name for p in work.iterdir()) == ["doc.md"]


def test_render_fills_log_with_a_removal_line_for_each_comment(work):
    doc = commented_doc(work)
    log = []
    sheafmd.render(doc, log=log)
    removed = [l for l in log if l.startswith("  - ")]
    assert len(removed) == 3                    # the plain comment and one of each marker
    assert all("internal note removed" in l for l in removed)
    assert any(SECRET_ONE in l for l in removed)


def test_render_returns_the_same_share_copy_with_or_without_a_log(work):
    doc = commented_doc(work)
    assert sheafmd.render(doc, log=[]) == sheafmd.render(doc)


# ── render: the page ────────────────────────────────────────────────────────

def test_render_share_false_returns_the_page_with_the_comment_text_and_the_editor(work):
    doc = commented_doc(work)
    page = sheafmd.render(doc, share=False)
    assert page.startswith("<!doctype html>")
    assert SECRET_ONE in page and SECRET_TWO in page
    assert '<script id="rd-edit-meta" type="application/json">' in page


def test_the_pages_meta_block_names_the_document_and_hashes_its_source(work):
    doc = commented_doc(work)
    meta = meta_of(sheafmd.render(doc, share=False))
    assert meta["name"] == "doc.md"
    assert meta["hash"] == sheafmd.Source(doc).read()[1]
    assert meta["me"] == "Ada"


def test_the_pages_meta_block_says_a_plain_document_is_editable(work):
    doc = write(work / "doc.md", "# T\n\nFirst paragraph.\n\nSecond paragraph.\n")
    meta = meta_of(sheafmd.render(doc, share=False))
    assert meta["edit"] is True
    assert meta["why"] == ""
    assert meta["editable"] and meta["commentable"]


def test_the_pages_meta_block_holds_the_parsed_comments_of_both_markers(work):
    doc = commented_doc(work)
    meta = meta_of(sheafmd.render(doc, share=False))
    parsed = comments.parse(doc.read_text(encoding="utf-8")).comments
    assert meta["comments"] == [c.as_dict() for c in parsed]
    assert [(c["id"], c["by"], c["body"]) for c in meta["comments"]] == [
        ("c1", "Grace", f"{SECRET_TWO} body"), ("c2", "Ada", "legacy-body")]
    assert meta["malformed"] == []


def test_a_closing_script_tag_in_a_comment_body_does_not_end_the_meta_block(work):
    body = "before </script><b>after</b>"
    c = comments.Comment(id="c1", by="Grace", at="2026-10-14T10:00", quote="quay", body=body)
    text = "# T\n\nA paragraph about the quay." + comments.format(c, one_line=True) + "\n"
    doc = write(work / "doc.md", text)
    assert comments.parse(text).comments[0].body == body       # the fixture holds what it says
    page = sheafmd.render(doc, share=False)
    block = META_RE.search(page).group(1)
    assert "</script>" not in block and "<" not in block
    assert json.loads(block)["comments"][0]["body"] == body    # and it reads back whole
    assert "\\u003c/script>" in page
    assert page.count("<script") == page.count("</script>") == 2    # the meta block and the editor


def test_render_share_false_logs_the_edit_mode_line(work):
    doc = write(work / "doc.md", "# T\n\nFirst paragraph.\n")
    log = []
    sheafmd.render(doc, share=False, log=log)
    assert any(l.startswith("  + edit mode") for l in log)


# ── render: the root config, found without being told the root ──────────────

def test_render_reads_for_from_the_root_config(work):
    write(work / ".sheaf.toml", 'for = "Acme"\n')
    doc = write(work / "doc.md", "# T\n\ntext\n")
    assert "Document prepared by Ada for Acme</p>" in sheafmd.render(doc)


def test_render_without_a_root_config_shows_no_for(work):
    doc = write(work / "doc.md", "# T\n\ntext\n")
    assert "Document prepared by Ada</p>" in sheafmd.render(doc)


def test_render_reads_credit_from_the_root_config(work):
    write(work / ".sheaf.toml", "credit = true\n")
    doc = write(work / "doc.md", "# T\n\ntext\n")
    assert sheafmd.render(doc).count(CREDIT) == 1


def test_render_has_no_credit_by_default(work):
    doc = write(work / "doc.md", "# T\n\ntext\n")
    assert CREDIT not in sheafmd.render(doc)


def test_render_reads_a_theme_given_as_a_folder_relative_to_the_root(work, tmp_path, monkeypatch):
    make_theme(work / "brand")
    write(work / ".sheaf.toml", 'theme = "brand"\n')
    doc = write(work / "doc.md", "# T\n\ntext\n")
    monkeypatch.chdir(tmp_path)                       # not the root: the folder is looked up in the root
    assert '<p class="doc-mark"><b>Acme Co</b>' in sheafmd.render(doc)


def test_render_reads_links_from_the_root_config(work):
    doc = write(work / "doc.md", "# T\n\ntext\n")
    write(work / ".sheaf.toml", "links = false\n")
    assert "<title>T</title>" in sheafmd.render(doc)           # accepted
    write(work / ".sheaf.toml", 'links = "no"\n')
    with pytest.raises(sheafmd.ConfigError, match="links"):     # and it is the file that is read
        sheafmd.render(doc)


def test_render_gives_no_link_warning_because_the_link_rule_is_for_command_line_renders(work):
    # SPEC 6.2 step 9: "The link rule check (section 6.6), CLI renders only."
    doc = write(work / "doc.md", "# T\n\nSee example.com/pricing for the plans.\n")
    log = []
    sheafmd.render(doc, log=log)
    assert [l for l in log if l.startswith("  !")] == []


def test_render_reads_the_config_at_the_top_of_the_git_work_tree_not_in_a_subfolder(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    if subprocess.run(["git", "init", "-q", str(repo)], capture_output=True).returncode != 0:
        pytest.skip("git is not available")
    write(repo / ".sheaf.toml", 'for = "TopLevel"\n')
    write(repo / "sub" / ".sheaf.toml", 'for = "Subfolder"\n')
    doc = write(repo / "sub" / "doc.md", "# T\n\ntext\n")
    page = sheafmd.render(doc)
    assert "for TopLevel</p>" in page
    assert "Subfolder" not in page


def test_load_root_config_reads_the_file_and_defaults_without_one(work):
    assert sheafmd.load_root_config(work) == sheafmd.RootConfig()
    write(work / ".sheaf.toml",
          'theme = "brand"\nfor = "Acme"\nlinks = false\ncredit = true\nlink_tlds = ["Studio", ".invalid"]\n')
    rc = sheafmd.load_root_config(work)
    assert (rc.theme, rc.for_, rc.links, rc.credit, rc.link_tlds) == (
        "brand", "Acme", False, True, ("studio", "invalid"))


def test_load_theme_reads_a_built_in_by_name_and_a_folder_relative_to_the_root(work):
    assert sheafmd.load_theme("plain").name == "plain"
    make_theme(work / "brand", "Acme Co")
    t = sheafmd.load_theme("brand", work)
    assert (t.name, t.wordmark) == ("brand", "Acme Co")


# ── render: keyword arguments ───────────────────────────────────────────────

def test_the_theme_argument_overrides_the_theme_of_the_root_config(work):
    make_theme(work / "brand")
    write(work / ".sheaf.toml", 'theme = "brand"\n')
    doc = write(work / "doc.md", "# T\n\ntext\n")
    assert 'class="doc-mark"' in sheafmd.render(doc).split("</style>")[1]
    assert 'class="doc-mark"' not in sheafmd.render(doc, theme="plain").split("</style>")[1]


def test_the_theme_argument_takes_a_folder_and_a_theme_object(work, tmp_path):
    make_theme(tmp_path / "elsewhere" / "brand")
    doc = write(work / "doc.md", "# T\n\ntext\n")
    from_folder = sheafmd.render(doc, theme=str(tmp_path / "elsewhere" / "brand"))
    assert '<p class="doc-mark"><b>Acme Co</b>' in from_folder
    obj = sheafmd.load_theme(str(tmp_path / "elsewhere" / "brand"))
    assert sheafmd.render(doc, theme=obj) == from_folder


def test_the_title_argument_sets_the_page_title(work):
    doc = write(work / "doc.md", "# Heading\n\ntext\n")
    assert "<title>Chosen title</title>" in sheafmd.render(doc, title="Chosen title")
    assert "<title>Heading</title>" in sheafmd.render(doc)


def test_the_toc_argument_shows_or_hides_the_contents(work):
    one = write(work / "one.md", "# Only heading\n\ntext\n")
    seven = write(work / "seven.md", headings(7))
    assert '<nav id="toc">' in sheafmd.render(one, toc="always")
    assert '<nav id="toc">' not in sheafmd.render(seven, toc="never")
    assert '<nav id="toc">' in sheafmd.render(seven)           # auto: from six headings
    assert '<nav id="toc">' not in sheafmd.render(one)


def test_the_by_argument_sets_the_byline_and_the_names_of_the_config_come_second(work):
    write(work / ".sheaf.toml", 'for = "Acme"\n')
    doc = write(work / "doc.md", "# T\n\ntext\n")
    assert "Document prepared by Grace for Acme</p>" in sheafmd.render(doc, by="Grace")


@pytest.mark.parametrize("share", [True, False])
def test_the_for_argument_overrides_the_for_of_the_root_config(work, share):
    write(work / ".sheaf.toml", 'for = "Acme"\n')
    doc = write(work / "doc.md", "# T\n\ntext\n")
    page = sheafmd.render(doc, share=share, by="Grace", for_="Globex")
    assert "Document prepared by Grace for Globex</p>" in page and "Acme" not in page


def test_the_for_argument_adds_a_for_where_the_root_config_has_none(work):
    doc = write(work / "doc.md", "# T\n\ntext\n")
    assert "Document prepared by Grace for Globex</p>" in sheafmd.render(doc, by="Grace", for_="Globex")
    assert "Document prepared by Grace</p>" in sheafmd.render(doc, by="Grace")


def test_a_for_of_none_keeps_the_config_and_an_empty_one_leaves_the_for_out(work):
    # None means "the root config's for" (SPEC 6.3); an empty string was asked for, and gets none.
    write(work / ".sheaf.toml", 'for = "Acme"\n')
    doc = write(work / "doc.md", "# T\n\ntext\n")
    assert "Document prepared by Grace for Acme</p>" in sheafmd.render(doc, by="Grace", for_=None)
    assert "Document prepared by Grace</p>" in sheafmd.render(doc, by="Grace", for_="")


def test_the_for_argument_is_written_as_text_never_as_markup(work):
    doc = write(work / "doc.md", "# T\n\ntext\n")
    page = sheafmd.render(doc, by="Grace", for_='<img src=x onerror=alert(1)> & "Co"')
    assert "<img src=x" not in page
    assert "for &lt;img src=x onerror=alert(1)&gt; &amp; &quot;Co&quot;</p>" in page


def test_an_empty_by_argument_is_not_the_same_as_none_it_leaves_the_byline_out(work):
    # None means "the user's name" (SPEC 6.3); an empty string was asked for, and gets no byline.
    doc = write(work / "doc.md", "# T\n\ntext\n")
    assert "Document prepared by" not in sheafmd.render(doc, by="")
    assert "Document prepared by Ada</p>" in sheafmd.render(doc, by=None)


@pytest.mark.parametrize("share", [True, False])
def test_the_assistant_of_the_front_matter_prepared_the_document_not_the_user(work, share):
    # #167: the list row named James and the page named the hub's person.
    doc = write(work / "doc.md", "---\nassistant: James\nkind: question\n---\n\n# T\n\ntext\n")
    page = sheafmd.render(doc, share=share)
    assert "Document prepared by James</p>" in page and "Document prepared by Ada" not in page


def test_the_by_argument_still_wins_over_the_assistant_of_the_front_matter(work):
    doc = write(work / "doc.md", "---\nassistant: James\n---\n\n# T\n\ntext\n")
    assert "Document prepared by Grace</p>" in sheafmd.render(doc, by="Grace")
    assert "Document prepared by" not in sheafmd.render(doc, by="")


@pytest.mark.parametrize("front", ["", "---\nkind: question\n---\n\n", "---\nassistant: ''\n---\n\n",
                                   "---\nassistant: [James, Ada]\n---\n\n"])
def test_without_an_assistant_in_the_front_matter_the_user_prepared_the_document(work, front):
    doc = write(work / "doc.md", front + "# T\n\ntext\n")
    assert "Document prepared by Ada</p>" in sheafmd.render(doc)


def test_the_hub_reads_the_assistant_from_the_text_it_renders_not_the_file(work):
    # The hub renders the text it holds (`src`), which may be ahead of the file on disk.
    from sheafmd.render import render_file
    doc = write(work / "doc.md", "# T\n\ntext\n")
    page = render_file(doc, share=False, src="---\nassistant: James\n---\n\n# T\n\ntext\n", log=[])
    assert "Document prepared by James</p>" in page


def test_the_credit_argument_adds_the_line_and_false_overrides_the_root_config(work):
    doc = write(work / "doc.md", "# T\n\ntext\n")
    assert sheafmd.render(doc, credit=True).count(CREDIT) == 1
    write(work / ".sheaf.toml", "credit = true\n")
    assert sheafmd.render(doc).count(CREDIT) == 1               # None follows the file
    assert CREDIT not in sheafmd.render(doc, credit=False)      # False beats the file


def test_the_max_image_width_argument_downscales_a_wider_image(work):
    write_png(work / "fig.png", 200, 100)
    doc = write(work / "doc.md", "# T\n\n![A figure](fig.png)\n")
    assert embedded_width(sheafmd.render(doc, max_image_width=50)) == 50
    assert embedded_width(sheafmd.render(doc)) == 200


# ── render: the log and the warnings ────────────────────────────────────────

def test_without_a_log_the_warnings_go_to_stderr_and_nothing_else_is_printed(work, capsys):
    make_theme(work / "brand", extra=MISSING_FONT)
    doc = commented_doc(work)
    page = sheafmd.render(doc, theme="brand")
    out, err = capsys.readouterr()
    assert page.startswith("<!doctype html>")
    assert err.splitlines() == [WARNING]
    assert out == ""                                  # the "-" removal lines are not printed


def test_with_a_log_the_warnings_are_only_in_the_list(work, capsys):
    make_theme(work / "brand", extra=MISSING_FONT)
    doc = commented_doc(work)
    log = []
    sheafmd.render(doc, theme="brand", log=log)
    out, err = capsys.readouterr()
    assert WARNING in log
    assert (out, err) == ("", "")


def test_a_clean_render_without_a_log_prints_nothing(work, capsys):
    doc = commented_doc(work)
    sheafmd.render(doc)
    assert capsys.readouterr() == ("", "")


def test_an_unknown_key_in_the_root_config_is_a_warning_in_the_log(work):
    write(work / ".sheaf.toml", "bogus = 1\n")
    doc = write(work / "doc.md", "# T\n\ntext\n")
    log = []
    sheafmd.render(doc, log=log)
    assert [l for l in log if l.startswith("  !")] == [f"  ! unknown key 'bogus' in {work / '.sheaf.toml'}"]


# ── render: errors ──────────────────────────────────────────────────────────

def test_an_unclosed_comment_raises_unclosed_comment_with_its_line(work):
    doc = write(work / "doc.md", "# T\n\n<!-- a closed\nnote -->\n\nFine text.\n\n<!-- never closed\n\nmore\n")
    with pytest.raises(sheafmd.UnclosedComment) as e:
        sheafmd.render(doc)
    assert e.value.line == 8
    assert isinstance(e.value, sheafmd.RenderError)
    assert "line 8" in str(e.value)


def test_a_missing_theme_raises_config_error_naming_it(work):
    doc = write(work / "doc.md", "# T\n\ntext\n")
    with pytest.raises(sheafmd.ConfigError, match="nonexistent"):
        sheafmd.render(doc, theme="nonexistent")


def test_a_missing_theme_in_the_root_config_raises_config_error(work):
    write(work / ".sheaf.toml", 'theme = "gone"\n')
    doc = write(work / "doc.md", "# T\n\ntext\n")
    with pytest.raises(sheafmd.ConfigError, match="gone"):
        sheafmd.render(doc)


def test_a_toml_error_in_the_root_config_raises_config_error_naming_the_file(work):
    write(work / ".sheaf.toml", "for = \n")
    doc = write(work / "doc.md", "# T\n\ntext\n")
    with pytest.raises(sheafmd.ConfigError) as e:
        sheafmd.render(doc)
    assert str(work / ".sheaf.toml") in str(e.value)


# ── strip_comments ──────────────────────────────────────────────────────────

def test_strip_comments_repeats_until_none_is_left():
    assert sheafmd.strip_comments("a<!-- x -->b<!<!-- y -->-- z -->c") == "abc"


def test_strip_comments_logs_each_removal_including_the_one_a_removal_made():
    log = []
    sheafmd.strip_comments("a<!-- x -->b<!<!-- y -->-- z -->c", log)
    assert log == ["  - internal note removed (10 chars): x…",
                   "  - internal note removed (10 chars): y…",
                   "  - internal note removed (10 chars): z…"]


def test_strip_comments_removes_a_multi_line_comment_and_nothing_else():
    assert sheafmd.strip_comments("one\n<!-- two\nthree -->\nfour\n") == "one\n\nfour\n"


def test_strip_comments_leaves_a_text_without_comments_as_it_is():
    log = []
    assert sheafmd.strip_comments("no comments --> here <!- or here\n", log) == "no comments --> here <!- or here\n"
    assert log == []


def test_strip_comments_leaves_an_unclosed_opener_alone():
    assert sheafmd.strip_comments("a<!-- b") == "a<!-- b"


def test_strip_comments_works_without_a_log():
    assert sheafmd.strip_comments("x<!-- y -->z") == "xz"


# ── Source ──────────────────────────────────────────────────────────────────

def test_source_read_returns_the_text_and_its_hash(work):
    doc = write(work / "doc.md", "# T\n\nCafé text.\n")
    text, digest = sheafmd.Source(doc).read()
    assert text == "# T\n\nCafé text.\n"
    assert digest == hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def test_source_hash_changes_with_the_text(work):
    doc = write(work / "doc.md", "one\n")
    first = sheafmd.Source(doc).read()[1]
    doc.write_text("two\n", encoding="utf-8")
    assert sheafmd.Source(doc).read()[1] != first


def test_source_update_writes_the_new_text_and_returns_old_and_new(work):
    doc = write(work / "doc.md", "one\n")
    result = sheafmd.Source(doc).update(lambda t: t + "two\n")
    assert result == ("one\n", "one\ntwo\n")
    assert doc.read_text(encoding="utf-8") == "one\ntwo\n"


def test_source_update_that_changes_nothing_returns_the_text_twice_and_does_not_write(work):
    doc = write(work / "doc.md", "one\n")
    before = doc.stat().st_mtime_ns
    assert sheafmd.Source(doc).update(lambda t: t) == ("one\n", "one\n")
    assert doc.stat().st_mtime_ns == before


def test_source_update_leaves_no_temp_file_and_keeps_the_mode(work):
    doc = write(work / "doc.md", "one\n")
    doc.chmod(0o640)
    sheafmd.Source(doc).update(lambda t: t + "two\n")
    assert sorted(p.name for p in work.iterdir()) == ["doc.md"]
    assert doc.stat().st_mode & 0o777 == 0o640


def test_source_update_with_the_right_hash_writes(work):
    doc = write(work / "doc.md", "one\n")
    src = sheafmd.Source(doc)
    _, digest = src.read()
    src.update(lambda t: "two\n", expected_hash=digest)
    assert doc.read_text(encoding="utf-8") == "two\n"


def test_source_update_with_a_wrong_hash_raises_stale_and_leaves_the_file_unchanged(work):
    doc = write(work / "doc.md", "one\n")
    called = []
    with pytest.raises(sheafmd.StaleError):
        sheafmd.Source(doc).update(lambda t: called.append(t) or "two\n", expected_hash="wrong")
    assert doc.read_text(encoding="utf-8") == "one\n"
    assert called == []                                  # the change was never asked for
    assert sorted(p.name for p in work.iterdir()) == ["doc.md"]


def test_source_update_refuses_a_write_that_would_overwrite_a_change_made_since_the_read(work):
    doc = write(work / "doc.md", "one\n")
    src = sheafmd.Source(doc)
    _, digest = src.read()
    doc.write_text("one\nsomeone else's line\n", encoding="utf-8")
    with pytest.raises(sheafmd.StaleError):
        src.update(lambda t: "mine\n", expected_hash=digest)
    assert doc.read_text(encoding="utf-8") == "one\nsomeone else's line\n"


def test_source_update_holds_the_documents_lock_while_the_change_runs(work):
    doc = write(work / "doc.md", "")
    order, inside = [], threading.Event()

    def slow(text):
        inside.set()
        time.sleep(0.3)
        order.append("first")
        return text + "A"

    def later(text):
        order.append("second")
        return text + "B"

    def second():
        inside.wait(5)
        sheafmd.Source(doc).update(later)

    t = threading.Thread(target=second)
    t.start()
    sheafmd.Source(doc).update(slow)
    t.join(10)
    assert not t.is_alive()
    assert order == ["first", "second"]
    assert doc.read_text(encoding="utf-8") == "AB"


def test_source_update_through_a_symlink_writes_the_real_document_and_keeps_the_link(work):
    doc = write(work / "real.md", "one\n")
    link = work / "link.md"
    link.symlink_to(doc)
    sheafmd.Source(link).update(lambda t: t + "two\n")
    assert link.is_symlink()
    assert doc.read_text(encoding="utf-8") == "one\ntwo\n"


# ── comments.parse ──────────────────────────────────────────────────────────

def test_parse_returns_the_comments_of_a_sheaf_comment_marker():
    c = comments.Comment(id="c1", by="Grace", at="2026-10-14T10:00", quote="word", body="note")
    text = f"A word here.{comments.format(c, one_line=True)}\n"
    assert "<!-- sheaf-comment id=c1" in text
    parsed = sheafmd.comments.parse(text)
    assert [(x.id, x.by, x.body, x.marker, x.status) for x in parsed.comments] == [
        ("c1", "Grace", "note", "sheaf-comment", "open")]
    assert parsed.malformed == []


def test_parse_returns_the_comments_of_a_legacy_rd_comment_marker():
    c = comments.Comment(id="c1", by="Grace", at="2026-10-14T10:00", quote="word", body="note",
                         marker="rd-comment")
    text = f"A word here.{comments.format(c, one_line=False)}\n"
    assert "<!-- rd-comment id=c1" in text and "sheaf-comment" not in text
    parsed = sheafmd.comments.parse(text)
    assert [(x.id, x.by, x.body, x.marker) for x in parsed.comments] == [
        ("c1", "Grace", "note", "rd-comment")]
    assert parsed.malformed == []


def test_parse_reads_a_hand_written_legacy_comment_with_a_reply():
    text = ('A word here.<!-- rd-comment id=c1 by=Grace at=2026-10-14T10:00 status=resolved quote="word"\n'
            "note\n"
            "@Ada 2026-10-14T11:00 answer: done\n"
            "-->\n")
    [c] = sheafmd.comments.parse(text).comments
    assert (c.id, c.by, c.status, c.quote, c.body) == ("c1", "Grace", "resolved", "word", "note")
    assert [(r.by, r.at, r.role, r.text) for r in c.replies] == [("Ada", "2026-10-14T11:00", "answer", "done")]


def test_parse_reads_both_markers_in_one_document_in_order():
    a = comments.Comment(id="c1", by="Grace", at="2026-10-14T10:00", quote="one", body="first")
    b = comments.Comment(id="c2", by="Ada", at="2026-10-14T10:05", quote="two", body="second",
                         marker="rd-comment")
    text = (f"Para one.{comments.format(a, one_line=True)}\n\n"
            f"Para two.{comments.format(b, one_line=True)}\n")
    parsed = sheafmd.comments.parse(text)
    assert [(c.id, c.marker) for c in parsed.comments] == [("c1", "sheaf-comment"), ("c2", "rd-comment")]


def test_parse_round_trips_what_format_wrote():
    c = comments.Comment(id="c7", by="Grace Hopper", at="2026-10-14T10:00", quote="a \"quoted\" <word>",
                         body="line one\nline two -- with dashes")
    [back] = sheafmd.comments.parse(f"Text.{comments.format(c, one_line=False)}\n").comments
    assert (back.id, back.by, back.quote, back.body) == (c.id, c.by, c.quote, c.body)


def test_parse_reports_an_unclosed_comment_as_malformed_and_a_document_without_comments_as_empty():
    parsed = sheafmd.comments.parse("Text.\n\n<!-- sheaf-comment id=c1 by=Ada never closed\n")
    assert parsed.comments == []
    assert [(m.line, m.reason) for m in parsed.malformed] == [(3, "never closed")]
    empty = sheafmd.comments.parse("# Just a heading\n\nand text\n")
    assert empty.comments == [] and empty.malformed == []


# ── write_pdf ───────────────────────────────────────────────────────────────

def test_write_pdf_without_chrome_raises_pdf_error_that_says_what_is_needed(work, monkeypatch):
    monkeypatch.setattr("sheafmd.pdf.find_chrome", lambda: None)
    out = work / "out.pdf"
    with pytest.raises(sheafmd.PdfError) as e:
        sheafmd.write_pdf(sheafmd.render(commented_doc(work)), out)
    assert NO_CHROME in str(e.value)
    assert not out.exists()


@HAS_CHROME
def test_write_pdf_prints_the_share_copy_to_a_pdf_file(work, short_tmp):
    doc = commented_doc(work)
    out = work / "out.pdf"
    assert sheafmd.write_pdf(sheafmd.render(doc), out) is None
    assert out.read_bytes().startswith(b"%PDF")


@HAS_CHROME
def test_write_pdf_takes_a_string_path_too(work, short_tmp):
    doc = commented_doc(work)
    out = work / "str.pdf"
    sheafmd.write_pdf(sheafmd.render(doc), str(out))
    assert out.read_bytes().startswith(b"%PDF")
