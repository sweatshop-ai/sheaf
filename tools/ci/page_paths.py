"""Decide whether a pull request has to run the page tests (SPEC 18).

The page tests (tests/page) take about 14 minutes of a 29-minute pull-request run. They load the
whole package (the hub, the page's JS and CSS, the agents), the shared test support (conftest,
helpers, fakes, the leak guard, the corpus), the lock and the CI files that run them. A pull request
that touches none of these (notes, SPEC, README, another test file) cannot
change what they see, so it skips them. The list errs on the inclusive side: a path not named here
that matters is a path missing from the skip, never from the run. Anything that is not a pull
request, and any failure to read the diff, runs them.

    python tools/ci/page_paths.py            # in a job: reads the pull request's merge commit
    python tools/ci/page_paths.py FILE...    # the decision for a list of changed files
"""
import os
import re
import subprocess
import sys

SKIPPED = "Page tests skipped: no page path changed"

# A path the page tests load or are run by. A directory ends in "/".
PAGE_PATHS = (
    "src/",
    "tests/page/",
    "tests/corpus/",
    "tools/ci/",
    "pyproject.toml",
    "uv.lock",
    ".github/workflows/ci.yml",
)
# tests/ holds test_*.py files, which the page tests do not import, and the support they do import.
# Every other file under tests/, in any folder, so a folder added later runs them too.
# \Z and DOTALL: "$" also matches before a trailing newline and "." skips a newline, so a name
# a test file name that ends in a newline would be taken for a test file and skipped.
SUPPORT = re.compile(r"tests/(?!test_[^/]*\.py\Z).+", re.DOTALL)


def touches_page(files):
    """The files among `files` that make the page tests run. A name that is not UTF-8 (it holds a
    lone surrogate) cannot be judged, so it runs them."""
    return [f for f in files if f.startswith(PAGE_PATHS) or SUPPORT.fullmatch(f) or not _is_utf8(f)]


def _is_utf8(name):
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def changed_files():
    """The files a pull request changes: the merge commit against its first parent, the base.
    --no-renames lists the old path of a move as well as the new one, and -z leaves a name with
    non-ASCII characters unquoted. The bytes are decoded with surrogateescape, so a name that is not
    UTF-8 survives as a name that touches_page refuses to skip."""
    out = subprocess.run(["git", "diff", "--name-only", "--no-renames", "-z", "HEAD^1", "HEAD"],
                         capture_output=True, check=True).stdout
    return [f for f in out.decode("utf-8", "surrogateescape").split("\0") if f]


def decide(event, files):
    """(run, line to print). `files` is a list, or None when the diff could not be read."""
    if event != "pull_request":
        return True, f"Page tests run: this is a {event or 'run'}, not a pull request"
    if files is None:
        return True, "Page tests run: the diff could not be read"
    hit = touches_page(files)
    if not hit:
        return False, SKIPPED
    return True, f"Page tests run: {len(hit)} page path(s) changed, first {hit[0]}"


def main(argv):
    if argv:
        run, line = decide("pull_request", argv)
    else:
        try:
            files = changed_files()
        except (OSError, subprocess.CalledProcessError):
            files = None
        run, line = decide(os.environ.get("GITHUB_EVENT_NAME"), files)
    # a name can carry lone surrogates, and stdout may not be UTF-8: print ASCII, which cannot fail
    print(line.encode("ascii", "backslashreplace").decode("ascii"), flush=True)
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"run={'true' if run else 'false'}\n")


if __name__ == "__main__":
    main(sys.argv[1:])
