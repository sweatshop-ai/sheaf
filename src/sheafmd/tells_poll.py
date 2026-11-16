"""
sheafmd.tells_poll — `sheaf tells-poll`, one long-poll of a tiroir's door for a laptop session's Tells (SPEC 9.8, 13).

    sheaf tells-poll --origin https://HOST --session ID [--wait 25]

The Claude Code mod of the plugin calls this and nothing else: the token is read from the keyring here, so it never
enters the mod. The session id is the one the agent declared, sent in the declared-session header exactly as a send does;
the door hands a Tell only to the token and the session id it was queued for. It prints the Tells the door listed as a
JSON array (empty when none came within the wait) and exits 0; every failure is one sentence on stderr and exit 1.
"""
import argparse
import json
import sys

from . import connect, send

EXIT_OK, EXIT_FAILED = 0, 1
MAX_WAIT = 25    # the door's own limit

COMMAND_HELP = {"tells-poll": ("tells-poll --origin URL --session ID [--wait SECONDS]",
                               "ask a tiroir's door for a laptop session's Tells and print them as JSON (used by the Claude Code mod)")}


def _wait(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        n = -1
    if not 0 <= n <= MAX_WAIT:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of seconds from 0 to {MAX_WAIT}")
    return n


def cmd_tells_poll(argv: list[str], out=None, err=None) -> int:
    out = out or (lambda line="": print(line))
    err = err or (lambda line="": print(line, file=sys.stderr))
    p = argparse.ArgumentParser(prog="sheaf tells-poll", usage="sheaf tells-poll --origin URL --session ID [--wait SECONDS]",
                                description="Ask a tiroir's door for the Tells of a laptop session; print them as a JSON array.")
    p.add_argument("--origin", required=True, metavar="URL")
    p.add_argument("--session", required=True, metavar="ID")
    p.add_argument("--wait", type=_wait, default=MAX_WAIT, metavar="SECONDS")
    args = p.parse_args(argv)
    token = None
    try:
        origin = connect.origin_of(args.origin)
        token = send.credential(origin)
        if token is None:
            raise send.SendError(f"this laptop holds no credential for {origin}: run sheaf connect.")
        door = send.Door(origin, token, {"X-Sheaf-Host": send.machine(), "X-Sheaf-Session": args.session})
        bad, got = door.tool("tells", {"wait": args.wait})
        if bad:
            raise send.SendError(str(got))
    except (send.SendError, connect.UsageError) as e:
        err(f"sheaf: {str(e).replace(token, '***') if token else e}")
        return EXIT_FAILED
    out(json.dumps(got["tells"]))
    return EXIT_OK
