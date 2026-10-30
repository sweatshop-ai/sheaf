"""The CI workflow (SPEC 18), read as text: the project has no YAML reader and a macOS minute counts
ten times, so the triggers and the matrix are decided and these tests hold them:

  pull_request to main  ubuntu x {3.13}
  push to main          ubuntu x {3.13}
  schedule, 01:00       ubuntu x {3.11, 3.13, 3.14}, on main
  workflow_dispatch     ubuntu, and macOS too only when started with `macos` ticked; one Python or all

and where it runs: every job on GitHub's own runners.
"""
import os
import subprocess
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"

MATRIX_OS = ("os: ${{ fromJSON(github.event_name == 'workflow_dispatch' && inputs.macos && "
             "'[\"ubuntu-24.04\",\"macos-26\"]' || '[\"ubuntu-24.04\"]') }}")
RUNS_ON = "runs-on: ${{ matrix.os }}"
MATRIX_PYTHON = ("python: ${{ fromJSON(github.event_name == 'workflow_dispatch' && inputs.python != 'all' && "
                 "format('[\"{0}\"]', inputs.python) || (github.event_name == 'workflow_dispatch' || "
                 "github.event_name == 'schedule') && "
                 "'[\"3.11\",\"3.13\",\"3.14\"]' || '[\"3.13\"]') }}")


@pytest.fixture(scope="module")
def text():
    return CI.read_text(encoding="utf-8")


def section(text, key, indent=0):
    """The lines under `key:` at this indent, up to the next key at the same indent."""
    lines = text.splitlines()
    pad = " " * indent
    start = next((i for i, ln in enumerate(lines) if re.fullmatch(rf"{pad}{re.escape(key)}:\s*(#.*)?", ln)), None)
    assert start is not None, f"no `{key}:` at indent {indent}"
    out = []
    for ln in lines[start + 1:]:
        if ln.strip() and not ln.startswith(pad + " ") and not ln.lstrip().startswith("#"):
            break
        out.append(ln)
    return "\n".join(out)


def keys(block, indent):
    return re.findall(rf"^{' ' * indent}([A-Za-z_-]+):", block, flags=re.M)


def test_it_is_the_only_workflow():
    assert sorted(p.name for p in WORKFLOWS.iterdir()) == ["ci.yml"]


def test_it_runs_on_exactly_the_four_decided_triggers(text):
    assert keys(section(text, "on"), 2) == ["pull_request", "push", "schedule", "workflow_dispatch"]


def test_a_pull_request_to_main_and_a_push_to_main_only(text):
    on = section(text, "on")
    assert re.search(r"^  pull_request:\n    branches: \[main\]\s*$", on, flags=re.M)
    assert re.search(r"^  push:\n    branches: \[main\]\n", on, flags=re.M)
    assert len(re.findall(r"branches:", on)) == 2


def test_the_full_matrix_runs_every_night_and_the_scratch_filter_does_not_stop_it(text):
    on = section(text, "on")
    assert re.search(r"^  schedule:\n    - cron: '0 1 \* \* \*'\s*$", on, flags=re.M)
    # paths-ignore is a push filter only: it must not sit under schedule or pull_request.
    assert "paths-ignore" not in section(on, "schedule", 2)


def test_a_pull_request_does_not_ignore_paths(text):
    # A pull request is never filtered by path: required checks must be able to report.
    pr = section(section(text, "on"), "pull_request", 2)
    assert "paths" not in pr


def test_a_new_push_to_a_pull_request_cancels_the_run_before_it_and_a_run_on_main_is_never_cancelled(text):
    # A macOS run takes about half an hour and merges follow one another: with `true` the next
    # merge cancelled the macOS jobs of the one before it mid-way, so on
    # main they never finished. A pull request has no macOS job, and its earlier run is stale.
    block = section(text, "concurrency")
    assert "cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}" in block
    assert "cancel-in-progress: true" not in block
    assert "github.ref" in block
    # Each run on main has a group of its own: a group keeps one waiting run, and a newer one would replace it.
    assert "group: ci-${{ github.ref == 'refs/heads/main' && github.run_id || github.ref }}" in block


