"""
sheafmd.hub.sock — the hub's own socket, `<runtime>/hub-<port>.sock` (SPEC 11.4, D16).

A Tell message names this socket as its sender, so it has to be a place a session can send to.
What arrives is written to the diagnostics log as `tell-socket-message` (clipped there to 2,000
characters) and does nothing else: no comment, no push, no job. The socket is the user's alone
(0600 in the 0700 runtime folder). A socket that cannot be made costs the hub nothing: it is
written down and the hub serves without it.
"""
import os
import socket
import stat
import threading
import time

from .. import diagnostics, paths

MAX_READ = 64 * 1024            # one message is read up to here, the rest is dropped
READ_SECONDS = 2.0              # a message is read for this long at most, however it trickles in
READERS = 16                    # connections read at once; the rest are closed unread


class TellSocket:
    def __init__(self, port: int):
        self.port = port
        self.path = paths.hub_socket(port)
        self._srv: socket.socket | None = None
        self._ino: tuple[int, int] | None = None
        self._closed = threading.Event()
        self._readers = threading.BoundedSemaphore(READERS)

    def start(self) -> bool:
        """Listen. True when the socket is up; False after writing down why not."""
        try:
            self._srv = self._bind()
        except (OSError, paths.PathError) as e:
            self._srv = None
            diagnostics.record("hub", "tell-socket-failed", None, path=str(self.path),
                               error=f"{type(e).__name__}: {e}")
            return False
        threading.Thread(target=self._accept, daemon=True).start()
        return True

    def _bind(self) -> socket.socket:
        paths.private_dir(self.path.parent)
        try:
            st = os.lstat(self.path)
        except FileNotFoundError:
            pass
        else:
            # What a hub that crashed left; the port bind guarantees no other hub is using it.
            # Anything else at this path is not ours to remove.
            if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid():
                raise OSError(f"{self.path} exists and is not a socket of yours")
            self.path.unlink()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.bind(str(self.path))
            os.chmod(self.path, 0o600)
            s.listen(8)
            st = os.lstat(self.path)
            self._ino = (st.st_dev, st.st_ino)
        except BaseException:
            s.close()
            raise
        return s

    def _accept(self):
        srv = self._srv
        srv.settimeout(0.25)                        # so that a stop is noticed
        while not self._closed.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if self._readers.acquire(blocking=False):
                threading.Thread(target=self._read, args=(conn,), daemon=True).start()
            else:
                conn.close()

    def _read(self, conn: socket.socket):
        data = b""
        end = time.monotonic() + READ_SECONDS
        try:
            with conn:
                while len(data) < MAX_READ and (left := end - time.monotonic()) > 0:
                    conn.settimeout(left)
                    chunk = conn.recv(min(65536, MAX_READ - len(data)))
                    if not chunk:
                        break
                    data += chunk
        except OSError:
            pass                                    # slow, reset or silent: what came is logged
        finally:
            self._readers.release()
        if data:
            diagnostics.record("hub", "tell-socket-message", None,
                               message=data.decode("utf-8", errors="replace"))

    def stop(self):
        """Stop listening and remove the socket file, if it is still the one made here."""
        self._closed.set()
        srv, self._srv = self._srv, None
        if srv is not None:
            try:
                srv.close()
            except OSError:
                pass
        if self._ino is not None:
            try:
                st = os.lstat(self.path)
                if (st.st_dev, st.st_ino) == self._ino:
                    self.path.unlink()
            except OSError:
                pass
            self._ino = None
