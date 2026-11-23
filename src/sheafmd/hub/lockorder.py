"""The one order of the hub's locks (SPEC 9.11, "One lock order"). A thread that holds a lock takes only locks that come
AFTER it in `ORDER`; it never waits for one that comes before. `tests/lockorder.py` wraps the locks and fails any
acquisition against this list, in the move, Tell, save, door create, queue_agent and forget suites.

    stop      `Hub._stop_lock`: an upgrade stop, which takes the admission lock inside it
    moves     `moves._LOCK`: one move at a time; also a door `create` in a loose root, `Tell.queue_agent`'s look at an address, an Archive, Restore or Keep from its read of the path to its write; a root's forget (`Hub.forget_root`); a page's cancel from its root compare to its job's stop (the wait on the document comes after); a loose root's take-back (`Loose.drop`, its forget's wait after); a move to another tiroir and a restore from the trash, which take the page's lock only when it is free (`moves.page_held`). A Delete still waits for the page's lock under it
    admit     `Hub.admit`: every Tell start and the upgrade stop; held for a look and a mark, never for a wait on a file,
              a render or the hub's lock
    name      `place.held`: a rectoverso's name (`place._name_lock`); two names only under the moves' lock (`moves.exclusive()`, the one place two are held; their order is then free), or a link's name before its target's
    hub       `Hub._lock`
    doc       `LiveDocument._lock`
    file      `source.file_lock`: the flock of one .md (`update_file`, `update_beneath`, a move's link)
    folders   `place.folders_lock`: a project's private folders; after a file's lock (`place` takes the file's, then this)
    commit    a repo's commit lock (`Commits._repo_lock`), also under a pull's guard of names and files
    store     the thread lock of a state store (`Forwards`, `Waiting`, ...): innermost, held for a read or a write of its file

A path that needs a lock earlier in the list than one it holds does not wait for it: it lets go, takes it, and looks again
(a move marks a page "moving" under the admission lock and renames under the name's and file lock, never under admit)."""

ORDER = ["stop", "moves", "admit", "name", "hub", "doc", "file", "folders", "commit", "store"]