def test_the_matrix_is_ubuntu_on_every_trigger_and_macos_only_when_a_manual_run_asks_for_it(text):
    matrix = section(section(section(text, "jobs"), "test", 2), "strategy", 4)
    assert MATRIX_OS in matrix
    assert MATRIX_PYTHON in matrix
    assert keys(section(matrix, "matrix", 6), 8) == ["os", "python"]


def test_a_manual_run_picks_macos_and_the_python_version_and_macos_starts_off(text):
    inputs = section(section(section(text, "on"), "workflow_dispatch", 2), "inputs", 4)
    assert keys(inputs, 6) == ["macos", "python"]
    macos, python = section(inputs, "macos", 6), section(inputs, "python", 6)
    assert re.search(r"^        type: boolean\s*$", macos, flags=re.M)
    assert re.search(r"^        default: false\s*$", macos, flags=re.M)
    assert re.search(r'^        options: \[all, "3\.11", "3\.13", "3\.14"\]\s*$', python, flags=re.M)
    assert re.search(r"^        default: all\s*$", python, flags=re.M)


def test_a_manual_run_offers_each_version_of_the_matrix_and_all_of_them(text):
    # The option that runs every version is named `all`: with three versions it is not "both" any
    # more, and a version added to the matrix and not to the input could never be run on its own.
    # The versions, read as text from the pin above.
    listed = re.search(r"&& '\[([^']*)\]' \|\| '\[\"3\.13\"\]'\) \}\}$", MATRIX_PYTHON).group(1)
    matrix = [v.strip('"') for v in listed.split(",")]
    python = section(section(section(section(text, "on"), "workflow_dispatch", 2), "inputs", 4), "python", 6)
    options = re.search(r"^        options: \[(.*)\]\s*$", python, flags=re.M).group(1)
    assert [o.strip().strip('"') for o in options.split(",")] == ["all", *matrix]


def test_macos_is_named_only_in_that_one_expression_and_the_manual_input(text):
    asked_for = section(section(text, "on"), "workflow_dispatch", 2).splitlines()
    named = [ln for ln in text.splitlines()
             if "macos" in ln.lower() and not ln.lstrip().startswith("#") and ln not in asked_for]
    allowed = [ln for ln in named if MATRIX_OS in ln]
    # The steps that need to know the system ask runner.os, never name a runner image.
    assert len(allowed) == 1
    assert all("runs-on" not in ln and "macos-" not in ln.lower() for ln in named if ln not in allowed)
    others = [ln for ln in named if ln not in allowed]
    assert all(re.search(r"runner\.os == 'macOS'|service_macos\.py", ln) for ln in others), others


def test_one_job_asks_for_a_runner_and_nothing_else_does(text):
    assert re.findall(r"^\s*runs-on:.*$", text, flags=re.M) == ["    " + RUNS_ON]
    assert keys(section(text, "jobs"), 2) == ["test"]


def test_every_job_runs_on_the_runner_its_matrix_value_names(text):
    # GitHub's own runners: the matrix value is `ubuntu-24.04` or `macos-26`.
    line = re.search(r"^\s*runs-on: (.*)$", text, flags=re.M).group(1)
    assert line == "${{ matrix.os }}"


def test_the_ubuntu_image_is_named_never_latest(text):
    # `ubuntu-latest` moved to 26.04 on 2026-10-29 and Playwright 1.58 refused it: Playwright supports a fixed
    # list of systems per version, so a moving label breaks the page tests the day it moves. The image changes
    # only in a pull request that moves it (and Playwright with it when needed).
    assert not [ln for ln in text.splitlines() if "ubuntu-latest" in ln and not ln.lstrip().startswith("#")]


