"""No synthetic test value takes the shape of a secret (#53).

The Codex review runner (~/.claude/skills/codex-review/codex-review.sh) refuses a diff with a line its secret pattern
matches, and only Thierry may override it. A fixture that set TOKEN to a quoted value of 12 characters or more matched it, so every diff that
touched one stopped the review. The pattern below is the runner's SECRET_TEXT, read with grep -aEi, one line at a time.
A test value that must look like a secret is written as two literals, the first under 12 characters.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRET_TEXT = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{35}|(sk|rk)_live_[0-9A-Za-z]{16,}"
    r"|(api[_-]?key|secret|token|password)[A-Za-z0-9_]*[ \t\r\f\v]*[:=][ \t\r\f\v]*[\"'][^\"' ]{12,}",
    re.IGNORECASE)


def test_the_pattern_is_the_runners():
    assert SECRET_TEXT.search('TOKEN = "' + 'SENTINEL-DOOR-TOKEN"')
    assert SECRET_TEXT.search('FakeGoogle(token_error="' + 'invalid_grant")')
    assert not SECRET_TEXT.search('TOKEN = "SENTINEL-" "DOOR-TOKEN"')


def test_no_test_file_holds_a_secret_shaped_line():
    files = subprocess.run(["git", "ls-files", "-z", "tests"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\0")
    files = [f for f in files if f]
    assert files
    hits = [f"{f}:{n}" for f in files
            for n, line in enumerate((ROOT / f).read_text(encoding="utf-8", errors="replace").splitlines(), 1)
            if SECRET_TEXT.search(line)]
    assert hits == []
