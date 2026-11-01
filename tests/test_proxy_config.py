"""The `[proxy]` table of config.toml (SPEC 4.3, 9.9 "Switching it on"): the one switch of proxy
mode. Every key 9.9 names is required, and a missing, unknown or wrong one stops the hub's start
instead of printing a warning, so the hub never runs with part of the mode."""
import getpass
import os
import pwd
import re
import textwrap

import pytest

from sheafmd import config, paths
from sheafmd.hub import proxy
from sheafmd.hub.proxy import ProxyError

ADA = "0f8fad5b-d9cb-469f-a165-70867728950e"
BOB = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
ME = getpass.getuser()


def write_config(text: str):
    p = paths.config_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return p


def table(**over):
    """A whole `[proxy]` table as TOML, with `over` replacing or (as None) leaving out a key."""
    keys = {"origin": '"https://chat.example.com"', "socket": '"/run/sheaf-proxy/hub.sock"',
            "proxy_user": f'"{ME}"'}
    keys.update(over)
    head = "".join(f"{k} = {v}\n" for k, v in keys.items() if v is not None)
    return ("[proxy]\n" + head + f'\n[proxy.members."{ADA}"]\nname = "Ada"\nroots = ["/srv/pages/mails"]\n')


def test_without_the_table_there_is_no_proxy_mode():
    write_config('port = 27500\nname = "Grace"\n')
    assert proxy.load() is None


def test_a_whole_table_is_read():
    write_config(table() + f'\n[proxy.members."{BOB}"]\nname = "Bob"\nroots = ["/srv/a", "/srv/b/"]\n')
    got = proxy.load()
    assert got.origin == "https://chat.example.com" and got.host == "chat.example.com"
    assert str(got.socket) == "/run/sheaf-proxy/hub.sock"
    assert got.proxy_user == ME and got.uid == os.getuid() and got.gid == pwd.getpwnam(ME).pw_gid
    assert got.members == {ADA: proxy.Member(ADA, "Ada", ("/srv/pages/mails",)),
                           BOB: proxy.Member(BOB, "Bob", ("/srv/a", "/srv/b"))}


def test_the_table_does_not_warn_as_an_unknown_key_of_the_file():
    warned = []
    write_config('name = "Grace"\n' + table())
    assert config.load_user_config(warned.append).name == "Grace"
    assert warned == []


# ── what stops the start ─────────────────────────────────────────────────────

def refused(text):
    write_config(text)
    with pytest.raises(ProxyError) as e:
        proxy.load()
    return str(e.value)


@pytest.mark.parametrize("key", ["origin", "socket", "proxy_user"])
def test_a_missing_key_stops_the_start(key):
    assert f"'{key}' is missing" in refused(table(**{key: None}))


def test_no_member_stops_the_start():
    text = '[proxy]\norigin = "https://chat.example.com"\nsocket = "/run/x/hub.sock"\n' \
           f'proxy_user = "{ME}"\n'
    assert "no member" in refused(text)
    assert "no member" in refused(text + "[proxy.members]\n")


def test_an_unknown_key_stops_the_start_and_names_it():
    msg = refused(table(port="27420"))
    assert "unknown key 'port' in [proxy]" in msg and str(paths.config_file()) in msg
    assert "unknown key 'colour'" in refused(table() + 'colour = "red"\n')


@pytest.mark.parametrize("key, value, words", [
    ("origin", "3", "'origin' must be text"),
    ("socket", "true", "'socket' must be text"),
    ("proxy_user", '["caddy"]', "'proxy_user' must be text"),
    ("members", '"Ada"', "'members' must be a table"),
])
def test_a_key_of_the_wrong_type_stops_the_start(key, value, words):
    assert words in refused(table(**{key: value}).replace(f'\n[proxy.members."{ADA}"]', "\n[other]")
                            if key == "members" else table(**{key: value}))


@pytest.mark.parametrize("origin", [
    "http://chat.example.com", "https://chat.example.com/", "https://chat.example.com/app",
    "https://chat.example.com?x=1", "https://ada@chat.example.com", "https://", "chat.example.com",
    "https://chat.example.com:0", "https://chat.example.com:99999", "https://chat example.com",
    "https://chat.example.com#top",
])
def test_an_origin_that_is_not_https_a_host_and_a_port_at_most_stops_the_start(origin):
    assert "'origin'" in refused(table(origin=f'"{origin}"'))


@pytest.mark.parametrize("origin, host", [
    ("https://Chat.Example.com", "chat.example.com"),
    ("https://chat.example.com:8443", "chat.example.com:8443"),
    ("https://[::1]:8443", "[::1]:8443"),
    ("https://chat.example.com:443", "chat.example.com"),        # a browser names 443 by no port
])
def test_the_host_every_request_must_name_is_the_origins_with_its_port(origin, host):
    write_config(table(origin=f'"{origin}"'))
    got = proxy.load()
    assert got.host == host and got.origin == "https://" + host


def test_a_socket_that_is_not_an_absolute_path_stops_the_start():
    assert "'socket' must be an absolute path" in refused(table(socket='"run/hub.sock"'))
    assert "'socket'" in refused(table(socket='"/' + "x" * 120 + '/hub.sock"'))   # past the 107 bytes of AF_UNIX


def test_a_proxy_user_that_is_no_account_stops_the_start():
    assert "'proxy_user'" in refused(table(proxy_user='"no-such-account-sheaf"'))


