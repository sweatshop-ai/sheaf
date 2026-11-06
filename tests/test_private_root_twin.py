"""A hub with no private root (SPEC 9.9) behaves as it did before private roots (the gate): one scripted session (create, edit,
tick, close to the owner, change the owner, share again, pull a remote change) runs on the code of a named older commit
and on this tree, with the git dates and the hub's clock pinned, and the files and the git log of the list repo must
match byte for byte. tests/twin_session.py is the session; it uses only what the older commit has."""
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREE = HERE.parent
# The commit before private roots: sheaf's main when the gate was written. A later change never moves it, so the
# session is compared with the same behaviour for as long as the gate stands.
BASE = "ca80ef57b98a62f83e170d7ca84b45f03ae4de3c"
SOURCE = "https://github.com/sweatshop-ai/sheaf.git"


def git(*args, **kw):
    return subprocess.run(["git", "-C", str(TREE), *args], capture_output=True, **kw)


def base_source(into: Path) -> Path:
    """`src` of the commit BASE, taken out of git's objects into `into`. A shallow checkout (CI fetches two commits)
    may not hold it, so it is fetched by its hash into a scratch repo then, leaving this checkout alone; if it cannot
    be, the test fails: a gate that skips is no gate."""
    scratch = into.parent / "base.git"
    if git("cat-file", "-e", f"{BASE}^{{commit}}").returncode == 0:
        archive = ["git", "-C", str(TREE), "archive", "--format=tar", BASE, "src"]
    else:
        subprocess.run(["git", "init", "-q", "--bare", str(scratch)], check=True)
        got = subprocess.run(["git", "-C", str(scratch), "fetch", "--quiet", "--depth=1", SOURCE, BASE],
                             capture_output=True, text=True)
        assert got.returncode == 0, f"the base commit {BASE} is not here and cannot be fetched: {got.stderr}"
        archive = ["git", "-C", str(scratch), "archive", "--format=tar", BASE, "src"]
    packed = subprocess.run(archive, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(packed)) as tar:
        tar.extractall(into, filter="data")
    return into / "src"


def run_session(src: Path, work: Path) -> Path:
    """The session on the code in `src`; the work folder it left, whose `list` is the repo to compare."""
    work.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "SHEAF", "GIT_"))}
    got = subprocess.run([sys.executable, "-P", str(HERE / "twin_session.py"), str(work)], capture_output=True,
                         text=True, timeout=300, env={**env, "PYTHONPATH": str(src)})
    assert got.returncode == 0, got.stdout + got.stderr
    assert (work / "imported-from.txt").read_text(encoding="utf-8") == str((src / "sheafmd").resolve())    # that copy ran
    return work / "list"


def files_of(repo: Path) -> dict:
    return {p.relative_to(repo).as_posix(): p.read_bytes() for p in sorted(repo.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(repo).parts}


def log_of(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "log", "--reverse", "--name-status", "--format=fuller", "--date=raw"],
                          check=True, capture_output=True, text=True).stdout


def test_twin_no_private_root_byte_for_byte(tmp_path):
    before = run_session(base_source(tmp_path / "base"), tmp_path / "before")
    after = run_session(TREE / "src", tmp_path / "after")
    log = log_of(before)
    assert "-> acme/blog/private/b/" in log and "private/a/" in log and log.count("move:") == 3     # the session did move
    assert "remote edit" in log and "tick:" in log
    assert files_of(after) == files_of(before)
    assert log_of(after) == log
