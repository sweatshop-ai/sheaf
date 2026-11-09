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


def test_an_agents_row_stores_no_display_and_verify_gives_back_its_client():
    """The previous reader wanted a `display` in every row, so it turned an agent's row away. This test does not run
    that reader; it checks the row has no `display` and that `verify` still knows the client."""
    token = Tokens().add("t", client="ChatGPT")
    assert "display" not in stored()[0]
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
    with pytest.raises(proxy.ProxyError, match="signs too"):
        proxy.check_agent_names([(True, "ChatGPT (Bea)", "a"), (True, "chatgpt (Bea)", "b")])
    with pytest.raises(proxy.ProxyError, match="signs too"):
        proxy.check_agent_names([(False, "ChatGPT (Hans)", "a"), (True, "ChatGPT (Hans)", "b")])    # a typed display, after a rebinding
    proxy.check_agent_names([(True, "ChatGPT (Bea)", "a"), (True, "ChatGPT (Bob)", "b")])
    proxy.check_agent_names([(False, "Codex", "a"), (False, "codex", "b")])                       # old tokens may share a display



# ── `add` and the start fold and judge names the same way (13) ──────────────

def proxy_config(work, member="Bea", tokens=()):
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    listed = ", ".join(json.dumps(t) for t in tokens)
    paths.config_file().write_text(
        f'[proxy]\norigin = "{FRONT}"\nsocket = "/run/sheaf-proxy/hub.sock"\n'
        f'proxy_user = "{pwd.getpwuid(os.getuid()).pw_name}"\n'
        f'[proxy.members."{BEA}"]\nname = {json.dumps(member)}\nroots = ["{work}"]\ntokens = [{listed}]\n',
        encoding="utf-8")


@pytest.mark.parametrize("shown", ["Béa", "Ｂｅａ", "bea"])
def test_add_refuses_a_typed_display_that_a_member_has_by_accent_or_width(sheaf, work, shown):
    proxy_config(work)
    r = sheaf("token", "add", "t", "--as", shown)
    assert r.code != 0 and "Bea" in r.err and Tokens().list() == []


@pytest.mark.parametrize("member", ["action", "Action", "answer", "ＡＣＴＩＯＮ"])
def test_add_refuses_an_agent_whose_built_name_reads_as_a_role(sheaf, work, member):
    proxy_config(work, member, tokens=["t"])
    r = sheaf("token", "add", "t", "--client", "ChatGPT")
    assert r.code != 0 and "role" in r.err and Tokens().list() == []


def test_add_refuses_an_agent_whose_built_name_reads_as_a_role_in_loopback_too(sheaf, monkeypatch):
    monkeypatch.setenv("SHEAF_NAME", "action")
    r = sheaf("token", "add", "t", "--client", "ChatGPT")
    assert r.code != 0 and "role" in r.err and Tokens().list() == []


def test_add_refuses_an_old_token_that_signs_the_hubs_persons_name_in_proxy_mode_only(sheaf, work):
    assert sheaf("token", "add", "loop", "--as", "ada").code == 0         # loopback: as before
    Tokens().revoke("loop")
    proxy_config(work)
    for shown in ("ada", "Ａｄａ", "Adá"):
        r = sheaf("token", "add", "t", "--as", shown)
        assert r.code != 0 and "Ada" in r.err and "hub's person" in r.err and Tokens().list() == []
    assert sheaf("token", "add", "ada").code != 0                           # the name stands for the display


def test_add_refuses_the_persons_name_also_while_the_proxy_table_is_one_the_hub_would_refuse(sheaf, work):
    """A table that `load` refuses (no `proxy_user`) is still proxy mode once it is mended: a token made now must
    not be one the start then refuses."""
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(
        f'[proxy]\norigin = "{FRONT}"\nsocket = "/run/sheaf-proxy/hub.sock"\n'
        f'[proxy.members."{BEA}"]\nname = "Bea"\nroots = ["{work}"]\n', encoding="utf-8")
    r = sheaf("token", "add", "t", "--as", "ada")
    assert r.code != 0 and "hub's person" in r.err and Tokens().list() == []


