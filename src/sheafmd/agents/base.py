"""
sheafmd.agents.base — the agent adapter interface (SPEC 11.1).

The core calls an agent only through `Adapter`; no other module knows an agent's name. A
`Target` is what a render records about the session it ran in (`docs.json`, 8.3); a `State` is
what the session is doing now. `Runner` is the job runner's killable subprocess call, for the
adapters that deliver through a process.
"""
import re
import subprocess
from dataclasses import asdict, dataclass, fields
from typing import Callable, Mapping, Protocol

CAPS = frozenset({"ask", "deliver", "state", "stop"})

# run(argv, *, timeout, env=None, cwd=None, input=None): a child in its own process group, `input`
# on its stdin (what is private goes there, never on the command line, which every user of the
# machine can read); a child the runner killed comes back with a negative return code; a timeout
# raises TimeoutExpired.
Runner = Callable[..., subprocess.CompletedProcess]


class DeliveryError(Exception):
    """A delivery that did not happen. The message is one sentence a person reads."""


class DeliveryCancelled(Exception):
    """A delivery the job runner killed on Cancel."""


@dataclass
class State:
    status: str          # "working" | "waiting" | "idle" | "gone"
    question: str = ""   # with "waiting": what the session asked its person


_NAME = re.compile(r"[A-Za-z0-9._-]{1,40}")
_TEXT_LIMITS = {"session": 200, "name": 200, "cwd": 4096, "socket": 4096, "bin": 4096,
                "config_dir": 4096, "proc_start": 40}


@dataclass
class Target:
    agent: str                  # "claude-code", "codex", ...
    session: str = ""           # the agent's session id, "" when unknown
    pid: int | None = None
    socket: str = ""            # agent-specific delivery address, "" when none
    name: str = ""              # the session's human name when the agent has one ("Cosima")
    cwd: str = ""
    bin: str = ""               # the command that runs the agent, from the render's environment
    config_dir: str = ""        # where the agent keeps its session records
    proc_start: str = ""        # when the session's process started: tells it from a later one
                                # that took the same pid

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "Target":
        """A target read from a request or from `docs.json`. Raises ValueError with one
        sentence naming the field when the shape is wrong; keys it does not know are dropped."""
        if not isinstance(d, dict):
            raise ValueError("target must be an object")
        out = {}
        for f in fields(cls):
            if f.name not in d:
                continue
            v = d[f.name]
            if f.name == "agent":
                if not (isinstance(v, str) and _NAME.fullmatch(v)):
                    raise ValueError("target.agent must be a short name (letters, digits, . _ -)")
            elif f.name == "pid":
                if v is not None and not (type(v) is int and 0 < v < 2 ** 31):
                    raise ValueError("target.pid must be a process number or null")
            else:
                limit = _TEXT_LIMITS[f.name]
                if not isinstance(v, str) or len(v) > limit or "\0" in v:
                    raise ValueError(f"target.{f.name} must be text of at most {limit} characters")
            out[f.name] = v
        if "agent" not in out:
            raise ValueError("target.agent is missing")
        return cls(**out)


class Adapter(Protocol):
    agent: str           # "claude-code"
    display: str         # "Claude": the name on replies and buttons
    product: str         # "Claude Code"
    implemented: bool    # False for an agent that is only detected (no Ask, no Tell yet)

    def detect(self, env: Mapping[str, str], *, force: bool = False,
               session: str = "") -> Target | None: ...
    def capabilities(self, t: Target) -> frozenset[str]: ...
    def ask_command(self, t: Target) -> list[str]: ...                   # the prompt is its stdin, stdout the answer
    def child_env(self, t: Target) -> dict | None: ...                   # its commands' env; None: the hub's own
    def deliver(self, t: Target, text: str, run: Runner) -> None: ...    # raises DeliveryError
    def state(self, t: Target) -> State | None: ...
    def jump_values(self, t: Target) -> dict | None: ...                 # session, pid, name, agent of a live session of this account; None: none
    def name(self, t: Target) -> str: ...                                # its human name now, "" when it has none
    def stop(self, t: Target, text: str, run: Runner) -> None: ...
