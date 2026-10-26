"""config.toml and .sheaf.toml (SPEC 4.3, 4.4), and the root of a document (SPEC 8.2)."""
import os
import re
import subprocess
from pathlib import Path

import pytest

from sheafmd import config, paths
from sheafmd.config import ConfigError, RootConfig, UserConfig


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Nothing here may read the real git config, an ambient SHEAF_* variable, or find a
    repository above tmp_path (the cwd, so `git config user.name` cannot meet the
    checkout this suite lives in)."""
    empty = tmp_path / "git-global-empty"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.resolve()))
    for var in ("SHEAF_PORT", "SHEAF_NO_BROWSER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)


def write_config(text: str) -> Path:
    p = paths.config_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def write_root_file(root: Path, text: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    p = root / ".sheaf.toml"
    p.write_text(text, encoding="utf-8")
    return p


def git_config(tmp_path, monkeypatch, text: str):
    f = tmp_path / "git-global"
    f.write_text(text)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(f))


def git(cwd: Path, *args: str):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def make_repo_with_commit(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q")
    git(path, "-c", "user.name=Grace", "-c", "user.email=grace@example.com",
        "commit", "-q", "--allow-empty", "-m", "start")
    return path.resolve()


# ── port ────────────────────────────────────────────────────────────────────

def test_the_port_is_27419_without_an_environment_variable_or_a_file():
    assert not paths.config_file().exists()
    assert config.port() == 27419 == config.DEFAULT_PORT


def test_the_port_in_the_file_wins_over_the_default():
    write_config("port = 5000\n")
    assert config.port() == 5000


def test_sheaf_port_wins_over_the_port_in_the_file(monkeypatch):
    write_config("port = 5000\n")
    monkeypatch.setenv("SHEAF_PORT", "4000")
    assert config.port() == 4000


def test_sheaf_port_is_stripped_and_a_blank_one_is_not_set(monkeypatch):
    write_config("port = 5000\n")
    monkeypatch.setenv("SHEAF_PORT", "  4001 ")
    assert config.port() == 4001
    monkeypatch.setenv("SHEAF_PORT", "   ")
    assert config.port() == 5000


@pytest.mark.parametrize("bad", ["abc", "0", "70000", "65536", "-1", "+80", "80x", "1.5"])
def test_a_bad_sheaf_port_is_a_config_error_that_shows_the_value(monkeypatch, bad):
    monkeypatch.setenv("SHEAF_PORT", bad)
    with pytest.raises(ConfigError) as e:
        config.port()
    assert "SHEAF_PORT" in str(e.value) and repr(bad) in str(e.value)


def test_a_bad_sheaf_port_does_not_fall_through_to_the_file(monkeypatch):
    write_config("port = 5000\n")
    monkeypatch.setenv("SHEAF_PORT", "abc")
    with pytest.raises(ConfigError):
        config.port()


@pytest.mark.parametrize("edge", [1, 65535])
def test_the_ends_of_the_port_range_are_ports(monkeypatch, edge):
    monkeypatch.setenv("SHEAF_PORT", str(edge))
    assert config.port() == edge
    monkeypatch.delenv("SHEAF_PORT")
    write_config(f"port = {edge}\n")
    assert config.port() == edge


@pytest.mark.parametrize("bad", [0, 65536, -5, 100000])
def test_a_port_outside_1_to_65535_in_the_file_names_the_file(bad):
    path = write_config(f"port = {bad}\n")
    with pytest.raises(ConfigError) as e:
        config.load_user_config()
    assert str(path) in str(e.value) and "'port'" in str(e.value) and str(bad) in str(e.value)
    with pytest.raises(ConfigError):
        config.port()


def test_a_superscript_digit_in_sheaf_port_is_a_config_error_not_a_crash(monkeypatch):
    monkeypatch.setenv("SHEAF_PORT", "²")
    with pytest.raises(ConfigError):
        config.port()


# ── name ────────────────────────────────────────────────────────────────────

def test_sheaf_name_wins_over_the_name_in_the_file():
    write_config('name = "Grace"\n')
    assert os.environ["SHEAF_NAME"] == "Ada"        # set by conftest
    assert config.user_name() == "Ada"


def test_sheaf_name_is_stripped_and_a_blank_one_is_not_set(monkeypatch):
    write_config('name = "Grace"\n')
    monkeypatch.setenv("SHEAF_NAME", "  Ada  ")
    assert config.user_name() == "Ada"
    monkeypatch.setenv("SHEAF_NAME", "  ")
    assert config.user_name() == "Grace"


def test_the_name_in_the_file_wins_over_git(tmp_path, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    git_config(tmp_path, monkeypatch, "[user]\n name = Grace\n")
    write_config('name = "Katherine"\n')
    assert config.user_name() == "Katherine"


ZWSP = "\u200b"      # not printable: cleans to nothing


def test_a_sheaf_name_that_cleans_to_nothing_falls_through_to_the_file(monkeypatch):
    write_config('name = "Grace"\n')
    monkeypatch.setenv("SHEAF_NAME", ZWSP)
    assert config.user_name() == "Grace"


def test_a_name_in_the_file_that_cleans_to_nothing_falls_through_to_git(tmp_path, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    git_config(tmp_path, monkeypatch, "[user]\n name = Grace\n")
    write_config(f'name = "{ZWSP}"\n')
    assert config.user_name() == "Grace"


def test_a_git_name_that_cleans_to_nothing_falls_through_to_the_login(tmp_path, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    git_config(tmp_path, monkeypatch, f"[user]\n name = {ZWSP}\n")
    monkeypatch.setenv("USER", "login")
    assert config.user_name() == "login"


def test_a_login_that_cleans_to_nothing_falls_through_to_author(tmp_path, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    git_config(tmp_path, monkeypatch, "")
    monkeypatch.setenv("USER", ZWSP)
    monkeypatch.delenv("USERNAME", raising=False)
    assert config.user_name() == "author"


def test_username_is_tried_when_user_cleans_to_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    git_config(tmp_path, monkeypatch, "")
    monkeypatch.setenv("USER", ZWSP)
    monkeypatch.setenv("USERNAME", "ada")
    assert config.user_name() == "ada"


def test_a_git_name_that_is_not_utf8_is_read_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    f = tmp_path / "git-global"
    f.write_bytes(b"[user]\n name = Jos\xe9\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(f))
    assert config.user_name().startswith("Jos")


def test_the_name_comes_back_cleaned(monkeypatch):
    monkeypatch.setenv("SHEAF_NAME", f"  Ada{ZWSP}\n  Lovelace ")
    assert config.user_name() == "Ada Lovelace"


def test_a_long_name_is_cut_at_the_display_limit(monkeypatch):
    monkeypatch.setenv("SHEAF_NAME", "x" * 100)
    assert config.user_name() == "x" * 60


def test_without_a_name_in_the_file_git_config_user_name_is_used(tmp_path, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    git_config(tmp_path, monkeypatch, "[user]\n name = Grace\n")
    monkeypatch.setenv("USER", "login")
    assert not paths.config_file().exists()
    assert config.user_name() == "Grace"


def test_an_empty_name_in_the_file_is_not_a_name(tmp_path, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    git_config(tmp_path, monkeypatch, "[user]\n name = Grace\n")
    write_config('name = ""\n')
    assert config.user_name() == "Grace"


def test_without_a_git_name_the_login_name_is_used(tmp_path, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    git_config(tmp_path, monkeypatch, "")
    monkeypatch.setenv("USER", "login")
    assert config.user_name() == "login"


def test_without_git_installed_the_login_name_is_used(tmp_path, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    nothing = tmp_path / "empty-bin"
    nothing.mkdir()
    monkeypatch.setenv("PATH", str(nothing))
    monkeypatch.setenv("USER", "login")
    assert config.user_name() == "login"


def test_the_last_resort_for_the_name_is_author(tmp_path, monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    git_config(tmp_path, monkeypatch, "")
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)
    assert config.user_name() == "author"


# ── browser ─────────────────────────────────────────────────────────────────

def test_the_browser_is_on_by_default():
    assert config.browser_enabled() is True


def test_sheaf_no_browser_1_turns_it_off(monkeypatch):
    monkeypatch.setenv("SHEAF_NO_BROWSER", "1")
    assert config.browser_enabled() is False


def test_sheaf_no_browser_1_turns_it_off_even_when_the_file_says_true(monkeypatch):
    write_config("browser = true\n")
    monkeypatch.setenv("SHEAF_NO_BROWSER", "1")
    assert config.browser_enabled() is False


def test_browser_false_in_the_file_turns_it_off():
    write_config("browser = false\n")
    assert config.browser_enabled() is False


def test_browser_true_in_the_file_leaves_it_on():
    write_config("browser = true\n")
    assert config.browser_enabled() is True


def test_sheaf_no_browser_0_does_not_turn_it_off(monkeypatch):
    monkeypatch.setenv("SHEAF_NO_BROWSER", "0")
    assert config.browser_enabled() is True


def test_sheaf_no_browser_0_does_not_override_browser_false_in_the_file(monkeypatch):
    write_config("browser = false\n")
    monkeypatch.setenv("SHEAF_NO_BROWSER", "0")
    assert config.browser_enabled() is False


# ── the file: unknown keys, TOML errors, wrong types, a missing file ────────

def test_an_unknown_key_warns_with_the_path_and_the_key():
    path = write_config('port = 5000\ncolour = "red"\n')
    warned = []
    cfg = config.load_user_config(warned.append)
    assert len(warned) == 1
    assert str(path) in warned[0] and "colour" in warned[0]
    assert cfg == UserConfig(port=5000, name=None, browser=None)     # the known keys still count


def test_a_known_key_does_not_warn():
    write_config('port = 5000\nname = "Grace"\nbrowser = false\n')
    warned = []
    cfg = config.load_user_config(warned.append)
    assert warned == []
    assert cfg == UserConfig(port=5000, name="Grace", browser=False)


def test_the_warning_reaches_the_caller_through_port_name_and_browser(monkeypatch):
    monkeypatch.delenv("SHEAF_NAME")
    path = write_config('colour = "red"\n')
    for call in (config.port, config.user_name, config.browser_enabled):
        warned = []
        call(warned.append)
        assert len(warned) == 1 and str(path) in warned[0] and "colour" in warned[0], call.__name__


def test_without_a_warn_the_warning_goes_to_stderr(capsys):
    path = write_config('colour = "red"\n')
    config.load_user_config()
    out, err = capsys.readouterr()
    assert out == ""
    assert str(path) in err and "colour" in err and err.endswith("\n")


@pytest.mark.parametrize("text,line", [
    ('port = 8080\nname = "Ada"\nbrowser = = true\n', 3),
    ('# a\n# b\n# c\n# d\nname = "unclosed\n', 5),
])
def test_a_toml_error_names_the_file_and_the_line(text, line):
    path = write_config(text)
    with pytest.raises(ConfigError) as e:
        config.load_user_config()
    msg = str(e.value)
    assert str(path) in msg
    assert re.search(rf"\bline {line}\b", msg), msg


def test_a_toml_error_stops_port_too():
    write_config("port = 8080\nname = \nbrowser = true\n")
    with pytest.raises(ConfigError) as e:
        config.port()
    assert str(paths.config_file()) in str(e.value) and "line 2" in str(e.value)


@pytest.mark.parametrize("text,key", [
    ('port = "x"\n', "port"),
    ("port = 80.5\n", "port"),
    ("port = true\n", "port"),            # a bool is not a port
    ('browser = "yes"\n', "browser"),
    ("browser = 1\n", "browser"),
    ("name = 5\n", "name"),
    ("name = true\n", "name"),
])
def test_a_key_of_the_wrong_type_names_the_file_and_the_key(text, key):
    path = write_config(text)
    with pytest.raises(ConfigError) as e:
        config.load_user_config()
    assert str(path) in str(e.value) and f"'{key}'" in str(e.value)


def test_port_true_is_refused_not_read_as_port_1():
    write_config("port = true\n")
    with pytest.raises(ConfigError):
        config.port()


def test_a_missing_config_file_gives_the_defaults_and_no_error(capsys):
    assert not paths.config_file().exists()
    assert config.load_user_config() == UserConfig(port=None, name=None, browser=None)
    assert config.port() == 27419
    assert config.browser_enabled() is True
    assert capsys.readouterr() == ("", "")


def test_an_empty_config_file_gives_the_defaults(capsys):
    write_config("")
    assert config.load_user_config() == UserConfig()
    assert capsys.readouterr() == ("", "")


def test_a_file_that_is_not_utf8_is_refused_naming_it():
    p = paths.config_file()
    p.parent.mkdir(parents=True)
    p.write_bytes(b'name = "\xff\xfe"\n')
    with pytest.raises(ConfigError) as e:
        config.load_user_config()
    assert str(p) in str(e.value) and "UTF-8" in str(e.value)


def test_a_config_file_that_is_a_folder_is_refused_naming_it():
    p = paths.config_file()
    p.mkdir(parents=True)
    with pytest.raises(ConfigError) as e:
        config.load_user_config()
    assert str(p) in str(e.value) and "cannot be read" in str(e.value)


# ── .sheaf.toml ─────────────────────────────────────────────────────────────

def test_without_the_file_the_root_defaults_apply(tmp_path, capsys):
    root = tmp_path / "root"
    root.mkdir()
    cfg = config.load_root_config(root)
    assert cfg == RootConfig()
    assert (cfg.theme, cfg.for_, cfg.links, cfg.link_tlds, cfg.credit) == (None, None, True, (), False)
    assert capsys.readouterr() == ("", "")


def test_an_empty_root_file_gives_the_defaults(tmp_path):
    write_root_file(tmp_path / "root", "")
    assert config.load_root_config(tmp_path / "root") == RootConfig()


@pytest.mark.parametrize("line,field,value", [
    ('theme = ".sheaf/theme-brand"', "theme", ".sheaf/theme-brand"),
    ('theme = "plain"', "theme", "plain"),
    ('for = "Example Co"', "for_", "Example Co"),
    ("links = false", "links", False),
    ("links = true", "links", True),
    ('link_tlds = ["example", "studio"]', "link_tlds", ("example", "studio")),
    ("credit = true", "credit", True),
])
def test_each_root_key_is_read(tmp_path, line, field, value):
    write_root_file(tmp_path / "root", line + "\n")
    cfg = config.load_root_config(tmp_path / "root")
    assert getattr(cfg, field) == value
    others = {f: getattr(RootConfig(), f) for f in ("theme", "for_", "links", "link_tlds", "credit")
              if f != field}
    assert {f: getattr(cfg, f) for f in others} == others       # nothing else moved


def test_every_root_key_together(tmp_path):
    write_root_file(tmp_path / "root", (
        'theme = ".sheaf/theme-brand"\nfor = "Example Co"\nlinks = false\n'
        'link_tlds = ["example", "studio"]\ncredit = true\n'))
    assert config.load_root_config(tmp_path / "root") == RootConfig(
        theme=".sheaf/theme-brand", for_="Example Co", links=False,
        link_tlds=("example", "studio"), credit=True)


def test_an_empty_theme_or_for_is_none(tmp_path):
    write_root_file(tmp_path / "root", 'theme = ""\nfor = ""\n')
    cfg = config.load_root_config(tmp_path / "root")
    assert cfg.theme is None and cfg.for_ is None


def test_link_tlds_are_lowercased_and_lose_their_dot_and_a_bad_one_warns_naming_the_file(tmp_path):
    path = write_root_file(tmp_path / "root", 'link_tlds = ["EXAMPLE", ".studio", "a b"]\n')
    warned = []
    cfg = config.load_root_config(tmp_path / "root", warned.append)
    assert cfg.link_tlds == ("example", "studio")
    assert len(warned) == 1
    assert str(path) in warned[0] and "a b" in warned[0] and "link_tlds" in warned[0]


def test_a_bad_link_tld_warns_on_stderr_without_a_warn(tmp_path, capsys):
    path = write_root_file(tmp_path / "root", 'link_tlds = ["a b"]\n')
    assert config.load_root_config(tmp_path / "root").link_tlds == ()
    err = capsys.readouterr().err
    assert str(path) in err and "a b" in err


def test_an_unknown_root_key_warns_naming_the_file_and_the_key(tmp_path):
    path = write_root_file(tmp_path / "root", 'for = "Example Co"\nbyline = "x"\n')
    warned = []
    cfg = config.load_root_config(tmp_path / "root", warned.append)
    assert len(warned) == 1 and str(path) in warned[0] and "byline" in warned[0]
    assert cfg.for_ == "Example Co"


def test_an_unknown_root_key_goes_to_stderr_without_a_warn(tmp_path, capsys):
    path = write_root_file(tmp_path / "root", 'byline = "x"\n')
    config.load_root_config(tmp_path / "root")
    err = capsys.readouterr().err
    assert str(path) in err and "byline" in err


def test_a_toml_error_in_the_root_file_names_the_file_and_the_line(tmp_path):
    path = write_root_file(tmp_path / "root", 'theme = "plain"\nlinks = false\ncredit = = true\n')
    with pytest.raises(ConfigError) as e:
        config.load_root_config(tmp_path / "root")
    assert str(path) in str(e.value) and re.search(r"\bline 3\b", str(e.value))


@pytest.mark.parametrize("text,key", [
    ('links = "yes"\n', "links"),
    ("links = 1\n", "links"),
    ("credit = 1\n", "credit"),
    ("theme = 5\n", "theme"),
    ("for = 7\n", "for"),
    ('link_tlds = "example"\n', "link_tlds"),
])
def test_a_root_key_of_the_wrong_type_names_the_file_and_the_key(tmp_path, text, key):
    path = write_root_file(tmp_path / "root", text)
    with pytest.raises(ConfigError) as e:
        config.load_root_config(tmp_path / "root")
    assert str(path) in str(e.value) and f"'{key}'" in str(e.value)


def test_load_root_config_reads_the_folder_it_is_given_and_never_looks_upward(tmp_path):
    root = tmp_path / "root"
    write_root_file(root, "credit = true\n")
    (root / "sub").mkdir()
    assert config.load_root_config(root).credit is True
    assert config.load_root_config(root / "sub") == RootConfig()     # no file there: defaults
    write_root_file(root / "sub", 'for = "Sub Co"\n')
    assert config.load_root_config(root / "sub") == RootConfig(for_="Sub Co")


# ── find_root, and the file only at the top of a root ──────────────────────

def test_inside_a_git_work_tree_the_root_is_the_top_of_it(tmp_path):
    repo = make_repo_with_commit(tmp_path / "repo")
    (repo / "notes" / "deep").mkdir(parents=True)
    assert config.find_root(repo / "notes" / "deep" / "doc.md") == repo
    assert config.find_root(repo / "notes" / "doc.md") == repo
    assert config.find_root(repo / "doc.md") == repo


def test_a_git_worktree_is_its_own_root(tmp_path):
    repo = make_repo_with_commit(tmp_path / "repo")
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", str(wt), "-b", "side")
    (wt / "sub").mkdir()
    (repo / "sub").mkdir()
    assert config.find_root(wt / "sub" / "doc.md") == wt.resolve()
    assert config.find_root(wt / "doc.md") == wt.resolve()
    assert config.find_root(repo / "sub" / "doc.md") == repo      # and the main one stays itself
    assert wt.resolve() != repo


def test_each_worktree_reads_its_own_root_file(tmp_path):
    repo = make_repo_with_commit(tmp_path / "repo")
    (repo / ".sheaf.toml").write_text('for = "Example Co"\n')
    git(repo, "add", ".sheaf.toml")
    git(repo, "-c", "user.name=Grace", "-c", "user.email=grace@example.com",
        "commit", "-q", "-m", "root file")
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", str(wt), "-b", "side")
    (wt / ".sheaf.toml").write_text('for = "Other Co"\n')
    assert config.load_root_config(config.find_root(repo / "doc.md")).for_ == "Example Co"
    assert config.load_root_config(config.find_root(wt / "doc.md")).for_ == "Other Co"


def test_outside_git_the_root_is_the_documents_own_folder(tmp_path):
    folder = tmp_path / "loose" / "notes"
    folder.mkdir(parents=True)
    assert config.find_root(folder / "doc.md") == folder.resolve()


def test_a_relative_document_path_is_resolved_first(tmp_path, monkeypatch):
    folder = tmp_path / "loose"
    folder.mkdir()
    monkeypatch.chdir(folder)
    assert config.find_root(Path("doc.md")) == folder.resolve()


def test_without_git_installed_the_root_is_the_documents_own_folder(tmp_path, monkeypatch):
    repo = make_repo_with_commit(tmp_path / "repo")
    (repo / "sub").mkdir()
    nothing = tmp_path / "empty-bin"
    nothing.mkdir()
    monkeypatch.setenv("PATH", str(nothing))
    assert config.find_root(repo / "sub" / "doc.md") == (repo / "sub").resolve()


def test_a_document_in_a_subfolder_of_a_repo_gets_the_root_file_at_the_top_not_the_one_beside_it(tmp_path):
    repo = make_repo_with_commit(tmp_path / "repo")
    (repo / ".sheaf.toml").write_text('for = "Top Co"\ncredit = true\nlinks = false\n')
    write_root_file(repo / "sub", 'for = "Sub Co"\ncredit = false\nlinks = true\n')
    root = config.find_root(repo / "sub" / "doc.md")
    assert root == repo
    cfg = config.load_root_config(root)
    assert cfg == RootConfig(for_="Top Co", credit=True, links=False)


def test_a_document_in_a_subfolder_of_a_repo_with_no_top_file_gets_the_defaults(tmp_path):
    repo = make_repo_with_commit(tmp_path / "repo")
    write_root_file(repo / "sub", 'for = "Sub Co"\n')
    assert config.load_root_config(config.find_root(repo / "sub" / "doc.md")) == RootConfig()


def test_a_document_outside_git_reads_the_file_in_its_own_folder_not_the_parents(tmp_path):
    write_root_file(tmp_path / "loose", 'for = "Parent Co"\n')
    write_root_file(tmp_path / "loose" / "mine", 'for = "My Co"\n')
    root = config.find_root(tmp_path / "loose" / "mine" / "doc.md")
    assert root == (tmp_path / "loose" / "mine").resolve()
    assert config.load_root_config(root).for_ == "My Co"
    (tmp_path / "loose" / "mine" / ".sheaf.toml").unlink()
    assert config.load_root_config(root) == RootConfig()            # the parent's is not consulted


def test_tell_wait_is_600_seconds_unless_sheaf_tell_wait_says_otherwise(monkeypatch):
    monkeypatch.delenv("SHEAF_TELL_WAIT", raising=False)
    assert config.tell_wait() == 600
    monkeypatch.setenv("SHEAF_TELL_WAIT", " 30 ")
    assert config.tell_wait() == 30
    monkeypatch.setenv("SHEAF_TELL_WAIT", "  ")
    assert config.tell_wait() == 600


@pytest.mark.parametrize("bad", ["abc", "0", "-5", "1.5", "²"])
def test_a_bad_sheaf_tell_wait_is_a_config_error_that_shows_the_value(monkeypatch, bad):
    monkeypatch.setenv("SHEAF_TELL_WAIT", bad)
    with pytest.raises(ConfigError) as e:
        config.tell_wait()
    assert "SHEAF_TELL_WAIT" in str(e.value) and repr(bad) in str(e.value)
