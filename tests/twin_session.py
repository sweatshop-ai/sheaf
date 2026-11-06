"""One scripted session on a hub with no private root, run by tests/test_private_root_twin.py once against the
code of a named older commit and once against this tree (`python twin_session.py <work folder>`, with PYTHONPATH
naming the `src` folder to run). It writes the list repo under <work folder>/list; the test compares those files
and the git log of the two runs byte for byte. It uses only what the older commit has too."""
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path

work = Path(sys.argv[1]).resolve()
DATE = "2026-01-02T03:04:05+00:00"
NOW = 1_767_323_045                                    # the same instant
for var, value in {"SHEAF_HOME": work / "home", "HOME": work / "home", "XDG_RUNTIME_DIR": work / "run",
                   "XDG_STATE_HOME": work / "state", "XDG_CONFIG_HOME": work / "conf", "TMPDIR": work / "tmp"}.items():
    Path(value).mkdir(parents=True, exist_ok=True)
    os.environ[var] = str(value)
os.environ.update(SHEAF_NAME="Ada", GIT_AUTHOR_DATE=DATE, GIT_COMMITTER_DATE=DATE, GIT_CONFIG_GLOBAL="/dev/null",
                  GIT_CONFIG_SYSTEM="/dev/null", SHEAF_PORT="39001")

import sheafmd  # noqa: E402
from sheafmd import paths  # noqa: E402
from sheafmd.hub import place, proxy, the_list  # noqa: E402
from sheafmd.hub.core import Hub  # noqa: E402
from sheafmd.mcp import Caller, Door  # noqa: E402
from sheafmd.source import md_hash  # noqa: E402

(work / "imported-from.txt").write_text(str(Path(sheafmd.__file__).resolve().parent), encoding="utf-8")


def git(at, *args):
    return subprocess.run(["git", "-C", str(at), "-c", "user.name=box", "-c", "user.email=box@example.com", *args],
                          check=True, capture_output=True, text=True).stdout


remote, repo, other = work / "remote.git", work / "list", work / "other"
subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True, capture_output=True)
(repo / ".sheaf.toml").write_text('versions = "root"\ncommit = true\npush = true\n', encoding="utf-8")
(repo / "projects.toml").write_text('[projects."acme/blog"]\nmembers = ["a", "b"]\nstatus = "live"\n', encoding="utf-8")
(repo / "acme" / "blog").mkdir(parents=True)
(repo / "acme" / "blog" / "2026-01-01-notes.md").write_text("# Notes\n\nThe project's first page.\n", encoding="utf-8")
git(repo, "add", "-A")
git(repo, "commit", "-q", "-m", "first")
git(repo, "push", "-q", "origin", "HEAD:main")

member = {"roots": [str(repo)]}
cfg = proxy.parse({"origin": "https://front.example.com", "socket": "/run/sheaf-proxy/hub.sock",
                   "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                   "members": {"id-a": {"name": "Member A", "short": "a", "email": "a@example.com", **member},
                               "id-b": {"name": "Member B", "short": "b", "email": "b@example.com", **member}}},
                  "the twin")
hub = Hub(port=39001, key=paths.ensure_key(), started_by="test", clock=lambda: NOW, proxy=cfg)
hub.the_list = the_list.TheList(hub, the_list.ListConfig(repo, "acme/record", 1, work / "token"))
root = hub.the_list.root()
door, caller = Door(hub), Caller("Claude")
DOC = f"{root.name}/acme/blog/2026-01-02-plan.md"


def tool(name, **args):
    _, out = door.handle(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": name, "arguments": args}}).encode(), caller)
    got = out["result"]
    assert not got["isError"], got
    return json.loads(got["content"][0]["text"])


def now_text():
    return Path(hub.file(DOC)).read_text(encoding="utf-8")


def rewrite(change):
    text = now_text()
    tool("update", doc=DOC, text=change(text), expected_hash=md_hash(text))


def by_hand(change):
    """A change to the front matter made outside the door, as a person's editor or a pull makes it, then the poll's
    move of the file to its home."""
    with place.held(hub, DOC):
        Path(hub.file(DOC)).write_text(change(now_text()), encoding="utf-8")
        hub.committed(DOC, what="edit", by="Ada")
    place.place(hub, DOC)


tool("create", doc=DOC, text="---\nclient: acme\nproject: blog\n---\n# Plan\n\n- [ ] Approve\n\nFirst paragraph.\n")
hub.entry(DOC)                                                                          # a page is opened: rendered, its versions kept
rewrite(lambda t: t.replace("First", "Second"))                                         # edit
hub.entry(DOC).live.refresh(force=True)
with place.held(hub, DOC):                                                              # tick, as the list's tick writes it
    Path(hub.file(DOC)).write_text(now_text().replace("- [ ] Approve", "- [x] Approve"), encoding="utf-8")
    hub.committed(DOC, cfg.members["id-a"], "tick")
by_hand(lambda t: t.replace("client: acme", "visibility: owner\nowner: a\nclient: acme"))   # closed: to a private home
by_hand(lambda t: t.replace("owner: a", "owner: b"))                                    # owner change: to the other's
by_hand(lambda t: t.replace("visibility: owner\n", "").replace("owner: b\n", ""))       # shared again: back to the project
hub.commits.settle()

subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True, capture_output=True)    # a remote change
doc = other / "acme" / "blog" / "2026-01-02-plan.md"
doc.write_text(doc.read_text(encoding="utf-8").replace("Second", "Third"), encoding="utf-8")
git(other, "commit", "-q", "-am", "remote edit")
git(other, "push", "-q", "origin", "HEAD:main")
hub.commits.poll(hub.roots.all())                                                       # the watcher's pull
hub.commits.settle()
hub.commits.stop()