def test_add_judges_a_display_against_the_agents_of_the_bound_member_while_the_proxy_table_is_one_the_hub_would_refuse(sheaf, work):
    proxy_config(work, tokens=["bea-chatgpt"])
    assert sheaf("token", "add", "bea-chatgpt", "--client", "ChatGPT").code == 0     # signs `ChatGPT (Bea)`
    text = paths.config_file().read_text(encoding="utf-8")
    paths.config_file().write_text(text.replace(f'proxy_user = "{pwd.getpwuid(os.getuid()).pw_name}"\n', ""), encoding="utf-8")
    r = sheaf("token", "add", "t", "--as", "ChatGPT (Bea)")
    assert r.code != 0 and "ChatGPT (Bea)" in r.err and [t.name for t in Tokens().list()] == ["bea-chatgpt"]


def test_add_fails_closed_when_config_toml_cannot_be_read(sheaf, work):
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text('[proxy\nname = "Bea"\n', encoding="utf-8")        # a syntax error; SHEAF_NAME is Ada
    r = sheaf("token", "add", "t", "--as", "ada")
    assert r.code != 0 and Tokens().list() == []


def test_a_role_word_is_read_at_the_end_of_a_built_name_longer_than_the_display_cut():
    assert not proxy.reads_as_role("OpenWebUI-assistant-for-the-whole-team-x (Ann Lee-B (action) Smith)")
    assert proxy.reads_as_role("OpenWebUI-assistant-for-the-whole-team-x (action)")


def test_add_accepts_what_the_start_accepts_two_old_tokens_with_one_display(sheaf, work):
    proxy_config(work)
    assert sheaf("token", "add", "one", "--as", "Codex").code == 0
    assert sheaf("token", "add", "two", "--as", "codex").code == 0
    proxy.check_names(proxy.load(), "Ada", [t.signed("Ada", proxy.load()) for t in Tokens().list()])


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


# ── a broken `[proxy]` table, and two adds at once (14) ─────────────────────

def broken_proxy_config(work):
    """A table the hub refuses (`proxy_user` is missing) that still binds `bea-chatgpt` to Bea."""
    proxy_config(work, tokens=["bea-chatgpt"])
    text = paths.config_file().read_text(encoding="utf-8")
    paths.config_file().write_text(text.replace(f'proxy_user = "{pwd.getpwuid(os.getuid()).pw_name}"\n', ""),
                                   encoding="utf-8")


def test_add_a_client_refuses_with_the_tables_error_and_writes_nothing_while_the_proxy_table_is_broken(sheaf, work):
    broken_proxy_config(work)
    with pytest.raises(proxy.ProxyError) as table:
        proxy.load()
    r = sheaf("token", "add", "bea-chatgpt", "--client", "ChatGPT")
    assert r.code != 0 and str(table.value) in r.err and "[proxy]" in r.err
    assert "sheaf_mcp_" not in r.out and Tokens().list() == []


def test_list_says_the_table_is_broken_and_names_no_signature_built_on_the_person(sheaf, work):
    proxy_config(work, tokens=["bea-chatgpt"])
    assert sheaf("token", "add", "bea-chatgpt", "--client", "ChatGPT").code == 0
    assert sheaf("token", "add", "old", "--as", "Codex").code == 0
    broken_proxy_config(work)
    with pytest.raises(proxy.ProxyError) as table:
        proxy.load()
    r = sheaf("token", "list")
    assert str(table.value) in r.err and "[proxy]" in r.err
    assert "(Ada)" not in r.out and "ChatGPT (Bea)" not in r.out         # neither the person's nor a guess at the member's
    [agent] = [line for line in r.out.splitlines() if line.split()[:1] == ["bea-chatgpt"]]
    assert "ChatGPT" in agent and "table is broken" in agent
    [old] = [line for line in r.out.splitlines() if line.split()[:1] == ["old"]]
    assert old.split()[:2] == ["old", "Codex"]                                  # a typed display needs no table


def test_list_without_a_proxy_table_still_signs_an_agent_with_the_person(sheaf):
    assert sheaf("token", "add", "t", "--client", "ChatGPT").code == 0
    r = sheaf("token", "list")
    assert r.err == "" and "ChatGPT -> ChatGPT (Ada)" in r.out


