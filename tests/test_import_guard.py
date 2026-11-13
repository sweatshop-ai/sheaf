"""A worktree that runs the suite with another checkout's venv imports that checkout's sheafmd: the editable
install wins, and the run is green or red about code that is not here. Three times in 2026 a green run on the
wrong code was believed for a while (2026-10-24 twice, 2026-10-31). The suite refuses to start instead."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def collect(pythonpath):
    env = {**os.environ, "PYTHONPATH": str(pythonpath)}
    return subprocess.run([sys.executable, "-m", "pytest", "--co", "-q", "-p", "no:cacheprovider", __file__],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


def test_a_suite_whose_sheafmd_comes_from_elsewhere_refuses_to_start_and_names_both_places(tmp_path):
    (tmp_path / "sheafmd").mkdir()
    (tmp_path / "sheafmd" / "__init__.py").write_text("")

    r = collect(tmp_path)

    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "tests collected" not in out and "test collected" not in out
    assert str(tmp_path / "sheafmd" / "__init__.py") in out
    assert f"PYTHONPATH={ROOT / 'src'}" in out


def test_a_suite_that_imports_its_own_sheafmd_starts():
    r = collect(ROOT / "src")

    assert r.returncode == 0, r.stdout + r.stderr
