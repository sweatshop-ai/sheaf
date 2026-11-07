"""The target of a Tell: a session or an agent, and the person can change it (SPEC 9.8, 10.1, 10.6).

A document's entry in `docs.json` holds, per whose target it is:

    target     the hub person's: a session (as the render recorded it) or an agent {kind, token, id}
    session    the session the document last rendered from, kept beside an agent target
    targets    {member id: {kind: "agent", token, id}}, each member's own, only ever one of their agents

An agent is kept with the token's stable `id`, so a revoked token, or a new one of the same name, is never
the old target. The wire form `agent:<token name>` is resolved to the id here, on the server.

    note_write(hub, address, row, member)   a door write with an agent's token
    pick(hub, address, member, choice)      POST /_/target: the entry after the change; raises Refused
    agent_view(hub, raw, member)            (agent shape, tell line) of a stored agent target
    choices(hub, address, member)           what the person may make the target
    stored(hub, address, member)            the raw target of whose it is, or None
"""
from __future__ import annotations

from ..agents.base import Target
from .state import TokenRow

LATER = "Tell to {agent} is not available yet."
REVOKED = "{agent} can no longer reach this hub: its token was revoked. Pick another target."
WHAT = "The target is session, agent:<token name> or none."


class Refused(Exception):
    """A target the reader may not pick: one sentence, a 400."""


def is_agent(raw) -> bool:
    return isinstance(raw, dict) and raw.get("kind") == "agent"


def _keep(row: TokenRow) -> dict:
    return {"kind": "agent", "token": row.name, "id": row.id}


def agents(hub, member=None) -> list[TokenRow]:
    """The agent tokens a reader may Tell: every one for the hub person, their own for a member."""
    rows = [r for r in hub.tokens.list() if r.client is not None and not r.invalid]
    return rows if member is None else [r for r in rows if r.name in member.tokens]


def live(hub, raw, member=None) -> TokenRow | None:
    """The token a stored agent target names, or None when it was revoked (a new token of its name has another
    id) or, for a member, is no longer one of theirs."""
    if not is_agent(raw):
        return None
    return next((r for r in agents(hub, member) if r.name == raw.get("token") and r.id == raw.get("id")), None)


def stored(hub, address: str, member=None) -> dict | None:
    """The raw target of the hub person or of `member`; None for none. A member's is theirs only while the
    token is still one of theirs (9.8)."""
    entry = hub.docs.get(address)
    if member is None:
        raw = entry.get("target")
        return raw if isinstance(raw, dict) and raw else None
    raw = (entry.get("targets") or {}).get(member.id) if isinstance(entry.get("targets"), dict) else None
    if is_agent(raw) and raw.get("token") in member.tokens:
        return raw
    return None


def _session_of(entry: dict) -> dict | None:
    """The session the document last rendered from, while there is one: the target itself or the one kept beside
    an agent target."""
    for raw in (entry.get("target"), entry.get("session")):
        if isinstance(raw, dict) and raw and not is_agent(raw):
            return raw
    return None


def agent_view(hub, raw: dict, member=None) -> tuple[dict, str | None, bool]:
    """(the agent shape of 10.1, the line under Tell, whether the token still reaches the hub) of a stored agent
    target. A revoked token has no signature to build: its shape names the token."""
    row = live(hub, raw, member)
    name = row.signed(hub.person, hub.proxy) if row is not None else str(raw.get("token", ""))
    shape = {"kind": "agent", "token": raw.get("token"), "display": name, "label": name}
    return shape, (LATER if row is not None else REVOKED).format(agent=name), row is not None


def choices(hub, address: str, member=None) -> list[dict]:
    """What the reader may make the target (`targets` of 10.1): the session while there is one, for the hub
    person, then the agents they may Tell."""
    out = []
    if member is None:
        session = _session_of(hub.docs.get(address))
        if session is not None:
            try:
                t = Target.from_dict(session)
            except ValueError:
                t = None
            if t is not None:
                from .tell import who
                ad = hub.adapter(t.agent)
                out.append({"target": "session", "label": f"{who(t, ad)} · {ad.product}"})
    for row in agents(hub, member):
        out.append({"target": f"agent:{row.name}", "label": row.signed(hub.person, hub.proxy)})
    return out


def note_write(hub, address: str, row: TokenRow | None, member=None) -> None:
    """A door write (reply, resolve, create, update) made with `row`: an agent's token makes that agent the
    target, the member's when the token acts for one. A token that is no agent's makes none. The session the
    hub person's target was stays beside it."""
    if row is None or row.client is None:
        return

    def settle(entry: dict) -> dict:
        _set(entry, _keep(row), member)
        return entry
    hub.docs.change(address, settle)


def _set(entry: dict, agent: dict | None, member) -> None:
    if member is not None:
        targets = dict(entry["targets"]) if isinstance(entry.get("targets"), dict) else {}
        if agent is None:
            targets.pop(member.id, None)
        else:
            targets[member.id] = agent
        if targets:
            entry["targets"] = targets
        else:
            entry.pop("targets", None)
        return
    old = entry.get("target")
    if agent is None and not old:
        return
    if isinstance(old, dict) and old and not is_agent(old):
        entry["session"] = old                      # kept beside the agent, so the person can take it back
    entry["target"] = agent


def pick(hub, address: str, member, choice) -> None:
    """Change the target to `choice`: "session", "agent:<token name>" or "none" (9.8). Raises Refused for a
    target the reader may not pick."""
    if not isinstance(choice, str):
        raise Refused(WHAT)
    if choice == "none":
        def settle(entry):
            _set(entry, None, member)
            return entry
    elif choice == "session":
        if member is not None:
            raise Refused("Tell reaches only your own agents here.")

        def settle(entry):
            session = _session_of(entry)
            if session is None:
                raise Refused("No session rendered this page, so there is none to take back.")
            entry["target"] = session
            entry.pop("session", None)
            return entry
    elif choice.startswith("agent:") and len(choice) > 6:
        name = choice[6:]
        row = next((r for r in agents(hub, member) if r.name == name), None)
        if row is None:
            raise Refused(f"{name} is not one of your agents.")

        def settle(entry):
            _set(entry, _keep(row), member)
            return entry
    else:
        raise Refused(WHAT)
    hub.docs.change(address, settle)
