# 02: How an agent session on a laptop gets a page onto a tiroir

**Type:** research
**Status:** resolved (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

What ways exist, or could exist with what sheaf already has, for an agent session on a laptop to put a page on a tiroir's sheaf and to read back what the person did there (edits, comments, Tells)? Candidates to weigh against each other: a git root pushed and pulled; a file sync like `brain-sync`; the hub's MCP door with an MCP token over Tailscale (SPEC 9.7); the relay of a forked session (SPEC 9.14); the remote seat (GLOSSARY). For each: what already works, what is missing, latency, what happens to a save made on the page while the agent writes the file, and what crosses the network. Facts only; the choice is ticket 05.

## Answer

Full findings: branch `research/02-laptop-to-tiroir` (commit 9e2d624), file `.scratch/sheaf-in-open-webui/research/02-laptop-to-tiroir.md`. Facts only; the choice is ticket 05.

**Common to all five ways.** The hub listens on 127.0.0.1 only and refuses any other Host header (`hub/server.py:49-54`, `auth.py:27`). The front's proxy does not carry `/_/mcp` (SPEC 9.9). A page save against an older text is merged while the hub still knows that text (SPEC 7.3). The hub's file lock stops only other sheaf writers: a non-sheaf writer landing during the hub's read-merge-write is overwritten (`source.py:229-239`).

| Way | Works today | Missing / limits | Lag laptop → page | Page save while the agent writes | What crosses the network |
|---|---|---|---|---|---|
| Git root, pushed and pulled | Yes on the tiroir side: one commit per write, push, pull on a poll (`commits.py:49-50, 448-470`); the list's root runs this way | Same lines changed on both sides → `push-diverged`, hub stops until a person resolves it; Tells never travel through git | ≤ ~60 s + 1 s | Merged by git, or `push-diverged` on a line conflict | File contents via GitHub; laptop and tiroir never talk |
| File sync like `brain-sync` | One-way only | The next rsync writes the laptop copy back over a page edit within 15 min (`brain-sync.sh:100-104, 137`); nothing returns to the laptop | ≤ 15 min | Lost | Files over ssh |
| MCP door with a token | `create`/`update`/`read` complete in the hub; `update` refused when the hash moved | Reachable from the laptop only via an `ssh -L` tunnel; the library door deployed on tiroir-tt has no `create`/`update`, five read/reply tools only (tiroir-library-mcp `sheaf_door.py:20-21, 62`); Tells queued until the agent next calls `documents`; the door returns a loopback URL the person cannot open | One call | Merged; stale `update` refused | MCP calls through the tunnel |
| Relay of a fork (SPEC 9.14) | Tells only | Relay token reaches two routes; list's sheaves in proxy mode only. Side fact: with the member's front sign-in, `POST /_/sessions` does not check the session was forked from a box transcript (`handler.py:1463-1497`) | n/a for pages | n/a | Tells |
| Remote seat | Everything works as locally | The agent becomes a tiroir session; in proxy mode it needs the hub's account or a door token | Local | Merged | ssh session |

**Not checked:** no remote machine was touched, so tiroir-tt's accounts, Caddy and Tailscale setup are unverified; the library door was read from the `sorin` checkout at a44cb97, not its main branch.
