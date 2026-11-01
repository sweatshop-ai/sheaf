"""The render pipeline in the order of SPEC 6.2, one step per test group."""
import importlib
import json
import re

import pytest
from PIL import Image

import sheafmd
from sheafmd.theme import Theme

R = importlib.import_module("sheafmd.render")        # sheafmd.render is the public function


def doc(tmp_path, text, name="doc.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def page_of(tmp_path, text, **kw):
    return sheafmd.render(doc(tmp_path, text), **kw)


def body(out: str) -> str:
    return out[out.index("<main>"):out.index("</main>")]


# ── 5. headings ─────────────────────────────────────────────────────────────

def test_headings_get_ascii_folded_ids_and_a_repeat_gets_a_number(tmp_path):
    out = page_of(tmp_path, "# Caf\u00e9 au lait\n\n## Same\n\n## Same\n\n### Same\n\n##### Deep\n")
    ids = re.findall(r'<h([1-5]) id="([^"]+)"', out)
    assert ids == [("1", "cafe-au-lait"), ("2", "same"), ("2", "same-1"), ("3", "same-2"),
                   ("5", "deep")]


def test_pandoc_own_heading_id_is_dropped_so_there_is_one(tmp_path):
    out = page_of(tmp_path, "# Caf\u00e9\n")
    [h] = re.findall(r"<h1[^>]*>", out)
    assert h.count("id=") == 1


@pytest.mark.parametrize("text,flagged", [
    ("Correction: the figure was wrong", True), ("Retracted claim", True),
    ("The earlier number was superseded by this one", True), ("A correctional facility", False),
    ("Corrected", True), ("Nothing wrong here", False)])
def test_a_heading_that_corrects_or_retracts_is_flagged_in_body_and_contents(tmp_path, text, flagged):
    out = page_of(tmp_path, f"# T\n\n## {text}\n", toc="always")
    h2 = re.search(r"<h2[^>]*>", out).group(0)
    assert ('class="flagged"' in h2) is flagged
    assert ('class="lv2 flag"' in out) is flagged


def test_only_the_first_70_characters_decide_the_flag(tmp_path):
    out = page_of(tmp_path, f"# T\n\n## {'x' * 80} correction\n")
    assert 'class="flagged"' not in out


def test_h1_to_h3_go_to_the_contents_and_h4_does_not(tmp_path):
    out = page_of(tmp_path, "# One\n\n## Two\n\n### Three\n\n#### Four\n", toc="always")
    nav = out[out.index('<nav id="toc">'):out.index("</nav>")]
    assert [m for m in re.findall(r'class="lv(\d)', nav)] == ["1", "2", "3"]
    assert "Four" not in nav and 'id="four"' in out


def test_contents_appear_automatically_from_six_headings(tmp_path):
    five = "".join(f"## H{i}\n\n" for i in range(5))
    assert '<nav id="toc">' not in page_of(tmp_path, five)
    assert '<nav id="toc">' in page_of(tmp_path, five + "## H5\n")
    assert '<nav id="toc">' not in page_of(tmp_path, five + "## H5\n", toc="never")
    assert '<nav id="toc">' in page_of(tmp_path, "# One\n", toc="always")
    assert '<body class="notoc">' in page_of(tmp_path, "# One\n")


# ── title ───────────────────────────────────────────────────────────────────

def test_the_title_comes_from_the_option_then_the_first_heading_then_the_file_name(tmp_path):
    assert "<title>Given</title>" in page_of(tmp_path, "# Heading\n", title="Given")
    assert "<title>Heading &amp; more</title>" in page_of(tmp_path, "intro\n\n# Heading *&* more\n")
    assert "<title>my first plan</title>" in sheafmd.render(doc(tmp_path, "no heading\n", "my-first-plan.md"))


def test_a_heading_with_markup_gives_a_plain_title(tmp_path):
    assert "<title>Q4 plan v2</title>" in page_of(tmp_path, "# Q4 `plan` [v2](https://example.com)\n")
    assert "<title>Q4 plan</title>" in page_of(tmp_path, "# Q4 **plan**\n")


# ── 11. header ──────────────────────────────────────────────────────────────

def test_the_byline_names_who_prepared_it_and_for_whom_only_when_the_root_says(tmp_path):
    p = doc(tmp_path, "# T\n\ntext\n")
    assert '<p class="doc-by" data-rd-ui>Document prepared by Grace</p>' in sheafmd.render(p, by="Grace")
    (tmp_path / ".sheaf.toml").write_text('for = "Acme"\n')
    assert "Document prepared by Grace for Acme</p>" in sheafmd.render(p, by="Grace")


def test_the_byline_sits_after_the_first_title_and_defaults_to_the_users_name(tmp_path):
    out = page_of(tmp_path, "# T\n\ntext\n")
    assert re.search(r"</h1>\s*<p class=\"doc-by\"[^>]*>Document prepared by Ada</p>", out)


def test_labelled_lines_at_the_top_get_a_line_each(tmp_path):
    out = page_of(tmp_path, "# Call\n\n**Call:** Tuesday\n**Who:** Ada and Grace\n**Why:** budget\n\nBody.\n")
    [para] = re.findall(r'<p class="doc-fields">([\s\S]*?)</p>', out)
    assert para.count("<br>") == 2
    assert re.search(r"<br>\s*<strong>Who:</strong>", para)


def test_a_first_paragraph_without_a_label_is_left_alone(tmp_path):
    assert "doc-fields" not in body(page_of(tmp_path, "# T\n\nJust **bold** words: here.\n"))


# ── 10, 12. lead-ins and tables ─────────────────────────────────────────────

def test_a_paragraph_ending_in_a_colon_is_a_lead_in(tmp_path):
    out = page_of(tmp_path, "# T\n\nThe options are:\n\n- a\n- b\n\nNo colon here.\n")
    assert '<p class="leadin">The options are:</p>' in out
    assert out.count("leadin") >= 1 and "<p>No colon here.</p>" in out


def test_a_table_is_wrapped_for_scrolling(tmp_path):
    out = page_of(tmp_path, "| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert '<div class="tblwrap"><table>' in out and "</table></div>" in out


# ── 7. images ───────────────────────────────────────────────────────────────

def test_a_local_image_is_embedded_with_its_caption_and_missing_ones_are_loud(tmp_path):
    Image.new("RGB", (30, 10), "red").save(tmp_path / "pic.png")
    log = []
    out = page_of(tmp_path, '![alt words](pic.png "The caption")\n\n![x](nope.png)\n\n![r](https://example.com/r.png)\n',
                  log=log)
    assert '<figure><img src="data:image/png;base64,' in out
    assert "<figcaption>The caption</figcaption>" in out
    assert "[missing image: nope.png]" in out
    assert 'src="https://example.com/r.png"' in out
    assert any("embedded pic.png" in line for line in log)
    assert any(line.startswith("  ! image not found") for line in log)
    assert any("remote image left as-is" in line for line in log)


# ── 8. local paths ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/home/ada/notes/a.md", "/Users/ada/notes/a.md", "/opt/x/y", "/var/log/z",
                                  "/etc/hosts.d/x", "/srv/www/site"])
