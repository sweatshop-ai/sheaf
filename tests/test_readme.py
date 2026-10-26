"""The README (SPEC 23): what a new user meets first. It holds the name, the pitch, install, a quick
start, the agents, the platforms, the remote-box setup, the security model in one paragraph, the
"Made by" line with no link, and the licence, in that order. It names no person and no client, and
every command it shows is one this build has."""
import re
from pathlib import Path

import pytest

from helpers import BRAND_WORDS, CREDIT
from sheafmd.cli import COMMANDS

README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
HEADINGS = re.findall(r"^#{1,3} (.+)$", README, re.M)


def test_the_readme_has_its_parts_in_the_order_of_the_spec():
    wanted = ["sheaf", "Install", "Quick start", "Agents", "Platforms", "A hub on a remote box",
              "Security", "Licence"]
    at = [HEADINGS.index(h) for h in wanted]
    assert at == sorted(at), HEADINGS
    assert README.index("A working page for a markdown document") < README.index("## Install")


def test_the_made_by_line_is_the_one_of_the_spec_with_no_link_between_security_and_licence():
    line = CREDIT
    assert line.startswith("Made by ")
    lines = README.splitlines()
    assert line in lines
    assert "](" not in line and "http" not in line
    assert README.index("## Security") < README.index(line) < README.index("## Licence")


def test_the_licence_is_mit():
    licence = README.split("## Licence", 1)[1]
    assert "MIT" in licence


def test_the_install_command_is_the_documented_one():
    assert "uv tool install sheafmd" in README
    assert "sheaf init claude" in README
    for agent in ("claude", "codex", "gemini", "cursor"):
        assert agent in README.split("## Agents", 1)[1].split("## Platforms", 1)[0]


def test_the_platforms_say_linux_is_tested_in_ci_and_macos_is_not_tested_yet():
    # v1 ships for Linux: macOS is not tested, so the README must not say CI runs it.
    platforms = README.split("## Platforms", 1)[1].split("\n## ", 1)[0]
    # One bullet per platform: "- **Name** text", the text running on into two-space continuation lines.
    bullets = {m.group(1): " ".join(m.group(2).split())
               for m in re.finditer(r"^- \*\*(\w+)\*\*(.*(?:\n  .*)*)", platforms, re.M)}
    assert {"Linux", "macOS", "Windows"} <= set(bullets), bullets
    assert "tested" in bullets["Linux"] and "CI" in bullets["Linux"]
    assert "every pull request" in bullets["Linux"]
    # The versions and the platform CI runs; aarch64 was one run by hand.
    assert "x86-64, with Python 3.13" in bullets["Linux"]
    assert "every merge to main" in bullets["Linux"]
    assert "Python 3.11, 3.13 and 3.14 every night" in bullets["Linux"]
    assert "aarch64" in bullets["Linux"] and "once, by hand" in bullets["Linux"]
    assert "not tested yet" in bullets["macOS"] and "runs the whole test suite" not in bullets["macOS"]
    assert "use WSL2 (untested)" in bullets["Windows"]


def test_the_remote_box_setup_is_there_with_its_three_steps():
    box = README.split("## A hub on a remote box", 1)[1].split("\n## ", 1)[0]
    for need in ("sheaf service install", "loginctl enable-linger", "ssh -L 27419:127.0.0.1:27419",
                 "sheaf signin-url"):
        assert need in box, need


def test_the_security_model_is_one_paragraph():
    security = README.split("## Security", 1)[1].split("\n---", 1)[0].strip()
    assert "\n\n" not in security and len(security) > 400


def test_the_readme_names_no_person_no_address_no_client_and_no_path_of_a_machine():
    low = README.lower()
    # The first brand word is the maker's name in the Made-by line, and nowhere else.
    brand = [w for w in BRAND_WORDS if w in low and w != "tir" + "oir"]
    assert brand == []
    assert low.count("tir" + "oir") == 1
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", README)
    assert "/home/" not in README and "/Users/" not in README


def test_every_sheaf_command_the_readme_shows_is_a_command_of_this_build():
    shown = set(re.findall(r"(?:`|^    |^```\n)sheaf ([a-z][a-z-]*)(?![\w.])", README, re.M))
    assert {"init", "comments", "reply", "service", "signin-url", "rotate"} <= shown
    for word in shown:
        assert word in COMMANDS, f"the README shows `sheaf {word}`, which is not a command"


def test_the_service_section_says_what_ci_checks_and_that_no_mac_has_run_it():
    section = README.split("## Keep the hub running", 1)[1].split("\n## ", 1)[0]
    section = " ".join(section.split())
    assert "CI installs the service for real on a Linux runner" in section
    assert "`kill -9`" in section and "upgrade" in section
    # No CI run is a macOS run any more: the section must not say one lints the agent.
    assert "macOS runner" not in section and "lints" not in section
    assert "written but not tested" not in section
    assert "pretend to be a Mac" in section and "on a Mac of their own yet" in section