def test_a_running_hub_keeps_the_binding_it_started_with_while_the_table_is_broken_on_disk(browser, talk, work):
    """The hub reads its `[proxy]` table once, at the start (9.9): a file mended or broken later changes the next
    start, never the signatures of this one."""
    token = Tokens().add("bea-chatgpt", client="ChatGPT")
    browser.hub.proxy = members(work, tokens=["bea-chatgpt"])
    broken_proxy_config(work)
    reply(browser, token)
    assert last_by(talk) == "ChatGPT (Bea)"


CLASH_CHILD = """
import os, sys
from pathlib import Path
from sheafmd.hub import state
real = state.file_locked
def marked(name):
    if name == "tokens.lock":                   # the child stands at the lock: the parent holds it
        Path(os.environ["REACHED"]).touch()
    return real(name)
state.file_locked = marked
from sheafmd.cli import main
sys.exit(main(sys.argv[1:]))
"""


def test_two_adds_of_one_client_and_member_at_once_write_exactly_one(work, tmp_path):
    """Two real processes, both past the config read and standing at `tokens.lock` while this test holds it: the
    clash check has to run once the lock is theirs, or both pass it on the same empty file and both are written."""
    import subprocess
    import sys
    import time

    from sheafmd.hub.state import file_locked
    proxy_config(work, tokens=["bea-a", "bea-b"])                       # both sign `ChatGPT (Bea)`
    kids = []
    with file_locked("tokens.lock"):
        for name in ("bea-a", "bea-b"):
            reached = tmp_path / f"reached-{name}"
            kids.append((name, reached, subprocess.Popen(
                [sys.executable, "-c", CLASH_CHILD, "token", "add", name, "--client", "ChatGPT"],
                env={**os.environ, "REACHED": str(reached)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)))
        deadline = time.monotonic() + 60
        while not all(r.exists() for _, r, _ in kids) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert all(r.exists() for _, r, _ in kids)
        time.sleep(0.5)                                                  # from the touch to the flock call
    ran = [(name, p.communicate(timeout=120), p.returncode) for name, _, p in kids]
    written = [t.name for t in Tokens().list()]
    assert len(written) == 1, ran
    [(_, (out, err), code)] = [r for r in ran if r[0] not in written]
    assert code != 0 and "ChatGPT (Bea)" in err and "sheaf_mcp_" not in out
    [(_, (out, err), code)] = [r for r in ran if r[0] in written]
    assert code == 0 and "sheaf_mcp_" in out


def test_the_clash_check_of_add_runs_inside_the_lock_with_the_rows_of_that_moment(work):
    """The check is handed to `Tokens.add` and is called under `tokens.lock` with the rows the file holds then."""
    seen = []

    def check(rows):
        seen.append([r.name for r in rows])
        return "taken" if rows else None

    tokens = Tokens()
    tokens.add("a", client="ChatGPT", clash=check)
    with pytest.raises(TokenError, match="taken"):
        tokens.add("b", client="ChatGPT", clash=check)
    assert seen == [[], ["a"]] and [t.name for t in tokens.list()] == ["a"]


def test_the_config_is_read_before_the_lock_is_taken(sheaf, work, monkeypatch):
    """No lock is held across the config read: `add` reads the table and the person, then locks."""
    from sheafmd import config
    from sheafmd.hub import state
    held = []
    real_lock, real_name = state.file_locked, config.user_name
    depth = []

    def watched_lock(name):
        cm = real_lock(name)

        class Held:
            def __enter__(self):
                depth.append(name)
                return cm.__enter__()

            def __exit__(self, *a):
                try:
                    return cm.__exit__(*a)
                finally:
                    depth.pop()
        return Held()

    def watched_name():
        held.append(list(depth))
        return real_name()
    monkeypatch.setattr(state, "file_locked", watched_lock)
    monkeypatch.setattr(config, "user_name", watched_name)
    proxy_config(work, tokens=["bea-chatgpt"])
    assert sheaf("token", "add", "bea-chatgpt", "--client", "ChatGPT").code == 0
    assert held and all(h == [] for h in held)


def test_the_clash_message_of_add_is_the_one_it_always_was(sheaf):
    sheaf("token", "add", "old", "--as", "ChatGPT (Ada)")
    r = sheaf("token", "add", "new", "--client", "ChatGPT")
    assert r.err == ("sheaf: 'ChatGPT (Ada)' is already a name in use here (the hub's person, a member of proxy mode, "
                     "or another token's); a token that signs 'ChatGPT (Ada)' would pass for it\n")