def test_an_absolute_local_path_becomes_a_file_link(tmp_path, path):
    out = page_of(tmp_path, f"See {path} for more.\n")
    assert f'<a class="filelink" href="file://{path}">{path}</a>' in out


def test_a_path_in_a_code_block_or_already_a_link_is_left_alone(tmp_path):
    out = page_of(tmp_path, "```\n/home/ada/a/b\n```\n\n[here](/home/ada/a/b)\n\n`cp /home/a/x /home/b/y`\n")
    assert "filelink" not in body(out)


def test_a_path_alone_in_inline_code_is_linked(tmp_path):
    assert 'class="filelink"' in body(page_of(tmp_path, "At `/home/ada/a/b.md` now.\n"))


# ── 6. charts ───────────────────────────────────────────────────────────────

def test_a_chart_fence_becomes_an_inline_svg_and_a_bad_one_says_why(tmp_path):
    good = json.dumps({"type": "bar", "x": ["a", "b"], "series": [{"name": "n", "values": [1, 2]}]})
    out = page_of(tmp_path, f"```chart\n{good}\n```\n\n```chart\n{{not json\n```\n")
    assert body(out).count('<div class="chart"><svg') == 1
    assert "chart spec error" in body(out)


def test_without_mmdc_a_mermaid_fence_stays_code_and_the_log_says_how_to_install(tmp_path, monkeypatch):
    from sheafmd import charts
    monkeypatch.setattr(charts.shutil, "which", lambda name: None)
    log = []
    out = page_of(tmp_path, "```mermaid\ngraph LR\n  A-->B\n```\n", log=log)
    assert "mermaid-svg" not in body(out) and "graph LR" in body(out)
    assert any("mmdc is not installed" in line and "npm install" in line for line in log)


# ── 9. the link rule ────────────────────────────────────────────────────────