@pytest.mark.parametrize("member, words", [
    ('roots = ["/srv/x"]\n', "'name' is missing"),
    ('name = "Ada"\n', "'roots' is missing"),
    ('name = "Ada"\nroots = ["/srv/x"]\nrole = "admin"\n', "unknown key 'role'"),
    ('name = 7\nroots = ["/srv/x"]\n', "'name' must be text"),
    ('name = "Ada"\nroots = "/srv/x"\n', "'roots' must be a list"),
    ('name = "Ada"\nroots = []\n', "'roots' must name at least one folder"),
    ('name = "Ada"\nroots = ["srv/x"]\n', "absolute"),
    ('name = "Ada"\nroots = [3]\n', "absolute"),
    ('name = " \\t "\nroots = ["/srv/x"]\n', "'name'"),
])
def test_a_member_that_is_not_as_9_9_says_stops_the_start(member, words):
    text = ('[proxy]\norigin = "https://chat.example.com"\nsocket = "/run/x/hub.sock"\n'
            f'proxy_user = "{ME}"\n[proxy.members."{ADA}"]\n' + member)
    msg = refused(text)
    assert words in msg and ADA in msg


def test_a_member_entry_that_is_not_a_table_stops_the_start():
    text = ('[proxy]\norigin = "https://chat.example.com"\nsocket = "/run/x/hub.sock"\n'
            f'proxy_user = "{ME}"\nmembers = {{ "{ADA}" = "Ada" }}\n')
    assert ADA in refused(text)


def test_a_member_name_is_cleaned_by_the_rule_of_12():
    write_config(table().replace('name = "Ada"', 'name = "  Ada\\u0007  Lovelace\\n"'))
    assert proxy.load().members[ADA].name == "Ada Lovelace"


# ── the name rules: a comment's name is the only record of its author (5.2) ─

def members(*names):
    body = "".join(f'\n[proxy.members."id-{i}"]\nname = "{n}"\nroots = ["/srv/{i}"]\n'
                   for i, n in enumerate(names))
    write_config('[proxy]\norigin = "https://chat.example.com"\nsocket = "/run/x/hub.sock"\n'
                 f'proxy_user = "{ME}"\n' + body)
    return proxy.load()


def test_names_that_differ_from_everyone_pass():
    proxy.check_names(members("Ada", "Bob"), person="Grace", tokens=["Codex helper"])


@pytest.mark.parametrize("names, person, tokens, words", [
    (("Ada", "Ada"), "Grace", [], "another member"),
    (("Ada", "ada"), "Grace", [], "another member"),
    (("Ada", " Ada "), "Grace", [], "another member"),           # the same once cleaned
    (("Grace",), "Grace", [], "the hub's person"),
    (("grace",), "Grace", [], "the hub's person"),
    (("Helper",), "Grace", ["Helper"], "an MCP token"),
    (("Claude",), "Grace", [], "an agent"),
    (("Codex",), "Grace", [], "an agent"),
    (("Gemini",), "Grace", [], "an agent"),
    (("Cursor",), "Grace", [], "an agent"),
    (("opencode",), "Grace", [], "an agent"),
    (("sheaf",), "Grace", [], "sheaf"),                             # the author of merge notes
    (("Ada (action)",), "Grace", [], "(action)"),
    (("Ada (ACTION)",), "Grace", [], "(action)"),
])
def test_a_name_that_could_pass_for_someone_else_stops_the_start(names, person, tokens, words):
    with pytest.raises(ProxyError) as e:
        proxy.check_names(members(*names), person=person, tokens=tokens)
    assert words in str(e.value)


def test_a_member_names_the_door_tokens_that_act_for_them():
    write_config(table() + 'tokens = ["james-ada", "mistral-ada"]\n')
    cfg = proxy.load()
    assert cfg.member_of_token("james-ada").id == ADA and cfg.member_of_token("james") is None


def test_a_member_without_tokens_still_starts_and_binds_no_token():
    write_config(table())
    assert proxy.load().members[ADA].tokens == ()


@pytest.mark.parametrize("value", ['"james"', '["a b"]', "[1]", f'["{"x" * 41}"]'])
def test_tokens_that_are_not_a_list_of_token_names_stop_the_start(value):
    write_config(table() + f"tokens = {value}\n")
    with pytest.raises(ProxyError, match="'tokens' must be a list of token names"):
        proxy.load()


def test_a_token_that_acts_for_two_members_stops_the_start():
    write_config(table() + 'tokens = ["james"]\n'
                 f'\n[proxy.members."{BOB}"]\nname = "Bob"\nroots = ["/srv/pages/bob"]\ntokens = ["james"]\n')
    with pytest.raises(ProxyError, match="acts for another member already"):
        proxy.load()


def test_member_ids_a_mail_address_cannot_hold_each_get_their_own_commit_email():
    """#38: every such id was `member@<host>`, so their commits were one person's."""
    a, b = proxy.default_email("auth0|123", "https://chat.example.com"), \
        proxy.default_email("auth0|456", "https://chat.example.com")
    assert a != b
    assert a == proxy.default_email("auth0|123", "https://chat.example.com")
    for mail in (a, b):
        local, _, host = mail.partition("@")
        assert host == "chat.example.com" and re.fullmatch(r"[A-Za-z0-9._+-]+", local)
    assert proxy.default_email(ADA, "https://chat.example.com") == f"{ADA}@chat.example.com"
    taken = a.partition("@")[0]                          # an id chosen to read as another's hashed address
    assert proxy.default_email(taken, "https://chat.example.com") != a
    assert proxy.default_email(taken.capitalize(), "https://chat.example.com").lower() != a   # e-mails compare in lower case