def test_the_macos_image_is_named_never_latest(text):
    # Same failure mode as ubuntu-latest (#65): Playwright supports a fixed list of macOS versions too.
    assert not [ln for ln in text.splitlines() if "macos-latest" in ln and not ln.lstrip().startswith("#")]


def test_a_job_that_hangs_is_stopped(text):
    assert re.search(r"^    timeout-minutes: (\d+)\s*$", text, flags=re.M)
    assert int(re.search(r"^    timeout-minutes: (\d+)", text, flags=re.M).group(1)) <= 45


def test_the_token_can_only_read_and_no_secret_is_used(text):
    assert re.search(r"^permissions:\n  contents: read\s*$", text, flags=re.M)
    assert "secrets." not in text
    assert "pull_request_target" not in text


def test_only_three_actions_are_used_each_at_a_major_version(text):
    used = re.findall(r"^\s*(?:- )?uses: (\S+)\s*$", text, flags=re.M)
    assert used
    names = {u.split("@")[0] for u in used}
    assert names <= {"actions/checkout", "actions/cache", "astral-sh/setup-uv"}
    assert all(re.fullmatch(r"[\w./-]+@v\d+", u) for u in used), used


def test_uv_and_the_playwright_browsers_are_cached(text):
    assert re.search(r"enable-cache: true", text)
    cache = [ln for ln in text.splitlines() if "ms-playwright" in ln]
    assert any("Library/Caches/ms-playwright" in ln and ".cache/ms-playwright" in ln for ln in cache)
    assert "uses: actions/cache@" in text


def test_the_playwright_cache_key_names_the_runner_image(text):
    # A move of the image with the same uv.lock restored browsers built on the old one (#65). `env.ImageOS`
    # is empty in an expression (the env context leaves out what the runner inherits), so a step reads it.
    step = text[text.index("- name: Name the runner image"):text.index("- name: Cache the Playwright browsers")]
    assert "id: image" in step and '"os=${ImageOS:?' in step and '>> "$GITHUB_OUTPUT"' in step
    # bash reads an apostrophe inside "${ImageOS:?...}" as an opening quote: the step did not parse (PR #82 gate).
    run = re.search(r"^\s*run: (.*)$", step, flags=re.M).group(1)
    assert subprocess.run(["bash", "-n", "-c", run], capture_output=True).returncode == 0, run
    key = re.search(r"^\s*key: (playwright-.*)$", text, flags=re.M).group(1)
    assert key == "playwright-${{ runner.os }}-${{ steps.image.outputs.os }}-${{ hashFiles('uv.lock') }}"


def test_the_move_to_a_new_ubuntu_image_with_playwright_is_written_down(text):
    # #65: the move to 26.04 and the Playwright bump go in one pull request, by these steps.
    head = text[:text.index("name: CI")]
    assert "To move the ubuntu image" in head
    for word in ("playwright==", "uv lock", "MATRIX_OS", "SPEC 18", "page tests", "macos", "python=all"):
        assert word in head, word


def test_it_installs_from_the_lock_and_runs_pytest_without_the_page_marks_first(text):
    assert "uv sync --locked" in text
    assert text.index('-m "not page"') < text.index("-m page")


def test_both_pytest_runs_name_their_tests_and_go_through_the_stall_watch(text):
    """A job that hung for 24 minutes printed dots and no test name."""
    runs = [ln for ln in text.splitlines() if "pytest" in ln and "uv run" in ln]
    assert len(runs) == 2
    for ln in runs:
        assert "tools/ci/stall_watch.py --" in ln and "pytest -v " in ln and "pytest -q" not in ln
        assert "--durations=25" in ln


def test_the_page_tests_run_only_where_there_are_some_and_may_not_skip(text):
    block = text[text.index("Playwright"):]
    assert "hashFiles('tests/page/**') != ''" in block
    assert "chromium" in block
    # A browser that did not start skips every page test with a reason: that is a failure here.
    assert re.search(r"skipped", block)
    assert "exit 1" in block


