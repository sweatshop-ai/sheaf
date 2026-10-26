"""On native Windows (SPEC 14.2) every command except --share, comments, comment, reply, resolve,
reopen and version stops with one sentence and exit 1. The platform is faked at the one place the
command reads it: `sys.platform` itself would also change what the libraries do. These tests run
on Linux and macOS."""
import pytest

from sheafmd import cli
from sheafmd.cli import main

SAYING = "sheaf supports Linux and macOS. On Windows, use WSL2 (untested)."


@pytest.fixture
def windows(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_platform", lambda: "win32")
    (tmp_path / "work").mkdir()
    doc = tmp_path / "work" / "doc.md"
    doc.write_text("# Title\n\nA paragraph.\n", encoding="utf-8")
    return doc


@pytest.mark.parametrize("argv", [
    ["open", "{doc}"], ["{doc}"], ["{doc}", "--title", "T"], ["start"], ["stop"], ["status"], ["hub"],
    ["restart"], ["rotate"], ["signin-url"], ["service", "install"], ["init", "claude"], ["mcp"],
    ["token", "list"], ["list"], ["roots"], ["diag"],
])
def test_a_command_that_needs_the_hub_or_the_system_stops_on_windows(windows, capsys, argv):
    argv = [a.replace("{doc}", str(windows)) for a in argv]
    assert main(argv) == 1
    out = capsys.readouterr()
    assert out.err.strip() == SAYING and out.out == ""
    assert sorted(p.name for p in windows.parent.iterdir()) == ["doc.md"]


@pytest.mark.parametrize("argv", [
    ["{doc}", "--share"], ["comments", "{doc}"], ["version"],
    ["comment", "{doc}", "A paragraph.", "a note"],
])
def test_the_commands_that_need_no_hub_still_run_on_windows(windows, capsys, argv):
    argv = [a.replace("{doc}", str(windows)) for a in argv]
    assert main(argv) == 0
    assert SAYING not in capsys.readouterr().err


def test_the_help_still_prints_on_windows(windows, capsys):
    assert main(["--help"]) == 0
    assert "usage:" in capsys.readouterr().out


def test_other_platforms_are_not_stopped(monkeypatch, capsys):
    for platform in ("linux", "darwin"):
        monkeypatch.setattr(cli, "_platform", lambda: platform)
        assert main(["version"]) == 0
        assert SAYING not in capsys.readouterr().err
