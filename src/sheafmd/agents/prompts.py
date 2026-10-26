"""
sheafmd.agents.prompts — what the hub says to a session: the Ask prompt, the Tell message and the
Cancel message (SPEC 11.2, 11.3).

The wording is part of the interface: an agent acts on it. `links` is whether the root keeps
the link rule (`links = false` in `.sheaf.toml` leaves it out). Comment text reaches the agent
as content with its author, never filtered (9.8).
"""
from ..links import RULE


def _thread(c) -> str:
    return "\n".join([f"{c.by} ({c.at}): {c.body}"]
                     + [f"{c.display(r)} ({r.at}): {r.text}" for r in c.replies])


def ask(abs_path: str, c, links: bool = True) -> str:
    rule = f"{RULE} " if links else ""
    return (f'A comment was left on the document {abs_path}, at line {c.line}, on the passage '
            f'"{c.quote}". The thread so far:\n\n{_thread(c)}\n\n'
            "Answer the last message in the thread, the way you would answer it here in the "
            "conversation: short, in the language it was written in, and only from what you "
            f"know or can read. Do not edit any file. {rule}Your answer is written into the "
            "document as your reply, as it is, so give only the answer: no preamble, no "
            "sign-off.")


def tell(address: str, abs_path: str, me: str, c, links: bool = True) -> str:
    rule = f"{RULE}\n\n" if links else ""
    return (f"Tell from sheaf, on the page of {address} ({abs_path}).\n"
            f'{me} pressed Tell on comment {c.id} by {c.by}, at line {c.line}, on the passage '
            f'"{c.quote}": act on it here, in this conversation.\n\n'
            f"Thread:\n{_thread(c)}\n\n"
            f"{rule}"
            "When you are done, answer in the thread so the page shows it, with the role "
            "action:\n"
            f'- with the sheaf MCP tool: reply(doc="{address}", id="{c.id}", '
            'text="<what you did>", role="action")\n'
            f'- or in a shell: sheaf reply {abs_path} {c.id} "<what you did>" --role action')


def cancel(address: str, me: str, cid: str) -> str:
    return (f"Tell from sheaf, on the page of {address}: {me} pressed Cancel on comment {cid}. "
            "Stop working on it, undo nothing on your own, and do not reply in the thread. If "
            "you already changed something for it, say what in this conversation.")
