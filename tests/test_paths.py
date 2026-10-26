"""The folders of SPEC 4.1."""
import os
import stat
import sys
from pathlib import Path

import pytest

from sheafmd import paths


def test_sheaf_home_replaces_state_config_and_cache_and_never_the_runtime_folder(
        tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    h = tmp_path / "sheaf-home"
    assert paths.state_dir() == h / "state"
    assert paths.config_file() == h / "config.toml"
    assert paths.cache_dir() == h / "cache"
    assert paths.runtime_dir() == Path(os.environ["XDG_RUNTIME_DIR"]) / "sheaf"


def test_on_macos_sheaf_home_replaces_state_config_and_cache_and_never_the_runtime_folder(
        tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    h = tmp_path / "sheaf-home"
    assert paths.state_dir() == h / "state"
    assert paths.config_file() == h / "config.toml"
    assert paths.cache_dir() == h / "cache"
    assert paths.runtime_dir() == Path(f"/tmp/sheaf-{os.getuid()}")


def test_linux_follows_the_xdg_variables_then_the_home_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("SHEAF_HOME")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "s"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "k"))
    assert paths.state_dir() == tmp_path / "s" / "sheaf"
    assert paths.config_file() == tmp_path / "c" / "sheaf" / "config.toml"
    assert paths.cache_dir() == tmp_path / "k" / "sheaf"
    for v in ("XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(v)
    home = Path.home()
    assert paths.state_dir() == home / ".local" / "state" / "sheaf"
    assert paths.config_file() == home / ".config" / "sheaf" / "config.toml"
    assert paths.cache_dir() == home / ".cache" / "sheaf"


def test_a_relative_xdg_value_is_ignored(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("SHEAF_HOME")
    monkeypatch.setenv("XDG_STATE_HOME", "relative/dir")
    assert paths.state_dir() == Path.home() / ".local" / "state" / "sheaf"


def test_macos_uses_library_folders_and_a_short_runtime_path(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("SHEAF_HOME")
    lib = Path.home() / "Library"
    assert paths.state_dir() == lib / "Application Support" / "sheaf" / "state"
    assert paths.config_file() == lib / "Application Support" / "sheaf" / "config.toml"
    assert paths.cache_dir() == lib / "Caches" / "sheaf"
    # Never under Application Support: a socket path with a space can pass 104 bytes.
    assert paths.runtime_dir() == Path(f"/tmp/sheaf-{os.getuid()}")


def test_without_xdg_runtime_dir_the_runtime_folder_is_in_tmp(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert paths.runtime_dir() == Path(f"/tmp/sheaf-{os.getuid()}")


def test_a_private_dir_is_made_0700_and_a_loose_one_is_tightened(tmp_path):
    d = paths.private_dir(tmp_path / "a" / "b")
    assert d.is_dir() and stat.S_IMODE(d.stat().st_mode) == 0o700
    os.chmod(d, 0o755)
    paths.private_dir(d)
    assert stat.S_IMODE(d.stat().st_mode) == 0o700


def test_a_link_or_a_file_where_the_folder_should_be_is_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    with pytest.raises(paths.PathError):
        paths.private_dir(tmp_path / "link")
    (tmp_path / "file").write_text("x")
    with pytest.raises(FileExistsError):
        paths.private_dir(tmp_path / "file")


def test_the_locks_folder_is_private_under_the_runtime_folder():
    d = paths.locks_dir()
    assert d == paths.runtime_dir() / "locks"
    assert stat.S_IMODE(d.stat().st_mode) == 0o700 and stat.S_IMODE(d.parent.stat().st_mode) == 0o700
