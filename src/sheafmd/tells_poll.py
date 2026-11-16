"""
sheafmd.tells_poll — `sheaf tells-poll`, one long-poll of a tiroir's door for a laptop session's Tells (SPEC 9.8, 13).

    sheaf tells-poll (--origin https://HOST | --server NAME) --session ID [--wait 25]

`--server` is the name of the door's entry among Claude Code's MCP servers (`sheaf connect` writes `sheaf-HOST`), also as
a tool name writes it (`sheaf-chat_example_com`), for a caller that knows the door by its tool calls; the origin is read from that entry's url, and only an entry
named for its own address counts. The token is never read from the entry.

The Claude Code mod of the plugin calls this and nothing else: the token is read from the keyring here, so it never
enters the mod. The session id is the one the agent declared, sent in the declared-session header exactly as a send does;
the door hands a Tell only to the token and the session id it was queued for. It prints the Tells the door listed as a
JSON array (empty when none came within the wait) and exits 0; every failure is one sentence on stderr and exit 1.
"""
import argparse
import json
import re
import sys

from . import connect, send

EXIT_OK, EXIT_FAILED = 0, 1
MAX_WAIT = 25    # the door's own limit

COMMAND_HELP = {"tells-poll": ("tells-poll (--origin URL | --server NAME) --session ID [--wait SECONDS]",
                               "ask the shared Sheaf's door for a laptop session's Tells and print them as JSON (the Claude Code mod runs it)")}


def _wait(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        n = -1
    if not 0 <= n <= MAX_WAIT:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of seconds from 0 to {MAX_WAIT}")
    return n


def _tool_name_form(name: str) -> str:
    """How Claude Code writes a server's name in its tool names (`mcp__NAME__tool`): anything but a letter, digit, `_`
    or `-` is an underscore, so `sheaf-chat.example.com` is `sheaf-chat_example_com` there."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def _origin_of_server(name: str) -> str:
    """The origin of the door entry named `name` (as in `.claude.json`, or as a tool name writes it) among Claude Code's
    MCP servers; UsageError unless that entry is the one `sheaf connect` makes for the address its url names."""
    path = connect.claude_json()
    try:
        servers = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
        found = [(n, e["url"]) for n, e in servers.items() if name in (n, _tool_name_form(n))]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise connect.UsageError(f"{name!r} is not one of the shared Sheaf doors in {path}") from None
    if len(found) != 1 or not isinstance(found[0][1], str) or not found[0][1].endswith(connect.DOOR_PATH):
        raise connect.UsageError(f"{name!r} is not the door of a shared Sheaf in {path}")
    entry, url = found[0]
    origin = connect.origin_of(url[: -len(connect.DOOR_PATH)])
    if connect.entry_name(origin) != entry:
        raise connect.UsageError(f"{entry!r} is not the entry that sheaf connect makes for {origin}")
    return origin


def cmd_tells_poll(argv: list[str], out=None, err=None) -> int:
    out = out or (lambda line="": print(line))
    err = err or (lambda line="": print(line, file=sys.stderr))
    p = argparse.ArgumentParser(prog="sheaf tells-poll", usage="sheaf tells-poll (--origin URL | --server NAME) --session ID [--wait SECONDS]",
                                description="Ask the shared Sheaf's door for the Tells of a laptop session; print them as a JSON array.")
    where = p.add_mutually_exclusive_group(required=True)
    where.add_argument("--origin", metavar="URL")
    where.add_argument("--server", metavar="NAME")
    p.add_argument("--session", required=True, metavar="ID")
    p.add_argument("--wait", type=_wait, default=MAX_WAIT, metavar="SECONDS")
    args = p.parse_args(argv)
    token = None
    try:
        origin = _origin_of_server(args.server) if args.server else connect.origin_of(args.origin)
        token = send.credential(origin)
        if token is None:
            raise send.SendError(f"this laptop holds no credential for {origin}: run sheaf connect.")
        door = send.Door(origin, token, {"X-Sheaf-Host": send.machine(), "X-Sheaf-Session": args.session})
        bad, got = door.tool("tells", {"wait": args.wait})
        if bad:
            raise send.SendError(str(got))
        tells = got.get("tells") if isinstance(got, dict) else None
        if not isinstance(tells, list) or not all(isinstance(t, dict) for t in tells):
            raise send.SendError(f"the door of {origin} answered a tells call with something that is not a list of Tells.")
    except (send.SendError, connect.UsageError) as e:
        err(f"sheaf: {str(e).replace(token, '***') if token else e}")
        return EXIT_FAILED
    out(json.dumps(tells))
    return EXIT_OK


# ── `sheaf headers`: the headersHelper of the door's MCP entry ───────────────

COMMAND_HELP["headers"] = ("headers [--check NAME]",
                           "the headers a door write declares itself with (Claude Code's headersHelper); --check: does the MCP entry NAME carry it")


def _has_helper(name: str) -> bool:
    """Whether the MCP entry `name` (as the entry or as a tool name writes it) is the door `sheaf connect` makes for its
    address and carries the headersHelper."""
    try:
        origin = _origin_of_server(name)
        servers = json.loads(connect.claude_json().read_text(encoding="utf-8"))["mcpServers"]
        entry = servers[connect.entry_name(origin)]
        return isinstance(entry.get("headersHelper"), str) and bool(entry["headersHelper"].strip())
    except (connect.UsageError, OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def cmd_headers(argv: list[str], out=None, err=None) -> int:
    out = out or (lambda line="": print(line))
    p = argparse.ArgumentParser(prog="sheaf headers", usage="sheaf headers [--check NAME]",
                                description="Print the headers a door write declares itself with, as one JSON object: the "
                                            "session, the machine and the Remote Control link. Never a token.")
    p.add_argument("--check", metavar="NAME", help="print nothing; exit 0 when the MCP entry NAME carries this helper, else 1")
    args = p.parse_args(argv)
    if args.check is not None:
        return EXIT_OK if _has_helper(args.check) else EXIT_FAILED
    out(json.dumps(send.declared(session=send.registry_session())))
    return EXIT_OK
