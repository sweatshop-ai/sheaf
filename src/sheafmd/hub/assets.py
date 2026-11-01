"""The hub's mount assets (#116): `/_/mount.js` and `/_/mount.css`, read once when the hub starts and named by their
content (#179).

A browser keeps an asset asked by its name (`?v=<tag>`) for a year, so a name must serve one body forever. The name is
the start of the body's sha256, and the hub serves the bytes it read at start, not the files on disk: an upgrade in
place reinstalls the package under the running hub and restarts it seconds later, and in between the old hub still
serves its own files under their own name. A rollback is the same the other way, so neither needs a new version.
"""
import hashlib
import json
from dataclasses import dataclass
from importlib import resources

# The files each mount asset joins, in order: the loader's own, then the page's and the list's, which their pages of
# their own inline.
MOUNT_ASSETS = {"mount.js": ("mount.js", "page.js", "list.js"), "mount.css": ("mount.css", "page.css", "list.css")}
TAG_LENGTH = 16                       # hex digits of the sha256: 64 bits, the name of one body
VERSION_MARK = b"'@@SHEAF_VERSION@@'"


@dataclass(frozen=True)
class Asset:
    body: bytes
    tag: str                          # the `?v=` that names this body


def installed():
    """The page files of the installed package."""
    return resources.files("sheafmd") / "page"


def load(version: str, page=None) -> dict:
    """Each mount asset as the hub of `version` serves it: the files of `page` (the installed ones by default) joined,
    and the version written into mount.js, which tells an upgrade from a remount by it."""
    page = installed() if page is None else page
    out = {}
    for name, files in MOUNT_ASSETS.items():
        body = b"\n".join((page / f).read_bytes() for f in files)
        if name == "mount.js":
            body = body.replace(VERSION_MARK, json.dumps(version).encode(), 1)
        out[name] = Asset(body, hashlib.sha256(body).hexdigest()[:TAG_LENGTH])
    return out
