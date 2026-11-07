"""An agent's token (SPEC 9.7, D27): its replies are signed `<client> (<member>)`, built by sheaf.
The signature is read off the file after a reply through the HTTP door, in memory. The CLI and the
token store are judged beside it."""
import json
import os
import pwd

import pytest

import sheafmd.comments as rdc
from helpers import BEA, FRONT, comment, ok
from sheafmd import paths
from sheafmd.hub import proxy
from sheafmd.hub.auth import CLIENT_MAX
from sheafmd.hub.state import TokenError, Tokens

DOC = "work/plan.md"


@pytest.fixture
def talk(plan):
    comment(plan)
    return plan


def last_by(path):
    return rdc.parse(path.read_text(encoding="utf-8")).by_id("c1").replies[-1].by


def reply(browser, token, text="Done."):
    ok(browser, "reply", doc=DOC, id="c1", text=text, token=token)


def members(work, bea_name="Bea", tokens=()):
    return proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                        "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                        "members": {BEA: {"name": bea_name, "roots": [str(work)], "tokens": list(tokens)}}}, "the test")


# ── the signature, over the door ─────────────────────────────────────────────

def test_a_reply_by_an_agent_of_a_member_is_signed_client_and_member(browser, talk, work):
    chatgpt = Tokens().add("bea-chatgpt", client="ChatGPT")
    unknown = Tokens().add("bea-ai", client="AI")
    browser.hub.proxy = members(work, tokens=["bea-chatgpt", "bea-ai"])
    reply(browser, chatgpt)
    assert last_by(talk) == "ChatGPT (Bea)"
    reply(browser, unknown)
    assert last_by(talk) == "AI (Bea)"


def test_renaming_the_member_changes_the_signature_after_a_restart(browser, talk, work):
    token = Tokens().add("bea-chatgpt", client="ChatGPT")
    browser.hub.proxy = members(work, bea_name="Beatrice", tokens=["bea-chatgpt"])
    reply(browser, token)
    assert last_by(talk) == "ChatGPT (Beatrice)"


def test_in_loopback_mode_an_agent_signs_with_the_hubs_person_and_never_as_the_bare_person(browser, talk):
    token = Tokens().add("ada-chatgpt", client="ChatGPT")
    assert browser.hub.proxy is None
    reply(browser, token)
    assert last_by(talk) == f"ChatGPT ({browser.hub.person})" != browser.hub.person


def test_an_agent_no_member_names_signs_with_the_hubs_person(browser, talk, work):
    token = Tokens().add("stray", client="ChatGPT")
    browser.hub.proxy = members(work, tokens=[])
    reply(browser, token)
    assert last_by(talk) == f"ChatGPT ({browser.hub.person})"


def test_a_token_made_before_agents_signs_as_it_always_did_and_is_no_agent(browser, talk, work):
    old = Tokens().add("codex", "Codex")
    browser.hub.proxy = members(work, tokens=["codex"])         # even bound to a member
    reply(browser, old)
    assert last_by(talk) == "Codex"
    row = Tokens().verify(old)
    assert row.client is None and row.display == "Codex"


# ── the token store ──────────────────────────────────────────────────────────

def stored():
    return json.loads(Tokens.path().read_text(encoding="utf-8"))


def test_the_row_of_an_agent_stores_the_client_and_no_display(work):
    Tokens().add("bea-chatgpt", client="ChatGPT")
    [row] = stored()
    assert row["client"] == "ChatGPT" and "display" not in row and row["write"] is False


@pytest.mark.parametrize("given,kept", [("  Chat   GPT ", "Chat GPT"), ("Claude\x07", "Claude"), ("x" * CLIENT_MAX, "x" * CLIENT_MAX)])
def test_the_client_is_cleaned_by_the_display_name_rule(given, kept):
    Tokens().add("t", client=given)
    assert stored()[0]["client"] == kept


@pytest.mark.parametrize("given", ["", "  ", "\x00", "x" * (CLIENT_MAX + 1), "Chat(GPT)", "Chat)", "(", "é" * (CLIENT_MAX + 1)])
def test_a_client_that_is_empty_too_long_or_holds_a_parenthesis_is_refused(given):
    with pytest.raises(TokenError, match="client"):
        Tokens().add("t", client=given)
    assert Tokens().list() == []


def test_a_client_and_a_display_together_are_refused():
    with pytest.raises(TokenError, match="client"):
        Tokens().add("t", "Codex", client="ChatGPT")


def test_a_row_with_neither_display_nor_client_loads_and_is_listed_as_invalid(browser):
    p = Tokens.path()
    p.write_text(json.dumps([{"name": "bare", "sha256": "0" * 64}]), encoding="utf-8")
    [row] = Tokens().list()
    assert row.name == "bare" and row.display is None and row.client is None and row.invalid


def test_an_agents_row_has_no_display_which_the_previous_reader_requires_so_it_refuses_it():
    """The old reader wants a `display` of every row; an agent's has none, so it answers 401, never a wrong name."""
    token = Tokens().add("t", client="ChatGPT")
    row = stored()[0]
    assert "display" not in row                                 # what the previous `_row_addable` demands
    assert Tokens().verify(token).client == "ChatGPT"


# ── the CLI ──────────────────────────────────────────────────────────────────

def test_add_with_client_prints_the_name_it_signs_with_and_list_shows_client_and_name(sheaf):
    r = sheaf("token", "add", "ada-chatgpt", "--client", "ChatGPT")
    assert r.code == 0 and "'ChatGPT (Ada)'" in r.out
    listed = sheaf("token", "list").out
    assert "ChatGPT" in listed and "ChatGPT (Ada)" in listed


