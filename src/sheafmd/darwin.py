"""
sheafmd.darwin — what macOS says about a process, where Linux has /proc (SPEC 8.4, 9.4).

`hub/recover.py` reads four things about the process a pid file names before it signals it: its
state and start time, its command line, its four uids, and whether it holds a listening socket.
Linux has them in /proc. macOS has no /proc; the kernel gives the same through libproc and sysctl:

  * `proc_pidinfo(pid, PROC_PIDTBSDINFO)` fills a `struct proc_bsdinfo` (<sys/proc_info.h>): the
    state (`pbi_status`), the real, effective and saved uid, and the start time in seconds and
    microseconds since the epoch. A process that has ended (a zombie) gives nothing back.
  * `sysctl({CTL_KERN, KERN_PROCARGS2, pid})` gives argc, the executable's path, and the arguments
    as the process was started, each ended by a NUL (what /proc/<pid>/cmdline holds on Linux).
  * `lsof` names the process that listens on a TCP address. libproc can say it too, but through a
    union of socket structures whose layout this module would have to copy; `lsof` ships with macOS
    (/usr/sbin/lsof) and reads the same kernel table.

Each function returns None where the answer cannot be had: another system, a process that ended,
or one the kernel will not describe to us. The caller treats None as "no", so this fails closed.
"""
import ctypes
import ctypes.util
import struct
import subprocess
import sys

PROC_PIDTBSDINFO = 3
CTL_KERN, KERN_ARGMAX, KERN_PROCARGS2 = 1, 8, 49
LSOF = "/usr/sbin/lsof"
STATES = {1: "I", 2: "R", 3: "S", 4: "T", 5: "Z"}   # SIDL SRUN SSLEEP SSTOP SZOMB, as the letters of Linux


class BsdInfo(ctypes.Structure):
    """`struct proc_bsdinfo` of <sys/proc_info.h>, 136 bytes."""
    _fields_ = [("flags", ctypes.c_uint32), ("status", ctypes.c_uint32), ("xstatus", ctypes.c_uint32),
                ("pid", ctypes.c_uint32), ("ppid", ctypes.c_uint32),
                ("uid", ctypes.c_uint32), ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32),
                ("rgid", ctypes.c_uint32), ("svuid", ctypes.c_uint32), ("svgid", ctypes.c_uint32),
                ("rfu_1", ctypes.c_uint32), ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32),
                ("nfiles", ctypes.c_uint32), ("pgid", ctypes.c_uint32), ("pjobc", ctypes.c_uint32),
                ("e_tdev", ctypes.c_uint32), ("e_tpgid", ctypes.c_uint32), ("nice", ctypes.c_int32),
                ("start_tvsec", ctypes.c_uint64), ("start_tvusec", ctypes.c_uint64)]


_libc = None


def _lib():
    """libc (which holds libproc's functions on macOS), or None on any other system."""
    global _libc
    if _libc is None and sys.platform == "darwin":
        _libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.dylib", use_errno=True)
    return _libc


def available() -> bool:
    """Whether this is a macOS whose libproc can be called."""
    try:
        lib = _lib()
    except OSError:
        return False
    return lib is not None and hasattr(lib, "proc_pidinfo") and hasattr(lib, "sysctl")


def _bsdinfo(pid: int) -> BsdInfo | None:
    if not available():
        return None
    info = BsdInfo()
    got = _lib().proc_pidinfo(ctypes.c_int(pid), ctypes.c_int(PROC_PIDTBSDINFO), ctypes.c_uint64(0),
                              ctypes.byref(info), ctypes.c_int(ctypes.sizeof(info)))
    if got != ctypes.sizeof(info) or info.pid != pid:
        return None
    return info


def stat(pid: int) -> tuple[str, int] | None:
    """(state as Linux's letter, start time in microseconds since the epoch), or None."""
    info = _bsdinfo(pid)
    if info is None:
        return None
    return STATES.get(info.status, "?"), info.start_tvsec * 1_000_000 + info.start_tvusec


def uids(pid: int) -> tuple[int, int, int, int] | None:
    """The real, effective, saved and filesystem uid, as /proc/<pid>/status orders them. macOS has no
    filesystem uid; the kernel checks files against the effective one, so that one stands in for it."""
    info = _bsdinfo(pid)
    if info is None:
        return None
    return info.ruid, info.uid, info.svuid, info.uid


def _sysctl(mib: list[int], size: int) -> bytes | None:
    arr = (ctypes.c_int * len(mib))(*mib)
    buf = ctypes.create_string_buffer(size)
    n = ctypes.c_size_t(size)
    if _lib().sysctl(arr, ctypes.c_uint(len(mib)), buf, ctypes.byref(n), None, ctypes.c_size_t(0)) != 0:
        return None
    return buf.raw[:n.value]


def cmdline(pid: int) -> bytes | None:
    """The arguments the process was started with, each ended by a NUL, as /proc/<pid>/cmdline holds
    them; None when the kernel gives none (it ended, or is not ours)."""
    if not available():
        return None
    argmax = _sysctl([CTL_KERN, KERN_ARGMAX], ctypes.sizeof(ctypes.c_int))
    if argmax is None:
        return None
    raw = _sysctl([CTL_KERN, KERN_PROCARGS2, pid], struct.unpack("i", argmax)[0])
    if raw is None or len(raw) < 4:
        return None
    argc = struct.unpack_from("i", raw)[0]
    rest = raw[4:]
    end = rest.find(b"\0")                       # the executable's path, then NULs up to the arguments
    if argc < 1 or end < 0:
        return None
    rest = rest[end:].lstrip(b"\0")
    args = rest.split(b"\0")[:argc]
    if len(args) < argc:
        return None
    return b"".join(a + b"\0" for a in args)


def listens(pid: int, port: int) -> bool:
    """Whether `pid` holds a socket that listens on 127.0.0.1:`port`."""
    try:
        r = subprocess.run([LSOF, "-nP", "-a", "-p", str(pid), f"-iTCP@127.0.0.1:{port}", "-sTCP:LISTEN", "-Fp"],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return f"p{pid}" in r.stdout.split()