def test_the_link_rule_warns_through_warn_only_and_not_on_a_render_without_one(tmp_path):
    p = doc(tmp_path, "# T\n\nSee example.com/pricing please.\n")
    seen = []
    R.render_file(p, log=[], warn=seen.append)
    assert len(seen) == 1 and "example.com/pricing" in seen[0]
    seen.clear()
    R.render_file(p, log=[])
    assert seen == []


def test_the_root_can_turn_the_link_rule_off_and_add_endings(tmp_path):
    p = doc(tmp_path, "# T\n\nSee example.studio/x and example.com/pricing.\n")
    seen = []

    def mentions():
        return re.findall(r"^      (\S+)    in:", seen[0], re.M)
    R.render_file(p, log=[], warn=seen.append)
    assert mentions() == ["example.com/pricing"]
    (tmp_path / ".sheaf.toml").write_text('link_tlds = ["studio"]\n')
    seen.clear()
    R.render_file(p, log=[], warn=seen.append)
    assert mentions() == ["example.studio/x", "example.com/pricing"]
    (tmp_path / ".sheaf.toml").write_text("links = false\n")
    seen.clear()
    R.render_file(p, log=[], warn=seen.append)
    assert seen == []


def test_a_document_without_an_h1_is_warned_that_it_opens_on_its_first_section(tmp_path):
    p = doc(tmp_path, "## Which one, when\n\nText.\n", name="security-guide.md")
    seen = []
    R.render_file(p, log=[], warn=seen.append)
    assert len(seen) == 1
    assert "no `# ` title line" in seen[0] and "Which one, when" in seen[0]
    assert '"security guide"' in seen[0]
    seen.clear()
    R.render_file(p, log=[])
    assert seen == []
    p.write_text("# Security checks: which skill to use\n\n## Which one, when\n", encoding="utf-8")
    R.render_file(p, log=[], warn=seen.append)
    assert seen == []


def test_the_no_h1_warning_says_a_front_matter_title_is_not_shown(tmp_path):
    p = doc(tmp_path, "---\ntitle: Security skills\n---\n\n## Which one, when\n")
    seen = []
    R.render_file(p, log=[], warn=seen.append)
    assert len(seen) == 1 and "front-matter `title:` is not shown" in seen[0]
    p.write_text("## Which one, when\n", encoding="utf-8")
    seen.clear()
    R.render_file(p, log=[], warn=seen.append)
    assert len(seen) == 1 and "front-matter" not in seen[0]


# ── 14. assembly ────────────────────────────────────────────────────────────

def test_the_plain_theme_has_no_wordmark_and_no_footer_text(tmp_path):
    out = page_of(tmp_path, "# T\n")
    assert "doc-mark" in out                         # the stylesheet knows the class
    assert '<p class="doc-mark">' not in out
    assert "@bottom-left" not in out
    assert 'counter(page) " / " counter(pages)' in out        # every theme prints the page count


def test_a_theme_gives_wordmark_tagline_footer_and_its_own_stylesheet(tmp_path):
    t = tmp_path / "brand"
    t.mkdir()
    (t / "theme.toml").write_text('name = "brand"\nwordmark = "ACME & SONS"\ntagline = "We make things"\n'
                                  'pdf_footer = "ACME \\"quoted\\""\n')
    (t / "theme.css").write_text("h1{color:#c00}")
    out = page_of(tmp_path, "# T\n", theme=str(t))
    assert '<p class="doc-mark"><b>ACME &amp; SONS</b><span>We make things</span></p>' in out
    assert re.search(r'@media print\{@page\{@bottom-left\{content:"ACME \\"quoted\\""', out)
    assert out.index("h1{color:#c00}") > out.index("*{box-sizing:border-box}")     # base first, theme after
    assert "-apple-system" not in out                                                # plain's stylesheet replaced


def test_a_theme_from_the_root_config_is_found_relative_to_the_root(tmp_path):
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "theme.toml").write_text('name = "t"\nwordmark = "FROM ROOT"\n')
    (tmp_path / ".sheaf.toml").write_text('theme = "t"\n')
    assert "<b>FROM ROOT</b>" in page_of(tmp_path, "# T\n")
    assert "<b>FROM ROOT</b>" not in page_of(tmp_path, "# T\n", theme="plain")


def test_the_credit_line_ends_the_page_only_when_asked(tmp_path):
    line = '<p class="sheaf-credit">Made with <a href="https://github.com/sweatshop-ai/sheaf">sheaf</a></p>'
    assert line not in page_of(tmp_path, "# T\n")
    assert line + "</main>" in page_of(tmp_path, "# T\n", credit=True)
    assert line in page_of(tmp_path, "# T\n", credit=True, share=False)


