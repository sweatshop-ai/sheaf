"""The slices of CI (SHEAF_TEST_SLICE, tests/conftest.py) keep every Firefox and WebKit test in the last slice, so the
other five install Chromium alone (ci.yml)."""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["tests/page/test_mount_page.py", "tests/page/test_user_modify.py", "tests/page/test_page_mobile_composer.py",
         "tests/page/test_page_boot.py"]


# The id of a test in another engine starts with the engine's name (ci.yml reads it the same way); a Chromium id can
# hold "-webkit-user-modify" in a later part.
ENGINE_ID = re.compile(r"::.*\[(firefox|webkit)(-|\])")


def collect(slice_):
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    env["SHEAF_TEST_SLICE"] = slice_
    r = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:xdist", "-m", "page",
                        "--collect-only", "-q", *FILES], cwd=ROOT, capture_output=True, text=True, timeout=120, env=env)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    return [ln for ln in r.stdout.splitlines() if "::" in ln]


def test_a_test_that_runs_in_firefox_or_webkit_is_in_the_last_slice_and_in_no_other():
    # Run 44788361173: all six slices held 7 to 16 Firefox and 11 to 20 WebKit tests, so each one installed the system
    # packages of all three engines (126 MB, 181 packages), and a slow mirror held every job.
    slices = {i: collect(f"{i}/6") for i in range(1, 7)}
    other = [i for i in range(1, 6) if any(ENGINE_ID.search(t) for t in slices[i])]
    assert other == [], f"slices {other} hold a Firefox or WebKit test"
    last = slices[6]
    assert any("[firefox" in t for t in last) and any("[webkit" in t for t in last)


def test_every_test_is_in_one_slice_and_the_chromium_ones_are_still_spread_over_all_six():
    whole = collect("1/1")
    slices = [collect(f"{i}/6") for i in range(1, 7)]
    dealt = [t for s in slices for t in s]
    assert sorted(dealt) == sorted(whole) and len(set(dealt)) == len(dealt)
    chromium = [sum(not ENGINE_ID.search(t) for t in s) for s in slices]
    assert sum(n > 0 for n in chromium) >= 5, chromium
