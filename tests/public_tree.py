"""No client, person, company or host of ours stands in a file of this public repository.

`scan_tree` reads every tracked file, and every tracked path, and reports what it finds as `path:line key`,
never as the text that matched (a name found in a path is the path itself, printed as `path:0 key`). Two kinds of thing are found:

  a name       one of the terms in SHEAF_PUBLIC_TREE_TERMS (comma or line separated; a term is one word or
               several), in any case, as a whole word or inside a longer one or a one-word spelling
               ("name's", "name-mac", "NameCorp"), and across a line break. A term that starts with `=`
               is found only as whole words, for a short name that other words contain. The key is
               `term N`, its place in the list, so a log shows no name.
  an address   100.x.y.z, or fd7a:115c:a1e0 and what follows it (the tailnet's IPv6 range): the ranges a
               tailnet hands out. The key is the address, which is no name.

Where the names are kept. They are not in this repository, not even as hashes: a hash of a short name is
found by trying every name, in seconds, and the history keeps it for ever, so a hash list would publish
the very names it guards. CI reads them from the repository secret SHEAF_PUBLIC_TREE_TERMS (ci.yml). A run
that has no terms is no proof: in CI (CI is set) the test fails, and on a laptop it is skipped with a note,
and `python tests/public_tree.py` refuses to say "clean". A run from a fork has no secret and fails: the
people who push here have it.

A hit that is not a leak goes in ALLOW with the reason, one entry for each file and each address; an entry whose
hit has gone is reported too, so the list never keeps a reason for nothing. Names have no allowance: they
are removed. The guard's own two files may hold the addresses that ALLOW lists and the one the tests plant,
and nothing else. To scan by hand: SHEAF_PUBLIC_TREE_TERMS='a,b' python tests/public_tree.py."""
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent

# (path, key) -> why it is not a leak
ALLOW: dict = {
    ("SPEC.md", "100.64.0.0"):
        "the start of 100.64.0.0/10, the range a tailnet hands out, named in the spec as the range the peer route accepts",
    ("SPEC.md", "fd7a:115c:a1e0::"):
        "the start of the tailnet's IPv6 range, named in the spec as the range the peer route accepts: a range, no host",
    ("src/sheafmd/hub/channel.py", "fd7a:115c:a1e0::"):
        "the same IPv6 range as the network the peer route accepts: a range, no host",
    ("src/sheafmd/hub/channel.py", "100.64.0.0"):
        "the same range, 100.64.0.0/10, as the network the peer route accepts: a range, no host",
    ("tests/test_peer_channel.py", "100.64.0.1"):
        "a made-up address just inside 100.64.0.0/10, to show that the peer route accepts the range",
    ("tests/test_peer_channel.py", "100.127.255.254"):
        "a made-up address at the top end of 100.64.0.0/10, to show that the peer route accepts the whole range",
    ("tests/test_peer_channel.py", "100.63.255.255"):
        "a made-up address one below 100.64.0.0/10, to show that the peer route refuses what is outside",
    ("tests/test_peer_channel.py", "100.128.0.1"):
        "a made-up address one above 100.64.0.0/10, to show that the peer route refuses what is outside",
    ("tests/test_peer_channel.py", "100.101.102.103"):
        "a counting sequence that no host has, used as the peer's address in a test",
    ("tests/test_peer_channel.py", "fd7a:115c:a1e0::1"):
        "the start of the tailnet's IPv6 range inside a test address, to show that the peer route accepts the range",
    ("tests/two_hubs.py", "100.101.102.103"):
        "a counting sequence that no host has, sent as the peer's address in a two-hub test",
    ("tests/test_peer_channel.py", "100.1.1.1"):
        "a made-up address outside 100.64.0.0/10, to show that the peer route refuses it",
}

WORD = re.compile(r"[a-z0-9]+")
ADDRESS = re.compile(r"(?<![\d.])100\.\d{1,3}\.\d{1,3}\.\d{1,3}(?!\d)|(?<![0-9a-f:])fd7a:115c:a1e0[0-9a-f:]*", re.I)
OWN_FILES = ("tests/public_tree.py", "tests/test_public_tree.py")
TEST_ADDRESSES = ("100.64.1.2", "fd7a:115c:a1e0")    # one planted by tests/test_public_tree.py; the other the range itself, no host


class Hit(NamedTuple):
    path: str
    line: int      # 0 when it is the path itself, or a stale allowance
    key: str


def terms_from(value):
    """The terms of a list as the environment holds it, each as its lower-case words."""
    terms = []
    for number, raw in enumerate((r for r in re.split(r"[,\n]", value or "") if r.strip()), 1):
        if not raw.isascii():
            raise ValueError(f"term {number} has a character outside a-z and 0-9 that the scan cannot read, and would match as a cut-short word")
        words = " ".join(WORD.findall(raw.lower()))
        if words:
            terms.append(("=" if raw.strip().startswith("=") else "") + words)
    return tuple(terms)


def scan_text(text, terms):
    """The (line, key) of every hit in the text."""
    lowered = text.lower()
    found = []
    for match in ADDRESS.finditer(text):
        found.append((text.count("\n", 0, match.start()) + 1, match.group(0).lower()))
    for number, term in enumerate(terms, 1):
        whole = term.startswith("=")
        pattern = r"[^a-z0-9]*".join(map(re.escape, term.lstrip("=").split()))
        if whole:
            pattern = rf"(?<![a-z0-9]){pattern}(?![a-z0-9])"
        lines = {lowered.count("\n", 0, m.start()) + 1 for m in re.finditer(pattern, lowered)}
        found += [(line, f"term {number}") for line in sorted(lines)]
    return sorted(found)


def tracked(root):
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True).stdout
    return [os.fsdecode(p) for p in out.split(b"\0") if p]


def scan_tree(root, allow=None, terms=None):
    """Every hit in a tracked file or path of the checkout at `root`, then every allowance that matched nothing."""
    allow = ALLOW if allow is None else allow
    terms = terms_from(os.environ.get("SHEAF_PUBLIC_TREE_TERMS")) if terms is None else terms
    root = Path(root)
    hits, used = [], set()

    def add(path, line, key):
        if (path, key) in allow:
            used.add((path, key))
        else:
            hits.append(Hit(path, line, key))

    for path in tracked(root):
        for _, key in scan_text(path, terms):
            add(path, 0, key)
        own = path in OWN_FILES
        file = root / path
        if file.is_symlink() or not file.is_file():
            continue
        for line, key in scan_text(file.read_bytes().decode("utf-8", "replace"), terms):
            if own and key in {k for _, k in allow} | set(TEST_ADDRESSES):
                continue
            add(path, line, key)
    hits += [Hit(path, 0, f"allowed but absent: {key}") for path, key in allow if (path, key) not in used]
    return hits


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    terms = terms_from(os.environ.get("SHEAF_PUBLIC_TREE_TERMS"))
    if not terms:
        print("SHEAF_PUBLIC_TREE_TERMS is not set: with no names to look for, a scan proves nothing", file=sys.stderr)
        return 2
    hits = scan_tree(argv[0] if argv else ROOT, terms=terms)
    for hit in hits:
        print(f"{hit.path}:{hit.line} {hit.key}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
