"""
sheafmd.agents.prompts — what the hub says to a session: the Tell message and the Cancel message (SPEC 11.3).

The wording is part of the interface: an agent acts on it. `links` is whether the root keeps
the link rule (`links = false` in `.sheaf.toml` leaves it out). Comment text reaches the agent
as content with its author, never filtered (9.8).
"""
from ..links import RULE

ASK_RETIRED_HEAD = "Ask was retired"  # the one place the retired-Ask line is worded (SPEC 11.2)


def _thread(c) -> str:
    return "\n".join([f"{c.by} ({c.at}): {c.body}"]
                     + [f"{c.display(r)} ({r.at}): {r.text}" for r in c.replies])


def _reply_action(address: str, cid: str) -> str:
    return f'reply(doc="{address}", id="{cid}", text="<what you did>", role="action")'


def tell_agent(address: str, by: str, c, links: bool = True) -> str:
    """A Tell that waited for an agent (9.8): the agent reads it from `documents`, where it has no shell, and
    answers through the door."""
    rule = f"{RULE}\n\n" if links else ""
    return (f"Tell from sheaf, on the page of {address}.\n"
            f'{by} pressed Tell on comment {c.id} by {c.by}, at line {c.line}, on the passage '
            f'"{c.quote}": act on it here, in this conversation.\n\n'
            f"Thread:\n{_thread(c)}\n\n"
            f"{rule}"
            "When you are done, answer in the thread so the page shows it, with the role action, "
            f"with the sheaf MCP tool: {_reply_action(address, c.id)}")


def tell(address: str, abs_path: str, me: str, c, links: bool = True) -> str:
    rule = f"{RULE}\n\n" if links else ""
    return (f"Tell from sheaf, on the page of {address} ({abs_path}).\n"
            f'{me} pressed Tell on comment {c.id} by {c.by}, at line {c.line}, on the passage '
            f'"{c.quote}": act on it here, in this conversation.\n\n'
            f"Thread:\n{_thread(c)}\n\n"
            f"{rule}"
            "When you are done, answer in the thread so the page shows it, with the role "
            "action:\n"
            f"- with the sheaf MCP tool: {_reply_action(address, c.id)}\n"
            f'- or in a shell: sheaf reply {abs_path} {c.id} "<what you did>" --role action')


def dropped(drop: dict) -> str | None:
    """The text of a drop of `tell_dir` (9.12) that carries no `message` of its own: the comment's body, its
    sheaf and thread, and how to answer through the door. None when the drop lacks one of them."""
    keys = ("member", "sheaf", "text", "thread")
    if drop.get("kind") != "tell" or not all(isinstance(drop.get(k), str) and drop[k].strip()
                                                for k in keys):
        return None
    # The names are written into the `reply(...)` the session is told to call, and on lines of their own: a
    # quote would end an argument there, a line break start an instruction of the drop's.
    if any(c in drop[k] for k in ("member", "sheaf", "thread") for c in '"\r\n'):
        return None
    me, doc, text, cid = (drop[k] for k in keys)
    return (f"Tell from sheaf, on the page of {doc}.\n"
            f"{me} pressed Tell on comment {cid}: act on it here, in this conversation.\n\n"
            f"The comment:\n{text}\n\n"
            "When you are done, answer in the thread so the page shows it, with the role action:\n"
            f"- with the sheaf MCP tool: {_reply_action(doc, cid)}")


def cancel(address: str, me: str, cid: str) -> str:
    return (f"Tell from sheaf, on the page of {address}: {me} pressed Cancel on comment {cid}. "
            "Stop working on it, undo nothing on your own, and do not reply in the thread. If "
            "you already changed something for it, say what in this conversation.")
