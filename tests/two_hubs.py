"""Two hubs in one process, each with a state of its own, joined the way the channel joins them (ticket 23, seam 2): the agency
tiroir's call to a client goes in as a POST of `/_/tiroir/<verb>` on the client's handler, from the tailnet, with a peer token.
No socket. The paths of a hub are read from the environment at each call, so every entry into a site sets its own `SHEAF_HOME`
and `TMPDIR` first, and puts the test's back after."""
import json
import os
import pwd
import tempfile
from contextlib import contextmanager
from pathlib import Path

from helpers import Front, browser_on, door, rpc

from sheafmd import paths
from sheafmd.hub import proxy
from sheafmd.hub.core import Hub
from sheafmd.hub.state import Tokens

TAILNET = {"X-Forwarded-For": "100.101.102.103"}


class Site:
    """One tiroir: its hub, its handler, its folders, its members' agent tokens."""

    def __init__(self, tmp_path, name, port, origin, members, **table):
        self.name, self.origin, self.port = name, origin, port
        self.home, self.tmp = tmp_path / f"{name}-home", tmp_path / f"{name}-tmp"
        self.tmp.mkdir()
        self.roots = {}
        table_members = {}
        for uid, (who, email, agency) in members.items():
            root = tmp_path / f"{name}-{who.lower()}-work"
            root.mkdir()
            self.roots[who.lower()] = root
            table_members[uid] = {"name": who, "short": who.lower(), "roots": [str(root)], "tokens": [f"{who.lower()}-claude"],
                                  **({"email": email} if email else {}), **({"agency": True} if agency else {})}
        with self.inside():
            self.tokens = {f"{w.lower()}-claude": Tokens().add(f"{w.lower()}-claude", client="Claude Code", write=True)
                           for w, _, _ in members.values()}
            self.hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
            self.hub.proxy = proxy.parse({"origin": origin, "socket": f"/run/sheaf-proxy/{name}.sock",
                                          "proxy_user": pwd.getpwuid(os.getuid()).pw_name, "members": table_members, **table}, "the test")
            self.browser = browser_on(self.hub)
            self.front = Front(self.hub, self.browser.handler)

    @contextmanager
    def inside(self):
        before = {k: os.environ.get(k) for k in ("SHEAF_HOME", "TMPDIR")}
        before_temp = tempfile.tempdir
        os.environ["SHEAF_HOME"], os.environ["TMPDIR"] = str(self.home), str(self.tmp)
        tempfile.tempdir = str(self.tmp)
        try:
            yield self
        finally:
            for k, v in before.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            tempfile.tempdir = before_temp

    def request(self, method, path, **kw):
        with self.inside():
            return self.front.request(method, path, **kw)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body=body if body is not None else {}, **kw)

    def make(self, who, text, doc="plan.md"):
        """A page made through the door as `who`'s agent: its address."""
        with self.inside():
            res = door(self.browser, rpc("tools/call", {"name": "create", "arguments": {"doc": doc, "text": text}}),
                       token=self.tokens[f"{who}-claude"], as_name=None)
        out = res.json()["result"]
        assert not out["isError"], out
        return json.loads(out["content"][0]["text"])["doc"]

    def peer_token(self, origin, scopes, name=None):
        with self.inside():
            return Tokens().add_peer(name or f"peer-{len(Tokens().list())}", origin, scopes)

    def revoke(self, name):
        with self.inside():
            return Tokens().revoke(name)

    def text(self, doc):
        with self.inside():
            return self.hub.file(doc).read_text(encoding="utf-8")

    def files(self):
        """Every file this site's own state, its members' roots and its temp folder hold, as (path, bytes)."""
        for folder in (self.home, self.tmp, *self.roots.values()):
            for f in sorted(Path(folder).rglob("*")):
                if f.is_file():
                    yield f, f.read_bytes()


class Link:
    """The agency's way to one client: what `Hub.peer_call` is on the wire, here a POST on the client's handler. `mode` is `up`,
    `down` (no answer, an OSError) or `broken` (an answer that is not one). `asked` is every call, as the client received it."""

    def __init__(self, client: Site, token: str):
        self.client, self.token, self.mode, self.asked = client, token, "up", []

    def __call__(self, name, verb, body):
        self.asked.append((name, verb, body))
        if self.mode == "down":
            raise OSError("down")
        got = self.client.post(f"/_/tiroir/{verb}", body, member=None, headers={**TAILNET, "Authorization": f"Bearer {self.token}"})
        if self.mode == "broken":
            raise OSError("not an answer")
        return got.status, got.json()
