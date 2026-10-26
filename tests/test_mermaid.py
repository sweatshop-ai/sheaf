"""```mermaid fences become inline SVG through mmdc, cached by source."""
import hashlib
import os
import pwd
import shutil
from pathlib import Path

import pytest

from sheafmd import charts, paths

SRC = "graph LR\n  A-->B\n"
FENCE = '<pre class="mermaid"><code>graph LR\n  A--&gt;B\n</code></pre>'


def test_without_mmdc_the_diagram_stays_code(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEAF_HOME", str(tmp_path))
    monkeypatch.setattr(charts.shutil, "which", lambda name: None)
    log = []
    assert charts.render_mermaid(FENCE, log) == FENCE
    assert "mmdc is not installed" in log[0]


def test_a_cached_diagram_is_inlined_with_its_own_id(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEAF_HOME", str(tmp_path))
    k = hashlib.sha256(SRC.encode()).hexdigest()[:12]
    cache = paths.cache_dir() / "mermaid"
    cache.mkdir(parents=True)
    (cache / f"{k}.svg").write_text(f'<svg id="mmd-{k}"></svg>')
    out = charts.render_mermaid(FENCE, [])
    assert out == f'<div class="mermaid-svg"><svg id="mmd-{k}"></svg></div>'


@pytest.mark.skipif(not shutil.which("mmdc"), reason="mmdc not installed")
def test_two_diagrams_render_in_one_run_with_distinct_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEAF_HOME", str(tmp_path))
    # conftest points HOME at an empty folder, and mmdc's headless Chrome is found
    # through ~/.cache/puppeteer: tell it where the real cache is.
    real_cache = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".cache" / "puppeteer"
    if "PUPPETEER_CACHE_DIR" not in os.environ and real_cache.is_dir():
        monkeypatch.setenv("PUPPETEER_CACHE_DIR", str(real_cache))
    two = FENCE + '<pre class="mermaid"><code>sequenceDiagram\n  A-&gt;&gt;B: hi\n</code></pre>'
    out = charts.render_mermaid(two, [])
    assert out.count('<div class="mermaid-svg"><svg') == 2
    assert "my-svg" not in out
