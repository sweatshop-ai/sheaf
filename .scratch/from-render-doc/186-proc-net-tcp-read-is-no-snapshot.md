# 186: A read of /proc/net/tcp is no snapshot, so the peer lookup can list one socket twice

**Claimed by:** Kenji

**Status:** in review (#636). Reported by Kenji on 2026-11-23.

**Priority:** high. The failure turned main's CI red on a change that does not touch it, and the same read sits in the product's /proc path.

**Blocked by:** none

**From:** main's CI run 45224686146 on 899a25cf (the merge of #634), job `ubuntu-24.04 py3.13`, Tests step: `1 failed, 10986 passed, 6 skipped`. The runs on 7ad84b69 and later were green on the same code.

**Where:** `src/sheafmd/hub/peer.py` `_owners`, `_proc_owners`, `sockets`, `_selftest`; `tests/test_hub_peer_lookup.py`.

## Failure

`tests/test_hub_peer_lookup.py::test_a_kernel_that_finds_nothing_over_netlink_is_asked_again_in_proc` (gw2), at line 109:

```
assert peer.owners(conn_of(cli)) == [ME]
E  assert [20301, 20301] == [20301]
```

The test turns the netlink answer into "nothing", so `sockets` reads `/proc/net/tcp`. That table held the client's end of the connection twice. Host state at the end of the job: load average 32.95 / 27.70 / 18.00 on the t-compute runner, which has 32 cores shared by three runners and one network namespace.

## Cause

The kernel builds `/proc/net/tcp` piece by piece, one `read()` at a time. Between two reads it resumes by position in the hash table, so a socket opened or closed elsewhere in the meantime shifts the rows: a row can be listed again, or skipped. `_owners` reads the file whole (`read_bytes`, several `read()` calls) and takes every matching row, so under socket churn one socket is counted more than once.

This is a race in the reading, not a defect that a later commit hid: 7ad84b69 does not touch `peer.py`. Its CI run went green because no row shifted at the wrong moment.

## Reproduction (laptop, load 2.5, kernel 7.0)

The script holds one loopback connection. Ten threads open and close loopback pairs meanwhile, and the main thread counts the connection's rows in `/proc/net/tcp`, reading the file whole the way `_owners` does. Three 60-second runs:

| Run | Reads | Reads with more than one row |
|---|---|---|
| 1 | 784 | 4, one of them with 22 rows |
| 2 | 19898 | 0 |
| 3 | 156 | 0 |

Every repeated row had the same inode and uid (`59521954/1000`): it is the same socket, listed more than once. An earlier 20-second run with six threads gave 1 duplicate in 47 reads. The script, run with `python3 -I dup.py 60`:

```python
# Churn loopback sockets in threads while a target connection's /proc/net/tcp rows are counted.
import socket, threading, time, sys
from pathlib import Path
stop = False
def churn():
    while not stop:
        try:
            s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(8)
            cs = []
            for _ in range(20):
                c = socket.socket(); c.connect(s.getsockname()); a, _ = s.accept(); cs += [c, a]
            for x in cs: x.close()
            s.close()
        except OSError:
            pass
ts = [threading.Thread(target=churn, daemon=True) for _ in range(10)]
for t in ts: t.start()
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
cli = socket.socket(); cli.connect(srv.getsockname()); acc, _ = srv.accept()
lp, rp = cli.getsockname()[1], cli.getpeername()[1]
key = f"0100007F:{lp:04X} 0100007F:{rp:04X}"
reads = dups = 0; t0 = time.time()
while time.time() - t0 < float(sys.argv[1]):
    rows = [l.split()[9] + "/" + l.split()[7] for l in Path("/proc/net/tcp").read_bytes().decode().splitlines() if key in l]; n = len(rows)
    reads += 1
    if n != 1: dups += 1; print("rows:", rows)
stop = True
print("reads", reads, "anomalies", dups)
```

## Impact

- **Tests:** every test that reads `/proc/net/tcp` and compares a list for equality can fail this way: `test_the_netlink_answer_and_the_proc_answer_are_the_same`, `test_a_kernel_that_will_not_answer_over_netlink_is_asked_in_proc`, `test_a_netlink_answer_that_is_cut_short_is_asked_in_proc` and the one that failed.
- **Product, a duplicate row:** `check` compares the set of uids, so it accepts duplicates. `_selftest` compares `found != [os.geteuid()]`, so a duplicate at hub start reports `off`. The hub then prints that it does not check who is at the other end of a connection and records `peer-check-off`. This applies only where `/proc` is read: a host with no `tcp_diag`, or a socket that netlink lists with inode 0.
- **Product, a skipped row:** a missed row is the other half of the same race. `check` then finds nothing and refuses the sign-in link as unknown. This was not observed in the reproduction, which counted only extra rows.

## Fix direction

- [ ] Red first: a test that churns loopback sockets while it reads the owner of a held connection through `/proc` (`NETLINK` off), and expects exactly `[ME]` every time. It must fail on main within a bounded time. If churn alone does not fail it reliably on CI, a `PROC_NET` double whose table lists the row twice (the case seen above) is the deterministic red test, with the churn test as evidence.
- [ ] `_owners` or `_proc_owners`: collapse rows of the same socket, one `Socket` per inode, keeping the order in which they were first seen. Inode 0 rows (sockets no process holds) stay as they are, because they carry no identity to collapse on.
- [ ] A skipped row: when `/proc` finds nothing, read it once more before answering "no such socket". Decide in the PR whether one retry is enough, and give the reason in the box.
- [ ] `_selftest`: compare the set of uids, as `check` does, so the self-test and the check judge the same answer the same way.
