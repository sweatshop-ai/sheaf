"""The two-root fixture of the private-root tests: a list repo and a private repo, each a git work tree with a bare
remote, and two members, A (who has the private repo as their `private_root`) and B. A test imports `two_roots` and
asks it for the pieces it needs; nothing here is a test."""
import os
import pwd
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sheafmd import config, paths
from sheafmd.hub import proxy, the_list
from sheafmd.hub.core import Hub

A, B = "member-a-id", "member-b-id"


def git(at, *args):
    return subprocess.run(["git", "-C", str(at), "-c", "user.name=box", "-c", "user.email=box@example.com", *args],
                          check=True, capture_output=True, text=True).stdout


def make_repo(base: Path, name: str) -> Path:
    """A work tree `base/name` that commits and pushes to a bare `base/name.git`, with a first commit."""
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(base / f"{name}.git")], check=True)
    repo = base / name
    subprocess.run(["git", "clone", "-q", str(base / f"{name}.git"), str(repo)], check=True, capture_output=True)
    (repo / ".sheaf.toml").write_text('versions = "root"\ncommit = true\npush = true\n', encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    git(repo, "push", "-q", "origin", "HEAD:main")
    return repo


@dataclass
class TwoRoots:
    base: Path
    list_repo: Path
    private_repo: Path

    def table(self, a: dict | None = None, b: dict | None = None) -> dict:
        """A `[proxy]` table with members A and B; `a` and `b` replace or add keys of a member's block."""
        member = {"name": "Member A", "short": "a", "roots": [str(self.list_repo), str(self.private_repo)],
                  "private_root": str(self.private_repo), **(a or {})}
        other = {"name": "Member B", "short": "b", "roots": [str(self.list_repo)], **(b or {})}
        return {"origin": "https://front.example.com", "socket": "/run/sheaf-proxy/hub.sock",
                "proxy_user": pwd.getpwuid(os.getuid()).pw_name, "members": {A: member, B: other}}

    def list_table(self) -> dict:
        return {"root": str(self.list_repo)}

    def config(self, **over) -> proxy.ProxyConfig:
        return proxy.parse(self.table(**over), "the test", self.list_table())

    def hub(self, cfg: proxy.ProxyConfig | None = None, with_list: bool = True) -> Hub:
        hub = Hub(port=config.port(), key=paths.ensure_key(), started_by="test", proxy=cfg or self.config())
        if with_list:
            hub.the_list = the_list.TheList(hub, the_list.ListConfig(self.list_repo, "acme/record", 1,
                                                                     self.base / "token"))
        return hub


def two_roots(base: Path) -> TwoRoots:
    return TwoRoots(base, make_repo(base, "list"), make_repo(base, "private"))
