"""pandoc comes only from the pinned pypandoc-binary wheel (SPEC 3.2).

The edit round-trip depends on pandoc's exact output, so the version is asserted:
an upgrade is a deliberate change that updates the pin in pyproject.toml, this
constant, and runs the whole suite.
"""
import tomllib
from pathlib import Path

import pypandoc

BUNDLED_PANDOC = "3.9"
PIN = "pypandoc-binary==1.17"


def test_the_bundled_pandoc_is_the_version_the_suite_was_written_against():
    assert pypandoc.get_pandoc_version() == BUNDLED_PANDOC


def test_pandoc_is_the_wheels_binary_not_the_one_on_path():
    path = Path(pypandoc.get_pandoc_path())
    assert path.parent.name == "files" and path.parent.parent.name == "pypandoc"


def test_pyproject_pins_pypandoc_binary_exactly():
    root = Path(__file__).resolve().parent.parent
    deps = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    assert PIN in deps


def test_no_module_shells_out_to_a_bare_pandoc():
    """Every pandoc call gets its binary from pypandoc.get_pandoc_path() (SPEC 3.2)."""
    import re
    src = Path(__file__).resolve().parent.parent / "src" / "sheafmd"
    bare = re.compile(r"""\[\s*["']pandoc["']""")
    offenders = [f"{p.relative_to(src)}:{n}" for p in src.rglob("*.py")
                 for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if bare.search(line)]
    assert offenders == []


# A document can make pandoc 3.9 run without end and grow without bound: a footnote that cites
# itself. Every call of pandoc has a heap cap and a time limit, from one place.
SELF_CITING_FOOTNOTE = "[^1]: a [^1]\n"


def test_the_one_pandoc_runner_stops_a_footnote_that_cites_itself(monkeypatch):
    import time

    from sheafmd import _pandoc
    monkeypatch.setattr(_pandoc, "HEAP", "-M64m")
    t = time.time()
    r = _pandoc.run(["-f", "gfm", "-t", "html5"], SELF_CITING_FOOTNOTE)
    assert r.returncode != 0 and "Heap exhausted" in r.stderr
    assert time.time() - t < 30


def test_the_one_pandoc_runner_stops_a_run_that_takes_too_long(monkeypatch):
    from sheafmd import _pandoc
    monkeypatch.setattr(_pandoc, "TIMEOUT", 0.3)       # the runaway input runs longer than that
    monkeypatch.setattr(_pandoc, "HEAP", "-M128m")      # and cannot take much memory meanwhile
    r = _pandoc.run(["-f", "gfm", "-t", "html5"], SELF_CITING_FOOTNOTE)
    assert r.returncode != 0
    assert "did not finish" in r.stderr or "Heap exhausted" in r.stderr


def test_a_document_that_makes_pandoc_run_away_is_a_render_error_not_a_hang(tmp_path, monkeypatch):
    import pytest

    import sheafmd
    from sheafmd import _pandoc
    monkeypatch.setattr(_pandoc, "HEAP", "-M64m")
    p = tmp_path / "doc.md"
    p.write_text("Intro.\n\n" + SELF_CITING_FOOTNOTE, encoding="utf-8")
    for share in (True, False):
        with pytest.raises(sheafmd.RenderError):
            sheafmd.render(p, share=share)


def test_pandoc_is_started_from_one_module_only():
    """So the cap cannot be forgotten by a new call."""
    src = Path(__file__).resolve().parent.parent / "src" / "sheafmd"
    offenders = [p.name for p in src.rglob("*.py")
                 if p.name != "_pandoc.py" and "get_pandoc_path" in p.read_text(encoding="utf-8")]
    assert offenders == []