def test_the_page_is_self_contained(tmp_path):
    out = page_of(tmp_path, "# T\n\ntext\n", share=False)
    assert not re.findall(r'(?:src|href)="(?:https?:)?//', out)
    assert "@import" not in out and "<link" not in out


def test_a_share_copy_is_one_utf8_document(tmp_path):
    out = page_of(tmp_path, "# Caf\u00e9 \u2014 plan\n\nna\u00efve \u2713\n")
    assert out.startswith("<!doctype html>") and '<meta charset="utf-8">' in out
    assert "Caf\u00e9 \u2014 plan" in out and "na\u00efve \u2713" in out


# ── the page ────────────────────────────────────────────────────────────────

def test_the_page_carries_sentinels_a_meta_block_and_the_editor(tmp_path):
    p = doc(tmp_path, "# T\n\nFirst.\n\n- a\n- b\n\n```\ncode\n```\n")
    log = []
    out = sheafmd.render(p, share=False, log=log)
    assert "<!--MDB:0-->" in out
    meta = json.loads(re.search(r'<script id="rd-edit-meta" type="application/json">(.*?)</script>', out,
                                re.S).group(1))
    assert meta["name"] == "doc.md" and meta["edit"] is True and meta["why"] == ""
    assert meta["me"] == "Ada" and meta["comments"] == [] and meta["malformed"] == []
    assert meta["hash"] == sheafmd.Source(p).read()[1]
    assert meta["editable"] and set(meta["editable"]) <= set(meta["commentable"]) | set(meta["editable"])
    assert "page.js" not in out and "(?:sheaf|rd)-comment" in out
    assert any("edit mode" in line and "blocks editable" in line for line in log)


def test_the_meta_block_has_none_of_the_hubs_values(tmp_path):
    out = sheafmd.render(doc(tmp_path, "# T\n"), share=False)
    meta = json.loads(re.search(r'<script id="rd-edit-meta" type="application/json">(.*?)</script>', out,
                                re.S).group(1))
    for hub_only in ("doc", "token", "boot", "service", "agent", "can", "seen", "md", "ask", "tell"):
        assert hub_only not in meta


def test_the_hub_can_add_its_own_values_and_they_win(tmp_path):
    p = doc(tmp_path, "# T\n")
    out = R.render_file(p, share=False, log=[], extra_meta={"doc": "root/doc.md", "me": "Grace"})
    meta = json.loads(re.search(r'<script id="rd-edit-meta" type="application/json">(.*?)</script>', out,
                                re.S).group(1))
    assert meta["doc"] == "root/doc.md" and meta["me"] == "Grace"


