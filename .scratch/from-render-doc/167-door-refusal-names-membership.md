# 167: The door's refusal for a non-member should name the project, not a missing root

**Status:** open (the fix never reached this repo: only the ticket was written)

**From:** render-doc ticket 167 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/mcp.py:133` (`NOT_IN_A_ROOT`), `:763` (`_create`), `:781-782`; `src/sheafmd/hub/core.py:998` (`Hub.granted`); SPEC section 12

**Size:** one session, tests for each case listed below

- [ ] **A non-member's `create` is told the path is in no root.** In proxy mode, in a root that has a `projects.toml`, a door `create` at project depth by a token bound to a member who is not in that project's `members` is refused with "<path> is not inside a root of this hub; ..." (`src/sheafmd/mcp.py:781-782`, constant at `:133`). That sends callers looking for a missing root. Wanted: a sentence that names the project and membership and never says "root" ("<path> cannot be made: the token's member is not in the project <client>/<project>."). The same bytes must answer a project that does not exist and an unreadable `projects.toml`. It must not list the project's members.

- [ ] **Limits of the new sentence.**
  - Give it only when the address itself is not granted (`projects.grants(entries, rel, short)` is false). A refusal that comes only from the real-path half of `Hub.granted` (`src/sheafmd/hub/core.py:998`; a link inside the member's own project pointing into another project) keeps today's answer.
  - Run the address-only check before the `place.undecided`/`held` lookups in `_create` (`src/sheafmd/mcp.py:763`), so a non-member cannot tell an undecided private root from the ordinary case.
  - A path in no root, another member's root, a private root, and the hub key or an unbound token keep the old sentence.
  - Tests for each case, and SPEC section 12 names the new sentence next to the old.
