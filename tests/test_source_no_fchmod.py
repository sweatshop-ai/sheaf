"""os.fchmod does not exist on native Windows before Python 3.13: the atomic writer
must still write the document and keep its mode where the platform has chmod."""
import os
import stat

import pytest

from sheafmd import source as rds


def test_write_atomic_without_fchmod(tmp_path, monkeypatch):
    doc = tmp_path / "d.md"
    doc.write_text("old\n", encoding="utf-8")
    doc.chmod(0o640)
    monkeypatch.delattr(os, "fchmod")
    rds._write_atomic(doc, "new\n")
    assert doc.read_text(encoding="utf-8") == "new\n"
    assert not (tmp_path / ".d.md.sheaf-tmp").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_write_atomic_without_fchmod_keeps_the_mode(tmp_path, monkeypatch):
    doc = tmp_path / "d.md"
    doc.write_text("old\n", encoding="utf-8")
    doc.chmod(0o640)
    monkeypatch.delattr(os, "fchmod")
    rds._write_atomic(doc, "new\n")
    assert stat.S_IMODE(doc.stat().st_mode) == 0o640
