"""
sheafmd.agents.detect — which coding agent is running this command (SPEC 11.5).

The first row of TABLE whose variable is present in the environment is the agent. A
variable is present when it is set and not empty; a row that says `=1` needs exactly
"1". This is the whole of it: the agent's name, and the display name its replies are
signed with, and the variable that holds its session id, which the diagnostics log
records. The capabilities of 11.5 belong to the adapter that uses them. The product name
is in two places: here, because the page names it for an agent that has no adapter yet,
and in an adapter written for its agent, whose messages name it.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Agent:
    name: str                  # what `--agent` takes: "codex", "claude-code"
    display: str               # what a reply is signed with: "Codex", "Claude"
    # Each pair is (variable, required value); None means "set and not empty". The agent
    # is present when any pair holds.
    present_when: tuple[tuple[str, str | None], ...] = ()
    session_var: str | None = None     # the variable holding its session id; None: it has none
    product: str = ""                  # "Codex CLI": how the page names the product

    def present_in(self, environ) -> bool:
        return any(_present(environ, var, value) for var, value in self.present_when)


# SPEC 11.5, in its order.
TABLE: tuple[Agent, ...] = (
    Agent("codex", "Codex", (("CODEX_THREAD_ID", None),), "CODEX_THREAD_ID", "Codex CLI"),
    Agent("cursor", "Cursor", (("CURSOR_CONVERSATION_ID", None), ("CURSOR_AGENT", "1")),
          "CURSOR_CONVERSATION_ID", "Cursor agent"),
    Agent("opencode", "opencode", (("OPENCODE", "1"),), None, "opencode"),
    Agent("gemini", "Gemini", (("GEMINI_CLI", "1"),), None, "Gemini CLI"),
    Agent("claude-code", "Claude", (("CLAUDE_CODE_SESSION_ID", None),), "CLAUDE_CODE_SESSION_ID",
          "Claude Code"),
)


def _present(environ, var: str, value: str | None) -> bool:
    got = environ.get(var, "").strip()
    return got == value if value is not None else got != ""


def detect(environ=None) -> Agent | None:
    """The first agent of TABLE that `environ` (default: os.environ) shows, or None."""
    environ = os.environ if environ is None else environ
    for agent in TABLE:
        if agent.present_in(environ):
            return agent
    return None


def session_id(environ=None) -> str | None:
    """The session id of the detected agent (SPEC 11.5), or None: no agent, or one that has
    none (opencode, Gemini), or an empty variable."""
    environ = os.environ if environ is None else environ
    agent = detect(environ)
    if agent is None or agent.session_var is None:
        return None
    return environ.get(agent.session_var, "").strip() or None