def test_the_service_checks_run_per_system_through_the_ci_scripts(text):
    assert "tools/ci/service_linux.py" in text and "tools/ci/service_macos.py" in text
    assert re.search(r"if: runner\.os == 'Linux'", text)
    assert re.search(r"if: runner\.os == 'macOS'", text)


def test_the_wheel_is_built_and_installed_as_a_user_would(text):
    assert "tools/wheel_smoke.py" in text


def test_the_browsers_system_packages_are_installed_by_the_job_only_where_it_can_use_sudo(text):
    # `--with-deps` runs apt through sudo, so the job passes it only where sudo exists.
    block = text[text.index("Page tests (Playwright, Chromium)"):]
    assert re.search(r'if \[ "\$RUNNER_OS" = "Linux" \] && command -v sudo >/dev/null; then deps="--with-deps"; fi', block)
    assert 'playwright install $deps chromium' in block


def test_a_failed_job_prints_the_state_of_the_host_the_browser_died_on(text):
    # A Chromium has died with no word on a runner. The runner has no
    # dmesg (kernel.dmesg_restrict) and a memory cap of its own, so the step reads what it can.
    i = text.index("- name: Host state after a failure")
    block = text[i:text.index("\n      - name:", i + 1) if "\n      - name:" in text[i + 1:] else len(text)]
    assert "if: failure()" in block
    for want in ("free -m", "uptime", "memory.events", "/dev/shm", "dmesg"):
        assert want in block, want


# ── the page tests on a pull request (tools/ci/page_paths.py) ─────────────────

