"""The detection table of SPEC 11.5: the first agent whose variable is present."""
import pytest

from sheafmd.agents.detect import TABLE, Agent, detect, session_id

# A literal list on purpose: conftest derives its own from TABLE, so a variable missing from
# TABLE would be missing there too.
ALL_VARS = ("CODEX_THREAD_ID", "CURSOR_CONVERSATION_ID", "CURSOR_AGENT", "OPENCODE", "GEMINI_CLI",
            "CLAUDE_CODE_SESSION_ID")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ALL_VARS:
        monkeypatch.delenv(var, raising=False)


def test_the_table_is_the_spec_table_in_its_order():
    assert [(a.name, a.display) for a in TABLE] == [
        ("codex", "Codex"), ("cursor", "Cursor"), ("opencode", "opencode"),
        ("gemini", "Gemini"), ("claude-code", "Claude")]


@pytest.mark.parametrize("env, name, display", [
    ({"CODEX_THREAD_ID": "t-1"}, "codex", "Codex"),
    ({"CURSOR_CONVERSATION_ID": "c-1"}, "cursor", "Cursor"),
    ({"CURSOR_AGENT": "1"}, "cursor", "Cursor"),
    ({"OPENCODE": "1"}, "opencode", "opencode"),
    ({"GEMINI_CLI": "1"}, "gemini", "Gemini"),
    ({"CLAUDE_CODE_SESSION_ID": "s-1"}, "claude-code", "Claude"),
])
def test_each_agent_is_found_by_its_variable(env, name, display):
    found = detect(env)
    assert isinstance(found, Agent)
    assert (found.name, found.display) == (name, display)


def test_nothing_set_is_no_agent():
    assert detect({}) is None
    assert detect({"PATH": "/usr/bin", "HOME": "/home/x"}) is None


@pytest.mark.parametrize("env", [
    {"CODEX_THREAD_ID": ""}, {"CODEX_THREAD_ID": "  "}, {"CLAUDE_CODE_SESSION_ID": ""},
    {"CURSOR_CONVERSATION_ID": ""},
])
def test_an_empty_variable_is_not_present(env):
    assert detect(env) is None


@pytest.mark.parametrize("env", [
    {"CURSOR_AGENT": "0"}, {"CURSOR_AGENT": "true"}, {"OPENCODE": "0"}, {"OPENCODE": "true"},
    {"OPENCODE": ""}, {"GEMINI_CLI": "yes"}, {"GEMINI_CLI": "0"},
])
def test_a_flag_variable_needs_exactly_1(env):
    assert detect(env) is None


def test_a_flag_variable_with_1_survives_surrounding_spaces():
    assert detect({"OPENCODE": " 1 "}).name == "opencode"


def test_the_first_row_wins_when_several_are_present():
    everything = {"CODEX_THREAD_ID": "t", "CURSOR_CONVERSATION_ID": "c", "OPENCODE": "1",
                  "GEMINI_CLI": "1", "CLAUDE_CODE_SESSION_ID": "s"}
    remaining = dict(everything)
    for agent in TABLE:
        assert detect(remaining).name == agent.name
        for var, _ in agent.present_when:
            remaining.pop(var, None)
    assert detect(remaining) is None


def test_a_codex_started_inside_claude_code_is_codex():
    assert detect({"CLAUDE_CODE_SESSION_ID": "s", "CODEX_THREAD_ID": "t"}).display == "Codex"


def test_the_default_environment_is_os_environ(monkeypatch):
    assert detect() is None
    monkeypatch.setenv("GEMINI_CLI", "1")
    assert detect().display == "Gemini"


@pytest.mark.parametrize("env, want", [
    ({"CODEX_THREAD_ID": "t-1"}, "t-1"),
    ({"CURSOR_CONVERSATION_ID": "c-1"}, "c-1"),
    ({"CURSOR_AGENT": "1"}, None),                   # Cursor without a conversation id
    ({"OPENCODE": "1"}, None),
    ({"GEMINI_CLI": "1"}, None),
    ({"CLAUDE_CODE_SESSION_ID": " s-1 "}, "s-1"),
    ({}, None),
])
def test_the_session_id_is_the_detected_agents_own_variable(env, want):
    assert session_id(env) == want


def test_the_session_id_is_that_of_the_first_agent_not_of_every_variable():
    assert session_id({"CLAUDE_CODE_SESSION_ID": "s", "CODEX_THREAD_ID": "t"}) == "t"
    # the first match is THE agent (SPEC 11.5): Gemini comes before Claude Code and has no session id
    assert session_id({"CLAUDE_CODE_SESSION_ID": "s", "GEMINI_CLI": "1"}) is None
