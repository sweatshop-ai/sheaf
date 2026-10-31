"""
sheafmd.deliver — `sheaf deliver`: a Tell delivered in the hub's envelope by a process that is not the hub
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
import math
import os
import re
import shutil
import sys
import time

from . import config, paths
from .agents import envelope, prompts
from .agents.base import DeliveryCancelled, DeliveryError, Target
from .agents.claude_code import ClaudeCodeAdapter, config_dir_of
from .hub.jobs import Job

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
POLL_S = 0.2
# `--from` is written into the envelope's opening tag: a quote, an angle bracket or a control character in
# it would close the attribute or the tag and let the caller name any sender it likes.
_SENDER_RE = re.compile(r"uds:[^\"<>&\x00-\x1f\x7f]+")
_MSG_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

COMMANDS: dict = {}
COMMAND_HELP: dict = {}


class Refused(Exception):
    """A delivery that did not happen; the message is one sentence a person reads."""


def _err(line: str = ""):
    print(line, file=sys.stderr)


def _seconds(text: str) -> float:
    """A wait: a finite number of seconds, 0 or more. nan or inf would never reach the deadline."""
    try:
        s = float(text)
    except ValueError:
        s = math.nan
    if not math.isfinite(s) or s < 0:
        raise argparse.ArgumentTypeError("must be a number of seconds, 0 or more")
    return s


def _parse_drop() -> dict | None:
    """The drop on stdin; None for what is not UTF-8, not JSON, nested past the parser, or not an object."""
    try:
        drop = json.loads(sys.stdin.read())
    except (ValueError, RecursionError):           # UnicodeDecodeError is a ValueError
        return None
    return drop if isinstance(drop, dict) else None


def _tell_text(drop: dict) -> str | None:
    """The drop's own `message` when it has one, else the text built from the keys the hub writes today."""
    msg = drop.get("message")
    if isinstance(msg, str) and msg.strip():
        return msg
    return prompts.dropped(drop)


def _to_socket(args, text: str, sender: str, msg_id: str | None):
    try:
        envelope.push(args.socket, envelope.line(text, sender, msg_id))
    except OSError as e:
        raise Refused(f"the session did not take the message ({e.strerror or e})") from None


def _to_session(args, text: str, sender: str, msg_id: str | None):
    ad = ClaudeCodeAdapter(sender)
    t = Target(agent=ad.agent, session=args.session, bin=shutil.which("claude") or "",
               config_dir=args.config_dir or str(config_dir_of(os.environ)))
    deadline = time.monotonic() + args.wait
    while "deliver" not in ad.capabilities(t):
        if time.monotonic() >= deadline:
            raise Refused(f"no open session {args.session} in {t.config_dir}")
        time.sleep(POLL_S)
    try:
        # The hub's runner: the courier in a process group of its own, which a timeout ends whole.
        ad.deliver(t, text, Job(None, "deliver", "", "").run, msg_id=msg_id)
    except (DeliveryError, DeliveryCancelled) as e:
        raise Refused(str(e) or "the delivery was cancelled") from None


def cmd_deliver(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="sheaf deliver",
        usage="sheaf deliver (--socket PATH | --session ID [--config-dir DIR] [--wait S]) [--from uds:PATH] "
              "< DROP.json",
        description="Deliver the Tell of a drop (its JSON on stdin) to a Claude Code session in the hub's "
                    "envelope: a peer message from sheaf.")
    to = p.add_mutually_exclusive_group(required=True)
    to.add_argument("--socket", metavar="PATH", help="the session's messaging socket")
    to.add_argument("--session", metavar="ID", help="the session's id: its socket is the one its live record names")
    p.add_argument("--config-dir", metavar="DIR",
                   help="where the session keeps its record (default: CLAUDE_CONFIG_DIR, else ~/.claude)")
    p.add_argument("--wait", type=_seconds, default=0.0, metavar="S",
                   help="seconds to wait for the session's record to appear (default: 0)")
    p.add_argument("--from", dest="sender", metavar="uds:PATH",
                   help="the address the message names as its origin (default: this user's hub socket)")
    args = p.parse_args(argv)
    if args.sender is not None and not _SENDER_RE.fullmatch(args.sender):
        _err("sheaf: --from must be uds: and a socket path, without quotes, angle brackets, & or control characters")
        return EXIT_USAGE
    drop = _parse_drop()
    text = _tell_text(drop) if drop is not None else None
    if text is None:
        _err("sheaf: stdin must be one JSON object, a drop of tell_dir")
        return EXIT_USAGE
    msg_id = drop.get("id") if isinstance(drop.get("id"), str) and _MSG_ID_RE.fullmatch(drop["id"]) else None
    sender = args.sender or f"uds:{paths.hub_socket(config.port())}"
    try:
        (_to_session if args.session else _to_socket)(args, text, sender, msg_id)
    except Refused as e:
        _err(f"sheaf: {e}")
        return EXIT_FAILED
    print("delivered")
    return EXIT_OK


COMMANDS.update({"deliver": cmd_deliver})
COMMAND_HELP.update({
    "deliver": ("deliver (--socket PATH | --session ID [--config-dir DIR] [--wait S]) [--from uds:PATH] < DROP.json",
                "deliver a drop's Tell to a Claude Code session in the hub's envelope"),
})
