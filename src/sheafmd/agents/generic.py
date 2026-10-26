"""
sheafmd.agents.generic — an agent sheaf detects but has no adapter for (SPEC 11.5).

Codex, Cursor, opencode and Gemini are found by their variable and get a target; they have no
capability in v1, so the page shows Ask and Tell disabled with the line of 10.6. They keep the
MCP door. An agent named with `--agent` that is none of those gets its own name for display.
"""
from typing import Mapping

from .base import DeliveryError, State, Target
from .detect import Agent


class GenericAdapter:
    implemented = False

    def __init__(self, row: Agent | None = None, *, name: str = ""):
        if row is not None:
            self.agent, self.display, self.product = row.name, row.display, row.product or row.display
            self._row = row
        else:
            self.agent = self.display = self.product = name
            self._row = None

    def detect(self, env: Mapping[str, str], *, force: bool = False,
               session: str = "") -> Target | None:
        row = self._row
        if not (force or (row is not None and row.present_in(env))):
            return None
        own = ""
        if row is not None and row.session_var:
            own = env.get(row.session_var, "").strip()
        return Target(agent=self.agent, session=session or own)

    def capabilities(self, t: Target) -> frozenset[str]:
        return frozenset()

    def ask_command(self, t: Target) -> list[str]:
        raise NotImplementedError(f"{self.product} has no Ask in this version")

    def child_env(self, t: Target) -> dict | None:
        return None

    def deliver(self, t: Target, text: str, run) -> None:
        raise DeliveryError(f"{self.product} cannot receive a Tell in this version")

    def name(self, t: Target) -> str:
        return t.name

    def jump_values(self, t: Target) -> dict | None:
        return None

    def state(self, t: Target) -> State | None:
        return None

    def stop(self, t: Target, text: str, run) -> None:
        raise DeliveryError(f"{self.product} cannot receive a Tell in this version")