def page_paths():
    import importlib.util
    path = ROOT / "tools" / "ci" / "page_paths.py"
    spec = importlib.util.spec_from_file_location("page_paths", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_page_tests_are_decided_in_their_own_step_before_the_steps_that_use_the_answer(text):
    i = text.index("- name: Decide whether the page tests run")
    step = text[i:text.index("\n      - name:", i)]
    assert "id: page" in step and "tools/ci/page_paths.py" in step
    ifs = re.findall(r"^        if: (.*)$", text[i:], flags=re.M)
    assert ifs[:2] == ["hashFiles('tests/page/**') != '' && steps.page.outputs.run == 'true'"] * 2
    # checkout keeps the base: the merge commit's first parent
    assert re.search(r"actions/checkout@v4\n        with:\n(?:          #.*\n)?          fetch-depth: 2\n", text)


def test_a_pull_request_that_changes_no_page_path_skips_the_page_tests_and_says_so():
    pp = page_paths()
    for files in (["SPEC.md"], ["notes/x.md", "README.md", "docs/a.md"],
                  ["tests/test_ci_workflow.py", "tools/wheel_smoke.py"], []):
        run, line = pp.decide("pull_request", files)
        assert run is False and line == "Page tests skipped: no page path changed", files


@pytest.mark.parametrize("path", [
    "src/sheafmd/page/page.js", "src/sheafmd/page/page.css", "src/sheafmd/hub/server.py",
    "src/sheafmd/comments.py", "tests/page/test_page_boot.py", "tests/page/pagehelp.py",
    "tests/conftest.py", "tests/helpers.py", "tests/agent_fakes.py", "tests/leakguard.py",
    "tests/corpus/lists.md", "tools/ci/stall_watch.py", "pyproject.toml", "uv.lock",
    ".github/workflows/ci.yml"])
def test_a_pull_request_that_changes_a_path_the_page_tests_load_runs_them(path):
    run, line = page_paths().decide("pull_request", ["SPEC.md", path])
    assert run is True and path in line


def test_one_page_path_among_many_other_files_is_enough():
    assert page_paths().decide("pull_request", ["SPEC.md"] * 50 + ["src/sheafmd/cli.py"])[0] is True


@pytest.mark.parametrize("event", ["push", "schedule", "workflow_dispatch", None])
def test_anything_but_a_pull_request_always_runs_the_page_tests(event):
    # even when the diff touches nothing the tests load
    assert page_paths().decide(event, ["SPEC.md"])[0] is True


def test_a_diff_that_cannot_be_read_runs_the_page_tests():
    assert page_paths().decide("pull_request", None)[0] is True


def test_this_workflow_file_is_a_page_path():
    # a pull request that edits ci.yml runs the page tests it changed
    assert ".github/workflows/ci.yml" in page_paths().PAGE_PATHS
    assert page_paths().decide("pull_request", [".github/workflows/ci.yml"])[0] is True


def test_the_script_writes_its_answer_to_the_step_output(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    page_paths().main(["SPEC.md"])
    page_paths().main(["src/sheafmd/cli.py"])
    assert out.read_text() == "run=false\nrun=true\n"


def test_a_folder_added_under_tests_is_a_page_path_but_a_test_file_is_not():
    pp = page_paths()
    assert pp.decide("pull_request", ["tests/fixtures/doc.md"])[0] is True
    assert pp.decide("pull_request", ["tests/test_merge.py"])[0] is False


def temp_repo(path):
    """A git repo in `path` and a runner for it, cut off from the host's gitconfig: a developer who
    signs commits or has a global hook gets the same result as CI."""
    git = lambda *a: subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t",
                                     "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *a],
                                    check=True, capture_output=True)
    git("init", "-q")
    return git


def test_the_temp_repo_does_not_sign_or_run_hooks(tmp_path, monkeypatch):
    cfg = tmp_path / "gitconfig"
    cfg.write_text("[commit]\n\tgpgsign = true\n[core]\n\thooksPath = /nonexistent\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    repo = tmp_path / "r"
    repo.mkdir()
    git = temp_repo(repo)
    (repo / "a").write_text("a\n")
    git("add", "-A"); git("commit", "-qm", "one")
    assert subprocess.run(["git", "-C", str(repo), "log", "--format=%G?"], capture_output=True,
                          text=True).stdout.strip() == "N"


@pytest.mark.parametrize("path", ["tests/test_x.py\n", "tests/fixtures/a\nb.md", "tests/a\n"])
def test_a_name_with_a_newline_is_not_a_test_file_and_runs_the_page_tests(path):
    # SUPPORT's "$" matched before a trailing newline, and "." did not match a newline inside
    assert page_paths().decide("pull_request", ["SPEC.md", path])[0] is True


def test_a_name_that_is_not_utf8_runs_the_page_tests_and_the_step_stays_green(tmp_path, monkeypatch, capsys):
    git = temp_repo(tmp_path)
    (tmp_path / "a.txt").write_text("a\n")
    git("add", "-A"); git("commit", "-qm", "base")
    bad = os.fsencode(tmp_path) + b"/notes/caf\xe9.md"
    os.makedirs(os.path.dirname(bad))
    try:
        with open(bad, "wb") as f:
            f.write(b"x\n")
    except OSError:
        pytest.skip("this filesystem refuses a file name that is not UTF-8")
    git("add", "-A"); git("commit", "-qm", "pr")
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    page_paths().main([])
    assert out.read_text() == "run=true\n"
    # judged as a page path, not the "diff could not be read" fallback
    assert "page path(s) changed" in capsys.readouterr().out


def test_the_changed_files_name_a_move_by_both_paths_and_a_non_ascii_name_unquoted(tmp_path, monkeypatch):
    git = temp_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("x = 1\n" * 20)
    git("add", "-A"); git("commit", "-qm", "base")
    (tmp_path / "docs").mkdir()
    git("mv", "src/x.py", "docs/x.py")
    (tmp_path / "docs" / "é.md").write_text("é\n")
    git("add", "-A"); git("commit", "-qm", "pr")
    monkeypatch.chdir(tmp_path)
    files = page_paths().changed_files()
    assert sorted(files) == ["docs/x.py", "docs/é.md", "src/x.py"]
    assert page_paths().decide("pull_request", files)[0] is True
