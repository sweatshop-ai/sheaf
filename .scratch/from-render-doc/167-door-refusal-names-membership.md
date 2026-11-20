# 167: The door's refusal for a non-member should name the project, not a missing root

**Claimed by:** Kwame 2026-11-20 17:44

**Status:** done, merged as 21b55685 (PR 490)

**Blocked by:** none

**From:** render-doc ticket 167 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/mcp.py:133` (`NOT_IN_A_ROOT`), `:763` (`_create`), `:781-782`; `src/sheafmd/hub/core.py:998` (`Hub.granted`); SPEC section 12

**Size:** one session, tests for each case listed below

- [x] **A non-member's `create` is told the path is in no root.** In proxy mode, in a root that has a `projects.toml`, a door `create` at project depth by a token bound to a member who is not in that project's `members` is refused with "<path> is not inside a root of this hub; ..." (`src/sheafmd/mcp.py:781-782`, constant at `:133`). That sends callers looking for a missing root. Wanted: a sentence that names the project and membership and never says "root" ("<path> cannot be made: the token's member is not in the project <client>/<project>."). The same bytes must answer a project that does not exist and an unreadable `projects.toml`. It must not list the project's members.

- [x] **Limits of the new sentence.**
  - Give it only when the address itself is not granted (`projects.grants(entries, rel, short)` is false). A refusal that comes only from the real-path half of `Hub.granted` (`src/sheafmd/hub/core.py:998`; a link inside the member's own project pointing into another project) keeps today's answer.
  - Run the address-only check before the `place.undecided`/`held` lookups in `_create` (`src/sheafmd/mcp.py:763`), so a non-member cannot tell an undecided private root from the ordinary case.
  - A path in no root, another member's root, a private root, and the hub key or an unbound token keep the old sentence.
  - Tests for each case, and SPEC section 12 names the new sentence next to the old.

## Evidence

- PR 490 merged as 21b55685; CI run 44782241227, all 6 slices success; review round recorded, exit 0 (GO).
- `tests/test_hub_grants.py` and `tests/test_hub_place.py`: 141 passed locally; the new test failed before the fix with the old sentence.
- `Hub.project_refused` (`src/sheafmd/hub/core.py`) judges the address alone; `_created` (`src/sheafmd/mcp.py`) calls it after `names_private` and before `place.undecided`/`held`. The first CI run caught the check placed before `names_private`, which changed the answer for `acme/private/...`; fixed.
- Tests: the non-member sentence, an unnamed project and an unreadable `projects.toml` giving the same bytes, a link into another project keeping the old sentence, the key and an unbound token, a path in no root, another member's root, and a private folder that holds the name giving a non-member the same answer. SPEC 9.7 names both sentences.

## Open note

- Not tested: a truly undecided private root (one the hub cannot look at, so `place.undecided` is true). The private-folder test covers the ordering, not this branch.
