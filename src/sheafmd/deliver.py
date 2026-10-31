"""
sheafmd.deliver — `sheaf deliver`: a Tell pushed in the hub's envelope by a process that is not the hub
(SPEC 11.4, sheaf#117).

    sheaf deliver (--socket PATH | --session ID [--config-dir DIR] [--wait S]) [--from uds:PATH] < drop.json

The box's supervisor reads a drop of `tell_dir` (9.12) and hands it here, so a box session sees a Tell
the way a local one does: a peer message from sheaf, never typed text and never a frame from no one.
By `--session` the socket is the one the session's live record names, and a session that speaks no
peer protocol gets the courier, as the hub's own Tell does (11.4). `--wait` gives a window that was
just opened the time to publish its socket.
Registered in COMMANDS and COMMAND_HELP, which the foot of cli.py merges into its own.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

from . import config, paths
from .agents import envelope, prompts
from .agents.base import DeliveryCancelled, DeliveryError, Target
from .agents import claude_code
from .agents.claude_code import ClaudeCodeAdapter

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
POLL_S = 0.2

COMMANDS: dict = {}
COMMAND_HELP: dict = {}


def _err(line: str = ""):
    print(line, file=sys.stderr)


def _drop(raw: str) -> dict | None:
    try:
        drop = json.loads(raw)
    except ValueError:
        return None
    return drop if isinstance(drop, dict) else None


def _text(drop: dict) -> str | None:
    """The drop's own `message` when it has one, else the text built from the keys the hub writes today."""
    msg = drop.get("message")
    if isinstance(msg, str) and msg.strip():
        return msg
    return prompts.dropped(drop)


def _run(argv, *, timeout, env=None, cwd=None, input=None) -> subprocess.CompletedProcess:
    """The courier's runner: the child to its end, its prompt on stdin."""
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env=env, cwd=cwd, input=input)


def _to_session(args, text: str, sender: str) -> int:
    ad = ClaudeCodeAdapter(sender)
    t = Target(agent=ad.agent, session=args.session, bin=shutil.which("claude") or "",
               config_dir=args.config_dir or str(claude_code._config_dir(os.environ)))
    deadline = time.monotonic() + max(args.wait, 0.0)
    while "deliver" not in ad.capabilities(t):
        if time.monotonic() >= deadline:
            _err(f"sheaf: no open session {args.session} in {t.config_dir}")
            return EXIT_FAILED
        time.sleep(POLL_S)
    try:
        ad.deliver(t, text, _run)
    except (DeliveryError, DeliveryCancelled) as e:
        _err(f"sheaf: {e or 'the delivery was cancelled'}")
        return EXIT_FAILED
    return EXIT_OK


def cmd_deliver(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="sheaf deliver",
        usage="sheaf deliver (--socket PATH | --session ID [--config-dir DIR] [--wait S]) [--from uds:PATH] "
              "< DROP.json",
        description="Push the Tell of a drop (its JSON on stdin) to a Claude Code session in the hub's "
                    "envelope: a peer message from sheaf.")
    to = p.add_mutually_exclusive_group(required=True)
    to.add_argument("--socket", metavar="PATH", help="the session's messaging socket")
    to.add_argument("--session", metavar="ID", help="the session's id: its socket is the one its live record names")
    p.add_argument("--config-dir", metavar="DIR",
                   help="where the session keeps its record (default: CLAUDE_CONFIG_DIR, else ~/.claude)")
    p.add_argument("--wait", type=float, default=0.0, metavar="S",
                   help="seconds to wait for the session's record to appear (default: 0)")
    p.add_argument("--from", dest="sender", metavar="uds:PATH",
                   help="the address the message names as its origin (default: this user's hub socket)")
    args = p.parse_args(argv)
    drop = _drop(sys.stdin.read())
    text = _text(drop) if drop is not None else None
    if text is None:
        _err("sheaf: stdin must be one JSON object, a drop of tell_dir")
        return EXIT_USAGE
    sender = args.sender or f"uds:{paths.hub_socket(config.port())}"
    if args.session:
        code = _to_session(args, text, sender)
        if code == EXIT_OK:
            print("delivered")
        return code
    try:
        envelope.push(args.socket, envelope.line(text, sender))
    except OSError as e:
        _err(f"sheaf: the session did not take the message ({e.strerror or e})")
        return EXIT_FAILED
    print("delivered")
    return EXIT_OK


COMMANDS.update({"deliver": cmd_deliver})
COMMAND_HELP.update({
    "deliver": ("deliver (--socket PATH | --session ID [--config-dir DIR] [--wait S]) [--from uds:PATH] < DROP.json",
                "push a drop's Tell to a Claude Code session in the hub's envelope"),
})
