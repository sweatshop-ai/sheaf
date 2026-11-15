# 02: How an agent session on a laptop gets a page onto a tiroir

**Type:** research
**Status:** open
**Blocked by:** none
**Map:** ../map.md

## Question

What ways exist, or could exist with what sheaf already has, for an agent session on a laptop to put a page on a tiroir's sheaf and to read back what the person did there (edits, comments, Tells)? Candidates to weigh against each other: a git root pushed and pulled; a file sync like `brain-sync`; the hub's MCP door with an MCP token over Tailscale (SPEC 9.7); the relay of a forked session (SPEC 9.14); the remote seat (GLOSSARY). For each: what already works, what is missing, latency, what happens to a save made on the page while the agent writes the file, and what crosses the network. Facts only; the choice is ticket 05.