def test_when_sentinels_would_change_the_render_the_page_is_served_without_them(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_same_render", lambda a, b: False)
    log = []
    out = sheafmd.render(doc(tmp_path, "# T\n\ntext\n"), share=False, log=log)
    meta = json.loads(re.search(r'<script id="rd-edit-meta" type="application/json">(.*?)</script>', out,
                                re.S).group(1))
    assert "<!--MDB:" not in out
    assert meta["edit"] is False and meta["why"] == "block markers would alter this render"
    assert meta["editable"] == [] and meta["commentable"] == []
    assert "  ! edit mode off: block markers would alter this render" in log
    assert "<script" in out                                      # the page and its export still work


def test_a_comment_holding_a_closing_script_tag_cannot_end_the_meta_block(tmp_path):
    from sheafmd import comments as rdc
    c = rdc.format(rdc.Comment(id="c1", by="Grace", at="2026-10-14T10:00", quote="text",
                               body="</script><b>ZQ-X</b>"), True)
    out = sheafmd.render(doc(tmp_path, f"# T\n\ntext{c}\n"), share=False)
    meta_block = re.search(r'<script id="rd-edit-meta" type="application/json">(.*?)</script>', out, re.S).group(1)
    assert "</script>" not in meta_block and "\\u003c/script>" in meta_block
    assert json.loads(meta_block)["comments"][0]["body"] == "</script><b>ZQ-X</b>"
    assert "<b>ZQ-X</b>" not in out.replace(meta_block, "")


def test_a_comment_in_a_heading_stays_out_of_the_contents_and_the_id(tmp_path):
    from sheafmd import comments as rdc
    c = rdc.format(rdc.Comment(id="c1", by="Grace", at="2026-10-14T10:00", quote="Budget",
                               body="note ZQ-HEAD"), True)
    out = sheafmd.render(doc(tmp_path, f"# T\n\n## Budget{c}\n"), share=False, toc="always")
    nav = out[out.index('<nav id="toc">'):out.index("</nav>")]
    assert "ZQ-HEAD" not in nav and 'id="budget"' in out


def test_the_byline_reads_the_assistant_from_the_given_source_text_not_the_file(tmp_path):
    # The hub renders the text it holds (#167), which may be ahead of the file on disk.
    p = doc(tmp_path, "# T\n\ntext\n")
    out = R.render_file(p, share=False, log=[], src="---\nassistant: James\n---\n\n# T\n\ntext\n")
    assert "Document prepared by James</p>" in out


def test_a_given_source_text_is_rendered_instead_of_the_file(tmp_path):
    p = doc(tmp_path, "# From disk\n")
    out = R.render_file(p, share=False, log=[], src="# From the hub\n")
    assert "From the hub" in out and "From disk" not in out
    meta = json.loads(re.search(r'<script id="rd-edit-meta" type="application/json">(.*?)</script>', out,
                                re.S).group(1))
    from sheafmd.source import md_hash
    assert meta["hash"] == md_hash("# From the hub\n")


def test_pandoc_is_the_bundled_one(tmp_path, monkeypatch):
    import pypandoc
    calls = []
    real = R.subprocess.run

    def spy(cmd, *a, **kw):
        calls.append(cmd[0])
        return real(cmd, *a, **kw)
    monkeypatch.setattr(R.subprocess, "run", spy)
    page_of(tmp_path, "# T\n", share=False)
    assert {c for c in calls if c != "git"} == {pypandoc.get_pandoc_path()}


def test_a_missing_file_is_an_error_not_an_empty_page(tmp_path):
    with pytest.raises(FileNotFoundError):
        sheafmd.render(tmp_path / "nope.md")


def test_the_theme_object_can_be_passed_directly(tmp_path):
    t = Theme(name="x", css="h1{color:red}", wordmark="W")
    out = page_of(tmp_path, "# T\n", theme=t)
    assert "<b>W</b>" in out and "h1{color:red}" in out


PRE_DOC = "# T\n\n<pre>\nline one\n\nline three\n</pre>\n\nAfter.\n"


def test_a_raw_pre_across_a_blank_line_is_not_given_block_markers(tmp_path):
    # The splitter cuts the <pre> at its blank line; the markers it would put there add
    # blank lines inside the element, which a reader sees. Whitespace outside a <pre>
    # still does not count as a difference, inside one it does.
    log = []
    out = sheafmd.render(doc(tmp_path, PRE_DOC), share=False, log=log)
    assert "<!--MDB:" not in out
    assert "<pre>\nline one\n\nline three\n</pre>" in out
    assert "  ! edit mode off: block markers would alter this render" in log


def test_same_render_reads_whitespace_in_a_pre_exactly_and_elsewhere_loosely():
    plain = "<h1>T</h1>\n<pre>\na\n\nb\n</pre>\n<p>x  y</p>\n"
    spaced = "\n\n<h1>T</h1>\n\n\n<pre>\na\n\nb\n</pre>\n\n<p>x\ny</p>\n"
    assert R._same_render(spaced, plain)
    assert R._same_render("<!--MDB:1-->" + spaced, plain)
    assert not R._same_render(spaced.replace("a\n\nb", "a\n\n\n\nb"), plain)
    assert not R._same_render(spaced.replace("<pre>\na", "<pre>a"), plain)
    assert not R._same_render("<PRE>\na\n\n\nb\n</PRE>", "<PRE>\na\n\nb\n</PRE>")


def test_a_fenced_code_block_with_blank_lines_keeps_edit_mode(tmp_path):
    log = []
    out = sheafmd.render(doc(tmp_path, "# T\n\n```\nline one\n\nline three\n```\n\nAfter.\n"), share=False, log=log)
    assert "<!--MDB:" in out and not [x for x in log if "edit mode off" in x]


@pytest.mark.parametrize("share", [False, True])
@pytest.mark.parametrize("depth", [200, 300, 700])
def test_quotes_nested_hundreds_of_levels_deep_render_whichever_python_runs_them(tmp_path, depth, share):
    # The sanitiser wrote its tree out with a bs4 call that compares tags one level at a
    # time, so the render raised RecursionError (not a RenderError) at 248 levels on 3.11 and at 496
    # on 3.12, and how deep a document may nest was the interpreter's to say. 200 is the control.
    out = page_of(tmp_path, "> " * depth + "x\n", share=share)
    assert out.count("<blockquote") == depth and "x" in body(out)
