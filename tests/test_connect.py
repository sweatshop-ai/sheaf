"""`sheaf connect <tiroir-url> <token>` (SPEC 9.7, 13): the token goes into the login keyring, the tiroir's library door
into Claude Code's MCP entries, and the tiroir becomes the laptop's default when it has none. Run against an in-process
hub standing in for the tiroir, in a temp home with a fake keyring: no test touches the real `~/.claude.json`, the real
keyring or the real config (premortem R7), and no token is in a fixture, a log or the output."""
import json
import os
import re
from pathlib import Path

import pytest
from helpers import BEA, CAL, FRONT, rpc

from sheafmd import config, connect, paths
from sheafmd.cli import main

TOKEN = re.compile(r"sheaf_mcp_[A-Za-z0-9_-]{43}")
SECOND = "https://second.example.com"


class FakeKeyring:
    """The login keyring, in memory."""

    def __init__(self):
        self.items = {}

    def get(self, service, user):
        return self.items.get((service, user))

    def set(self, service, user, secret):
        self.items[(service, user)] = secret


@pytest.fixture(autouse=True)
def no_real_keyring(monkeypatch):
    """Whatever a test does, the system's keyring is out of reach: asking for it fails the test."""
    def refuse():
        raise AssertionError("a test asked for the real keyring (R7): inject a FakeKeyring")
    monkeypatch.setattr(connect, "system_store", refuse)


@pytest.fixture
def keyring(monkeypatch):
    k = FakeKeyring()
    monkeypatch.setattr(connect, "system_store", lambda: k)
    return k


@pytest.fixture
def tiroir(front, plan, browser, monkeypatch):
    """The hub as the tiroir: `connect`'s probe of the door is answered by the handler, token checked as always."""
    def probe(url, token):
        assert url.startswith(FRONT) or url.startswith(SECOND)
        res = browser.request("POST", "/_/mcp", cookie=False, headers={"Authorization": f"Bearer {token}"},
                              body=rpc("initialize", {"protocolVersion": "2099-01-01", "capabilities": {},
                                                      "clientInfo": {"name": "sheaf", "version": "0"}}))
        return res.status, (res.json() if res.status == 200 else None)
    monkeypatch.setattr(connect, "probe", probe)
    return front


def laptop(tiroir, name="Work MacBook", member=BEA):
    return tiroir.post("/_/laptops", {"name": name}, member=member).json()["token"]


def claude_json():
    return Path.home() / ".claude.json"


