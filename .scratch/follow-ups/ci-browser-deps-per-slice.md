# Install Firefox and WebKit (and their system packages) only in the slices that run them

**What to build:** Make the page-test step install `firefox` and `webkit` with `--with-deps` only in the CI slices that contain a test for those engines, so the other slices install Chromium and its packages alone.

**Blocked by:** None.

**Status:** ready, not started. Measure the saving first (see Open question).

## Problem

Every slice runs `playwright install --with-deps chromium firefox webkit` (`.github/workflows/ci.yml`, step "Page tests (Playwright, Chromium, Firefox, WebKit)"), and `--with-deps` runs apt through sudo for the system packages of all three engines. On a slow runner mirror that apt step is what hung the install: 45 minutes in run 44765451025, and ten minutes then a lock failure in runs 44789430505 and 44790768975 (see the apt-lock fix).

## What the tests use (read from `tests/page`, 2026-11-20)

Only five files name an engine other than Chromium:

| File | Engines besides Chromium | Where |
|------|--------------------------|-------|
| `tests/page/test_mount_page.py` | firefox, webkit | fixture params, line 130 |
| `tests/page/test_mount_selection.py` | firefox, webkit | `ENGINES`, line 52 |
| `tests/page/test_mount_allowlist.py` | firefox, webkit | `ENGINES`, line 22 |
| `tests/page/test_user_modify.py` | firefox, webkit | fixture params, line 16 |
| `tests/page/test_page_mobile_composer.py` | webkit only | fixture params, line 31 |

No other page test uses Firefox or WebKit.

## Why per-slice is not free today

`tests/conftest.py` (`pytest_collection_modifyitems`) deals the tests to the six slices round-robin, one unit at a time. Collecting each slice with `SHEAF_TEST_SLICE=i/6 pytest -m page --collect-only` gives, per slice (206 page tests each):

| Slice | Firefox items | WebKit items |
|-------|---------------|--------------|
| 1 | 13 | 11 |
| 2 | 15 | 19 |
| 3 | 11 | 19 |
| 4 | 15 | 12 |
| 5 | 16 | 15 |
| 6 | 7 | 20 |

Every slice holds both engines, so skipping them per slice saves nothing until the five files are gathered into fewer slices (or into a job of their own).

## Options

- **A. Put the five files in one slice or one job.** The other slices (or jobs) then install `chromium` only. The cost is an uneven slice: those five files hold 168 collected ids that name Firefox or WebKit (112 + 8 + 23 + 13 + 12, summed over the six slices) that now run in one place.
- **B. Leave the slices and fix the mirror.** Point apt at a different mirror, or bound it better (the apt-lock fix already stops a slow try from poisoning the next).

## Open question

How much install time the other slices save is not measured. Before building, read the step timings of a green run: the `Installing dependencies...` to first test, per slice, with and without Firefox and WebKit (run `playwright install --with-deps chromium` against `... chromium firefox webkit` on t-compute, or compare the apt download sizes in the job log).

## Do not

Do not cache the apt packages (`/var/cache/apt` is root-owned, and a poisoned cache would run as root on a public repo). The browser download itself is already cached (`Cache the Playwright browsers`, keyed on the runner image and `uv.lock`).
