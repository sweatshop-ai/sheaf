"""
sheafmd.cmdline — what every command module shares: the exit codes, the two output streams, the
parser of one command and the one line a hub failure is said in. cli.py and lifecycle.py both
import it; it imports neither.
"""
import argparse
import sys

from .hub import client as hubclient

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def out(line: str = ""):
    print(line)


def err(line: str = ""):
    print(line, file=sys.stderr)


def parser(name: str, usage: str, what: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=f"sheaf {name}", usage=f"sheaf {usage}", description=what)


def hub_failure(e: Exception) -> int:
    if isinstance(e, hubclient.Impostor):
        err(f"  ! {e}")
    else:
        err(f"sheaf: {e}")
    return EXIT_FAILED
