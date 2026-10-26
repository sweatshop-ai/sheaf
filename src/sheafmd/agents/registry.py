"""
sheafmd.agents.registry — every adapter, in the order of the detection table (SPEC 11.5).

At render the first adapter that finds its agent in the environment gives the target;
`--agent <name>` forces one, `--agent none` attaches nothing, `--session <id>` overrides the
session id. The hub builds the adapters with the sender address its pushes carry.
"""
from typing import Mapping

from .base import Adapter, Target
from .claude_code import ClaudeCodeAdapter
from .detect import TABLE
from .generic import GenericAdapter


def adapters(sender: str = "") -> tuple[Adapter, ...]:
    return tuple(ClaudeCodeAdapter(sender) if row.name == ClaudeCodeAdapter.agent
                 else GenericAdapter(row) for row in TABLE)


def adapter_for(agent: str, sender: str = "") -> Adapter:
    """The adapter of `agent`; for a name sheaf does not know, one that shows the name and can
    do nothing."""
    for a in adapters(sender):
        if a.agent == agent:
            return a
    return GenericAdapter(name=agent)


def detect_target(env: Mapping[str, str], agent: str | None = None,
                  session: str | None = None) -> Target | None:
    """The target a render in `env` records, or None when no agent is there (or `agent` is
    "none")."""
    if agent == "none":
        return None
    if agent:
        return adapter_for(agent).detect(env, force=True, session=session or "")
    for a in adapters():
        t = a.detect(env, session=session or "")
        if t is not None:
            return t
    return None
