"""Columns in the printed PDF (block editor v1, ticket 05): side by side at their stored split, whatever the page's width.
Needs Chrome or Chromium and poppler's pdftotext; skipped without them."""
import shutil
import subprocess
import tempfile

import pytest

import sheafmd
from sheafmd import pdf

pytestmark = pytest.mark.skipif(pdf.find_chrome() is None or shutil.which("pdftotext") is None,
                                reason="needs Chrome or Chromium and poppler's pdftotext")

MD = ('# T\n\n::: {#k .columns}\n::: {#a .column size="33"}\nLEFTWORD one two three.\n:::\n'
      '::: {#b .column size="67"}\nRIGHTWORD four five six.\n:::\n:::\n')


def test_columns_print_side_by_side(tmp_path, tmp_path_factory, monkeypatch):
    short = str(tmp_path_factory.mktemp("c"))
    monkeypatch.setenv("TMPDIR", short)
    monkeypatch.setattr(tempfile, "tempdir", short)
    md = tmp_path / "d.md"
    md.write_text(MD, encoding="utf-8")
    out = tmp_path / "d.pdf"
    pdf.write_pdf(sheafmd.render(md, share=True), out)
    assert out.read_bytes().startswith(b"%PDF")
    text = subprocess.run(["pdftotext", "-layout", str(out), "-"], capture_output=True, text=True, check=True).stdout
    row = next(line for line in text.splitlines() if "LEFTWORD" in line)
    assert "RIGHTWORD" in row, text
    assert row.index("RIGHTWORD") > row.index("LEFTWORD") + 8