def test_add_with_client_and_as_is_refused(sheaf):
    r = sheaf("token", "add", "t", "--client", "ChatGPT", "--as", "X")
    assert r.code != 0 and Tokens().list() == []


def test_add_says_the_name_a_member_gives_it(sheaf, work):
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(
        f'[proxy]\norigin = "{FRONT}"\nsocket = "/run/sheaf-proxy/hub.sock"\n'
        f'proxy_user = "{pwd.getpwuid(os.getuid()).pw_name}"\n'
        f'[proxy.members."{BEA}"]\nname = "Bea"\nroots = ["{work}"]\ntokens = ["bea-chatgpt"]\n', encoding="utf-8")
    assert "'ChatGPT (Bea)'" in sheaf("token", "add", "bea-chatgpt", "--client", "ChatGPT").out


@pytest.mark.parametrize("client", ["Bea", "bea", "BEA", "Béa", "Ｂｅａ", "Bea "])
def test_add_refuses_a_client_that_passes_for_a_member_by_case_accent_or_width(sheaf, work, client):
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(
        f'[proxy]\norigin = "{FRONT}"\nsocket = "/run/sheaf-proxy/hub.sock"\n'
        f'proxy_user = "{pwd.getpwuid(os.getuid()).pw_name}"\n'
        f'[proxy.members."{BEA}"]\nname = "Bea"\nroots = ["{work}"]\n', encoding="utf-8")
    r = sheaf("token", "add", "t", "--client", client)
    assert r.code != 0 and "Bea" in r.err and Tokens().list() == []


@pytest.mark.parametrize("client", ["Ada", "ada", "Ａｄａ"])
def test_add_refuses_a_client_that_passes_for_the_hubs_person(sheaf, client):
    r = sheaf("token", "add", "t", "--client", client)
    assert r.code != 0 and Tokens().list() == []


def test_add_refuses_a_client_whose_built_name_is_another_tokens_display(sheaf):
    sheaf("token", "add", "old", "--as", "ChatGPT (Ada)")
    r = sheaf("token", "add", "new", "--client", "ChatGPT")
    assert r.code != 0 and [t.name for t in Tokens().list()] == ["old"]
    r = sheaf("token", "add", "other", "--client", "CHATGPT")           # case alone does not tell them apart
    assert r.code != 0


def test_add_refuses_a_second_token_that_would_sign_the_same_name(sheaf):
    assert sheaf("token", "add", "one", "--client", "ChatGPT").code == 0
    assert sheaf("token", "add", "two", "--client", "chatgpt").code != 0


def test_add_refuses_a_typed_display_that_is_the_name_an_agent_signs_with(sheaf):
    assert sheaf("token", "add", "one", "--client", "ChatGPT").code == 0
    r = sheaf("token", "add", "evil", "--as", "chatgpt (ADA)")
    assert r.code != 0 and [t.name for t in Tokens().list()] == ["one"]


@pytest.mark.parametrize("old", ["claude", "codex", "ai"])
def test_an_old_token_named_like_a_client_does_not_block_that_agent(sheaf, old):
    assert sheaf("token", "add", old).code == 0
    assert sheaf("token", "add", "agent-" + old, "--client", old.capitalize()).code == 0


def test_the_hub_refuses_to_start_when_an_agent_signs_a_name_another_token_signs():
    with pytest.raises(proxy.ProxyError, match="another token"):
        proxy.check_agent_names([(True, "ChatGPT (Bea)"), (True, "chatgpt (Bea)")])
    with pytest.raises(proxy.ProxyError, match="another token"):
        proxy.check_agent_names([(False, "ChatGPT (Hans)"), (True, "ChatGPT (Hans)")])    # a typed display, after a rebinding
    proxy.check_agent_names([(True, "ChatGPT (Bea)"), (True, "ChatGPT (Bob)")])
    proxy.check_agent_names([(False, "Codex"), (False, "codex")])                       # old tokens may share a display



# ── a token's id: what tells a revoked token from a new one of the same name ─

def test_every_new_token_gets_a_random_id_that_the_door_sees_on_the_resolved_token():
    token = Tokens().add("bea-chatgpt", client="ChatGPT")
    [row] = stored()
    assert isinstance(row["id"], str) and len(row["id"]) == 16 and int(row["id"], 16) >= 0
    assert Tokens().verify(token).id == row["id"] and token.id == row["id"]
    assert token not in json.dumps(row)                        # an id is not the secret


def test_revoking_a_token_and_adding_one_of_the_same_name_gives_a_different_id():
    first = Tokens().add("bea-chatgpt", client="ChatGPT")
    Tokens().revoke("bea-chatgpt")
    second = Tokens().add("bea-chatgpt", client="ChatGPT")
    assert first.id != second.id and Tokens().verify(second).id == second.id
    assert Tokens().verify(first) is None


def test_an_old_row_has_no_id_and_is_not_given_one():
    token = Tokens().add("codex", "Codex")
    rows = stored()
    del rows[0]["id"]
    Tokens.path().write_text(json.dumps(rows), encoding="utf-8")
    assert Tokens().verify(token).id is None
    assert "id" not in stored()[0]                             # verify, even when it stamps last_used, backfills nothing


def test_list_shows_the_id_and_never_a_token(sheaf):
    out = sheaf("token", "add", "bea-chatgpt", "--client", "ChatGPT").out
    token = [w for w in out.split() if w.startswith("sheaf_mcp_")][0]
    listed = sheaf("token", "list").out
    assert stored()[0]["id"] in listed and token not in listed
