"""tools/check-rendered-pdf.py and tools/VERIFYING-RENDERED-OUTPUT.md (SPEC 18): dev tooling
for checking a rendered PDF."""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import BRAND_WORDS, write

from sheafmd import pdf

TOOLS = Path(__file__).resolve().parent.parent / "tools"
SCRIPT = TOOLS / "check-rendered-pdf.py"
HAS_POPPLER = shutil.which("pdftotext") is not None and shutil.which("pdfinfo") is not None
NEEDS_PDF_TOOLS = pytest.mark.skipif(
    pdf.find_chrome() is None or not HAS_POPPLER,
    reason="needs Chrome or Chromium and poppler's pdftotext and pdfinfo")


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("check_rendered_pdf", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_both_files_are_there_and_the_script_is_executable():
    assert (TOOLS / "VERIFYING-RENDERED-OUTPUT.md").is_file()
    assert SCRIPT.is_file() and SCRIPT.stat().st_mode & 0o111


def test_the_tools_name_no_brand():
    words = BRAND_WORDS
    for f in (SCRIPT, TOOLS / "VERIFYING-RENDERED-OUTPUT.md"):
        text = f.read_text(encoding="utf-8").lower()
        assert [w for w in words if w in text] == [], f.name


def test_the_note_points_at_the_script_where_it_lives():
    note = (TOOLS / "VERIFYING-RENDERED-OUTPUT.md").read_text(encoding="utf-8")
    assert "tools/check-rendered-pdf.py DOC.pdf" in note
    assert "tools/check-rendered-pdf.py --self-test DOC.pdf" in note


# ── the rules, on text ──────────────────────────────────────────────────────

def test_norm_folds_case_wrapping_quotes_and_dashes(tool):
    assert tool.norm("Orders at priority 1 to 3") in tool.norm("ORDERS AT\nPRIORITY 1 TO 3")
    assert tool.norm("Buyer’s — criterion") == "buyer's - criterion"


def test_a_stranded_table_tail_is_found(tool):
    assert tool.stranded_table_tail(["REGION", "ORDERS", "Total", "210"]) == ["Total", "210"]


def test_a_wrapped_heading_and_a_healthy_table_are_not_a_tail(tool):
    heading = ["THE SECOND HARBOUR SURVEY RAISES THE SAME", "QUESTION AS THE FIRST SURVEY",
               "None of the ten quays is on the maintenance record, so far."]
    assert tool.stranded_table_tail(heading) is None
    assert tool.stranded_table_tail(["REGION", "VISITS"] + [str(i) for i in range(12)]) is None
    assert tool.stranded_table_tail(["A single uppercase line is a heading".upper(), "Text."]) is None


def test_the_chart_sources_are_read_from_the_sibling_md(tool, tmp_path):
    spec = '```chart\n{"y_label": "Visits by quarter", "note": "Source: the log."}\n```\n'
    write(tmp_path / "plan.md", f"# T\n\n{spec}")
    assert tool.charts_from_source(tmp_path / "plan.pdf") == [("Visits by quarter", "Source: the log.")]
    assert tool.charts_from_source(tmp_path / "plan-share.pdf") == [("Visits by quarter", "Source: the log.")]
    assert tool.charts_from_source(tmp_path / "other.pdf") is None


def test_a_share_pdf_prefers_its_own_sibling_md_when_there_is_one(tool, tmp_path):
    write(tmp_path / "plan.md", '```chart\n{"y_label": "A", "note": "one"}\n```\n')
    write(tmp_path / "plan-share.md", '```chart\n{"y_label": "B", "note": "two"}\n```\n')
    assert tool.charts_from_source(tmp_path / "plan-share.pdf") == [("B", "two")]


# ── on a real PDF ───────────────────────────────────────────────────────────

LONG = " ".join(["The harbour opens in spring and closes again in autumn."] * 12)


@pytest.fixture
def printed(work, sheaf, short_tmp):
    def make(text, name="plan"):
        doc = write(work / f"{name}.md", text)
        r = sheaf(doc, "--share", "--pdf")
        assert r.code == 0, r.err
        return work / f"{name}-share.pdf"
    return make


def run_tool(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True,
                          text=True, timeout=120)


@NEEDS_PDF_TOOLS
def test_the_self_test_passes_on_a_real_pdf(printed):
    r = run_tool("--self-test", printed(f"# Plan\n\n{LONG}\n"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("PASS") == 7 and "FAIL" not in r.stdout


@NEEDS_PDF_TOOLS
def test_a_page_with_a_real_ending_is_ok_and_a_stub_is_reported(printed):
    ok = run_tool(printed(f"# Plan\n\n{LONG}\n"))
    assert ok.returncode == 0 and "   ok" in ok.stdout and "0 issue(s)" in ok.stdout
    stub = run_tool(printed("# Plan\n\nShort.\n", name="stub"))
    assert stub.returncode == 1 and "final page carries only" in stub.stdout


@NEEDS_PDF_TOOLS
def test_a_chart_note_missing_from_the_pdf_is_reported_not_skipped(printed, work):
    pdf_path = printed(f"# Plan\n\n{LONG}\n")
    write(work / "plan.md", '```chart\n{"y_label": "Visits", "note": "A note that is not in it."}\n```\n')
    r = run_tool(pdf_path)
    assert r.returncode == 1 and "chart note not found in the PDF" in r.stdout


def test_with_no_arguments_the_script_prints_its_usage_and_exits_2():
    r = run_tool()
    assert r.returncode == 2 and "usage:" in r.stderr and r.stdout == ""
    assert run_tool("--self-test").returncode == 2


def test_a_pdf_that_is_not_there_is_an_issue_not_a_traceback(tmp_path):
    r = run_tool(tmp_path / "missing.pdf")
    assert r.returncode == 1 and "no such file" in r.stdout and "Traceback" not in r.stderr
    assert "1 issue(s)" in r.stdout


def test_a_chart_block_that_is_not_json_is_said_to_be_unchecked(tool, tmp_path, capsys):
    write(tmp_path / "plan.md", "```chart\n{not json}\n```\n")
    assert tool.charts_from_source(tmp_path / "plan.pdf") == []
    assert "NOT checked" in capsys.readouterr().err