def run(capsys, *argv):
    code = main(["connect", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_connect_stores_the_token_adds_the_door_and_makes_the_tiroir_the_default(tiroir, keyring, capsys):
    token = laptop(tiroir)
    code, out, err = run(capsys, FRONT, token)
    assert code == 0, err
    assert keyring.get("sheaf", FRONT) == token
    entry = json.loads(claude_json().read_text())["mcpServers"]["sheaf-chat.example.com"]
    assert entry == {"type": "http", "url": f"{FRONT}/mcp", "headers": {"Authorization": f"Bearer {token}"},
                     "headersHelper": "sheaf headers"}     # it names the session on a door write; it never holds the token
    assert config.read_toml(paths.config_file(), config.USER_KEYS)["tiroir"] == FRONT
    assert token not in out + err and "sheaf_mcp_" not in out + err         # the token is never printed
    assert "chat.example.com" in out


def test_a_token_the_door_does_not_know_keeps_the_default_and_the_keyring_as_they_were(tiroir, keyring, capsys, monkeypatch):
    run(capsys, FRONT, laptop(tiroir))
    other = "sheaf_mcp_" + "A" * 43
    code, _, _ = run(capsys, SECOND, other)
    assert code == 1 and keyring.get("sheaf", SECOND) is None            # refused (not a token of this hub): nothing kept
    assert config.read_toml(paths.config_file(), config.USER_KEYS)["tiroir"] == FRONT


def test_a_second_connected_tiroir_keeps_the_first_as_default_and_adds_its_own_entry(tiroir, keyring, capsys, monkeypatch):
    first = laptop(tiroir)
    run(capsys, FRONT, first)
    second = laptop(tiroir, "Home desktop")
    code, _, err = run(capsys, SECOND, second)
    assert code == 0, err
    assert config.read_toml(paths.config_file(), config.USER_KEYS)["tiroir"] == FRONT
    servers = json.loads(claude_json().read_text())["mcpServers"]
    assert set(servers) == {"sheaf-chat.example.com", "sheaf-second.example.com"}
    assert keyring.get("sheaf", FRONT) == first and keyring.get("sheaf", SECOND) == second


def test_connect_again_replaces_that_tiroirs_token_and_leaves_the_rest_of_claude_json_alone(tiroir, keyring, capsys):
    Path.home().mkdir(parents=True, exist_ok=True)
    claude_json().write_text(json.dumps({"numStartups": 3, "mcpServers": {"mine": {"type": "stdio", "command": "x"}},
                                         "projects": {"/p": {"allowedTools": []}}}))
    claude_json().chmod(0o600)
    run(capsys, FRONT, laptop(tiroir))
    new = laptop(tiroir, "Home desktop")
    assert run(capsys, FRONT, new)[0] == 0
    got = json.loads(claude_json().read_text())
    assert got["numStartups"] == 3 and got["projects"] == {"/p": {"allowedTools": []}}
    assert got["mcpServers"]["mine"] == {"type": "stdio", "command": "x"}
    assert got["mcpServers"]["sheaf-chat.example.com"]["headers"] == {"Authorization": f"Bearer {new}"}
    assert keyring.get("sheaf", FRONT) == new
    assert claude_json().stat().st_mode & 0o777 == 0o600


def test_a_default_already_in_the_config_stays_and_the_rest_of_the_config_is_kept(tiroir, keyring, capsys):
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text('name = "Ada"\ntiroir = "https://mine.example.com"\n\n[jump]\ncommand = ["x"]\n')
    run(capsys, FRONT, laptop(tiroir))
    text = paths.config_file().read_text()
    assert 'tiroir = "https://mine.example.com"' in text and FRONT not in text.split("[jump]")[0]
    assert 'name = "Ada"' in text and '[jump]\ncommand = ["x"]' in text


def test_the_default_is_written_before_the_first_table_when_the_config_has_one(tiroir, keyring, capsys):
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text('name = "Ada"\n\n[jump]\ncommand = ["x"]\n')
    run(capsys, FRONT, laptop(tiroir))
    data = config.read_toml(paths.config_file(), config.USER_KEYS)
    assert data["tiroir"] == FRONT and data["name"] == "Ada" and data["jump"] == {"command": ["x"]}


def test_a_revoked_token_is_refused_and_nothing_is_written(tiroir, keyring, capsys):
    token = laptop(tiroir)
    tiroir.post("/_/laptops/revoke", {"name": "Work MacBook"})
    code, out, err = run(capsys, FRONT, token)
    assert code == 1 and "refused" in err and token not in out + err
    assert keyring.items == {} and not claude_json().exists() and not paths.config_file().exists()


@pytest.mark.parametrize("version", ["2024-11-05", "2025-06-18", "2099-01-01"])
def test_any_door_version_is_accepted(tiroir, keyring, capsys, monkeypatch, version):
    token = laptop(tiroir)
    monkeypatch.setattr(connect, "probe", lambda url, t: (200, {"jsonrpc": "2.0", "id": 1, "result": {
        "protocolVersion": version, "capabilities": {}, "serverInfo": {"name": "door", "version": "9"}}}))
    assert run(capsys, FRONT, token)[0] == 0
    assert keyring.get("sheaf", FRONT) == token


def test_a_door_that_answers_nothing_usable_stops_the_command_and_writes_nothing(tiroir, keyring, capsys, monkeypatch):
    monkeypatch.setattr(connect, "probe", lambda url, t: (200, {"unexpected": True}))
    code, _, err = run(capsys, FRONT, laptop(tiroir))
    assert code == 1 and "door" in err
    assert keyring.items == {} and not claude_json().exists()


@pytest.mark.parametrize("url", ["chat.example.com", "http://chat.example.com", "https://", "https://a.com/x?y=1",
                                 "ftp://a.com", "https://user:pw@a.com"])
def test_a_url_that_is_not_a_tiroirs_https_address_is_refused(tiroir, keyring, capsys, url):
    code, _, err = run(capsys, url, laptop(tiroir))
    assert code == 2 and keyring.items == {} and not claude_json().exists()


def test_a_token_that_is_not_one_is_refused_before_anything_is_asked(tiroir, keyring, capsys, monkeypatch):
    monkeypatch.setattr(connect, "probe", lambda *a: pytest.fail("asked the door"))
    assert run(capsys, FRONT, "not-a-token")[0] == 2


def test_no_keyring_stops_the_command_and_says_so(tiroir, capsys, monkeypatch):
    def none():
        raise connect.ConnectError("no login keyring on this computer")
    monkeypatch.setattr(connect, "system_store", none)
    code, _, err = run(capsys, FRONT, laptop(tiroir))
    assert code == 1 and "keyring" in err and not claude_json().exists()


def test_connect_writes_only_under_the_temp_home(tiroir, keyring, capsys, tmp_path):
    """R7: whatever connect makes lands under the test's home, config and temp folders; the real home is never named."""
    real_home = Path(pwd_home())
    before = {p: p.stat().st_mtime_ns for p in (real_home / ".claude.json", real_home / ".config" / "sheaf" / "config.toml")
              if p.exists()}
    assert Path.home() == tmp_path / "home" and Path.home() != real_home
    run(capsys, FRONT, laptop(tiroir))
    made = [p for p in tmp_path.rglob("*") if p.is_file() and p.name in (".claude.json", "config.toml")]
    assert sorted(p.name for p in made) == [".claude.json", "config.toml"]
    assert all(tmp_path in p.parents for p in made)
    assert {p: p.stat().st_mtime_ns for p in before} == before
    assert list(keyring.items) == [("sheaf", FRONT)]                       # the fake took it, not the system


def test_claude_config_dir_is_where_claude_code_keeps_its_file(tiroir, keyring, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cc"))
    run(capsys, FRONT, laptop(tiroir))
    assert (tmp_path / "cc" / ".claude.json").exists() and not claude_json().exists()


def test_connect_with_a_laptop_of_another_member_reaches_only_that_members_pages(tiroir, keyring, capsys, browser):
    """What connect stored opens the door as the member the token was made for, and no other."""
    run(capsys, FRONT, laptop(tiroir, member=CAL))
    token = keyring.get("sheaf", FRONT)
    res = browser.request("POST", "/_/mcp", cookie=False, headers={"Authorization": f"Bearer {token}"},
                          body=rpc("tools/call", {"name": "read", "arguments": {"doc": "work/plan.md"}}))
    assert res.json()["result"]["isError"] is True                           # Bea's page, not Cal's


def pwd_home() -> str:
    import pwd
    return pwd.getpwuid(os.getuid()).pw_dir


# ── the adapter to the `keyring` package, on a backend of the test's own (never the system's) ───

@pytest.fixture
def own_backend():
    import keyring
    from keyring.backend import KeyringBackend

    class Memory(KeyringBackend):
        priority = 5

        def __init__(self):
            self.items = {}

        def get_password(self, service, username):
            return self.items.get((service, username))

        def set_password(self, service, username, password):
            self.items[(service, username)] = password

        def delete_password(self, service, username):
            self.items.pop((service, username), None)

    before = keyring.get_keyring()
    mine = Memory()
    keyring.set_keyring(mine)
    yield mine
    keyring.set_keyring(before)


def test_the_system_store_round_trips_through_the_keyring_package(own_backend):
    store = connect.SystemStore()
    store.set("sheaf", FRONT, "secret")
    assert store.get("sheaf", FRONT) == "secret" and own_backend.items == {("sheaf", FRONT): "secret"}


def test_a_computer_with_no_keyring_is_told_so():
    import keyring
    from keyring.backends import fail
    before = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    try:
        with pytest.raises(connect.ConnectError, match="no login keyring"):
            connect.SystemStore()
    finally:
        keyring.set_keyring(before)


def test_the_token_file_is_owner_only_even_when_it_was_looser(tiroir, keyring, capsys):
    Path.home().mkdir(parents=True, exist_ok=True)
    claude_json().write_text("{}")
    claude_json().chmod(0o644)
    assert run(capsys, FRONT, laptop(tiroir))[0] == 0
    assert claude_json().stat().st_mode & 0o777 == 0o600


def test_a_redirect_from_the_door_is_not_followed_so_the_token_stays_where_it_was_sent():
    handler = connect._Refuse3xx()
    req = connect.urllib.request.Request("https://chat.example.com/mcp", headers={"Authorization": "Bearer x"})
    assert handler.redirect_request(req, None, 307, "Temporary Redirect", {}, "http://evil.example/") is None


@pytest.mark.parametrize("url", ["https://a.com:99999", "https://a.com:abc", "https://a.com:-1"])
def test_a_bad_port_is_a_usage_error_not_a_traceback(url):
    with pytest.raises(connect.UsageError):
        connect.origin_of(url)


def test_an_ipv6_address_keeps_its_brackets_in_the_origin_and_not_in_the_entry_name():
    origin = connect.origin_of("https://[::1]:8443")
    assert origin == "https://[::1]:8443" and "[" not in connect.entry_name(origin)


@pytest.mark.parametrize("empty", ['"tiroir" = ""', "'tiroir' = ''", 'tiroir = ""\r', 'tiroir = ""', "tiroir = ''", 'tiroir = ""  # none yet', 'tiroir = """"""'])
def test_an_empty_default_in_the_config_is_filled_not_repeated(tiroir, keyring, capsys, empty):
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(f'name = "Ada"\n{empty}\n\n[jump]\ncommand = ["x"]\n')
    code, _, err = run(capsys, FRONT, laptop(tiroir))
    assert code == 0, err
    data = config.read_toml(paths.config_file(), config.USER_KEYS)       # a duplicate key would not parse
    assert data["tiroir"] == FRONT and data["name"] == "Ada" and data["jump"] == {"command": ["x"]}


def test_port_zero_is_a_usage_error_not_the_default_port():
    with pytest.raises(connect.UsageError):
        connect.origin_of("https://a.com:0")


def test_an_empty_default_written_in_a_form_sheaf_does_not_know_stops_the_command_before_anything_is_written(
        tiroir, keyring, capsys):
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text('tiroir = """\n"""\n')
    code, _, err = run(capsys, FRONT, laptop(tiroir))
    assert code == 1 and "Nothing was written" in err
    assert keyring.items == {} and not claude_json().exists()
    assert paths.config_file().read_text() == 'tiroir = """\n"""\n'


@pytest.mark.parametrize("bad", ["name = ", 'port = "x"'])
def test_a_config_that_cannot_be_read_stops_the_command_before_anything_is_written(tiroir, keyring, capsys, bad):
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(bad + "\n")
    code, _, err = run(capsys, FRONT, laptop(tiroir))
    assert code == 1 and "config.toml" in err and "Nothing was written" in err
    assert keyring.items == {} and not claude_json().exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a folder whatever its mode")
def test_a_config_folder_that_cannot_be_written_stops_the_command_before_anything_is_written(tiroir, keyring, capsys):
    folder = paths.config_file().parent
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o500)
    try:
        code, _, err = run(capsys, FRONT, laptop(tiroir))
    finally:
        folder.chmod(0o700)
    assert code == 1 and "config.toml" in err and "Nothing was written" in err
    assert keyring.items == {} and not claude_json().exists()
    assert not paths.config_file().exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into a folder whatever its mode")
def test_a_config_folder_that_cannot_be_written_does_not_matter_when_the_laptop_has_a_default_already(tiroir, keyring, capsys):
    folder = paths.config_file().parent
    folder.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text('tiroir = "https://mine.example.com"\n')
    folder.chmod(0o500)
    try:
        code, _, err = run(capsys, FRONT, laptop(tiroir))
    finally:
        folder.chmod(0o700)
    assert code == 0, err
    assert keyring.get("sheaf", FRONT) is not None
