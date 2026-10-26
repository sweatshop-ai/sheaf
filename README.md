# sheaf

A working page for a markdown document, shared between a person and their agent.
The `.md` stays the source; everything done on the page lands back in it.

You read the document in your browser, edit it in place, and comment on passages. Press **Ask** on a
comment and a copy of the agent session that wrote the document answers in the thread; press
**Tell** and the running session acts on it and replies. Every edit and every comment is written
into the `.md`, so the agent reads the same file you do, and `git diff` shows what happened.

Three things set it apart:

- **A save made against an older file is merged, not refused.** If the agent changed the file
  while you were editing, your save is lined up with it paragraph by paragraph. Only the same
  paragraph changed on both sides is a conflict, and even then nothing is lost.
- **A share copy with the comments taken out.** `sheaf plan.md --share` writes one self-contained
  HTML file (and, with `--pdf`, a PDF) that you can send to someone outside the conversation.
- **Ask and Tell from the page, at any time.** The agent does not have to be waiting.

## Install

    uv tool install sheafmd

`pipx install sheafmd` works too. It needs Python 3.11 or later; pandoc comes with it. The command
is `sheaf`.

## Quick start

    sheaf plan.md

This starts the hub if none runs, opens the page in your browser and prints its address. Select
text on the page and press **Comment**; edit a paragraph and it is saved to `plan.md`. The hub
serves every document you open from one local address, `http://127.0.0.1:27419`, and its index
page lists them.

The commands that work on the file alone need no hub:

    sheaf comments plan.md                       # the open comments, with their threads
    sheaf reply plan.md c3 "Done." --resolve     # answer a comment and resolve it
    sheaf plan.md --share                        # plan-share.html, no comments, no script

`sheaf --help` lists every command.

## Agents

    sheaf init claude      # or codex, gemini, cursor

`init` registers sheaf's MCP door with that agent, using the agent's own command (`claude mcp add`,
`codex mcp add`, `gemini mcp add`; for Cursor it adds an entry to `~/.cursor/mcp.json`). The agent
can then list the documents with open comments, read a thread, reply and resolve. For Claude Code
it also installs a skill in `~/.claude/skills/sheaf`. `init` never replaces what it did not write:
a server called `sheaf` that is set up differently, a skill file of your own, or a file it cannot
read is left as it is, and it says why and what to do.

Ask and Tell from the page work with Claude Code. The other agents reach sheaf through the MCP
door; adapters for them come later.

For an agent that has no skills, or a project that wants the instruction in the repository, put
this in the project's `AGENTS.md` (sheaf never writes that file):

```
This project keeps documents in markdown and uses sheaf: `sheaf FILE.md` opens a page for the person and prints its URL, which you give them. Do not render text meant for pasting somewhere else (an email, a post, a commit message, a prompt, a config file): put it in the conversation.
Before you revise a document, read its comments with `sheaf comments FILE.md`.
After you handle a comment, reply with `sheaf reply FILE.md ID "what you did" --resolve`; never delete a comment. A message that starts "Tell from sheaf" is a comment to act on: do it, then reply with `--role action`.
Record what goes wrong with `sheaf diag note "what went wrong"`. Never run `sheaf signin-url` yourself: it prints the hub's key; ask the person to run it.
Every page, article, tool or document you name is a markdown link to its URL, checked with curl that it answers.
```

An agent that reaches the hub over HTTP instead gets a named token: `sheaf token add NAME`
prints it once. A token can read and answer comments. A token made with
`sheaf token add NAME --write` can also read a page's text, make a page and change its text; it
keeps every comment in the text, and a change made against an older text is refused.

## Platforms

- **Linux** is tested: CI runs the whole test suite on every pull request and every merge to main, on x86-64, with Python
  3.13, and with Python 3.11, 3.13 and 3.14 every night. On aarch64 sheaf was tried once, by hand, with Python 3.14: the failures it
  showed were fixed, and the whole suite has not been run there again.
- **macOS** is not tested yet. The code has launchd and `~/Library` paths; nobody has run sheaf on a
  Mac of their own.
- **Windows** is not supported: use WSL2 (untested). Natively, only `--share`, `comments`,
  `comment`, `reply`, `resolve`, `reopen` and `version` run.

## Keep the hub running

The hub starts by itself the first time a command needs it. To keep it running across logins and
reboots, install it as a user service (never done for you):

    sheaf service install      # systemd on Linux, launchd on macOS
    sheaf service uninstall

With the service installed, `sheaf start` and `sheaf restart` go through it. If the hub crashes the
service starts it again after a growing delay (2 s, up to 60 s on systemd 254 and later) and gives
up after five starts in five minutes. `sheaf diag` lists every `hub-start`, `hub-exit` and
`unclean-exit`. Linux is the tested platform. CI installs the service for real on a Linux runner
and checks that it restarts the hub after a `kill -9` and after an upgrade. The launchd job is
checked only by tests that pretend to be a Mac: nobody has run it on a Mac of their own yet.

After you upgrade sheaf, the next `sheaf` command restarts an idle hub on the new version and open
pages reload by themselves. If an Ask or Tell is running, it says so and leaves the hub alone: run
`sheaf restart` when it is done. A page with edits you have not saved, or a comment half written,
is never reloaded; it tells you instead.

## A hub on a remote box

The hub listens on `127.0.0.1` only. To use one on a box you reach over ssh:

1. On the box, install sheaf and run `sheaf service install`. A user service stops when its owner
   logs out unless the admin runs `loginctl enable-linger <you>` once.
2. On your machine forward the hub's port to the same port number:
   `ssh -L 27419:127.0.0.1:27419 box`. VS Code Remote-SSH forwards it for you. In an ssh session
   with no display, `sheaf open` prints this command, with your port, user and address, above the
   URL and starts no browser on the box.
3. On the box run `sheaf signin-url` and open what it prints in your own browser. That URL holds the
   hub key: open it yourself, never paste it to an agent.

Two people on one box each set their own port in `~/.config/sheaf/config.toml` (`port = 27420`) and
forward their own. The sign-in cookie is named after the hub's port, so a local hub and a
forwarded one on the same port number would overwrite each other's.

## Signing in again

`sheaf rotate` replaces the hub key. Every browser is signed out at once: an open page shows the
sign-in page (or, with unsaved edits on it, keeps them and says how to sign in again). Sign in
again with `sheaf open FILE.md`, or with `sheaf signin-url` for a browser on another machine. MCP
tokens are not affected.

## Security

The trust line is your operating-system user: any process running as you is trusted. sheaf defends
against other websites in your browser, other users on the machine, and hostile content in a
document you render. The hub listens on loopback only, checks the `Host` and `Origin` of every
request, and talks only to a browser that holds its key; the key is never in a page, and another
local user without it gets nothing but the hub's name and version. The sign-in link that
`sheaf open` hands your browser works once, and on Linux only for a browser of your own user: another
user who reads it from the process list is refused (macOS cannot check that). Raw HTML in a document is
sanitised and every page carries a content security policy, also for a page an agent wrote. An
agent's token reaches the door's tools and nothing else: it cannot use the page's routes, run Ask
or Tell, or add a folder, and it reads, makes and changes pages only when it was made with
`--write`. sheaf collects nothing and opens no connection to another machine: its commands, your
browser and the hub talk over `127.0.0.1`, and Ask and Tell go through your own agent.

---

Made by tiroir. A hosted version is coming.

## Licence

MIT. The pandoc binary comes from the separate `pypandoc-binary` wheel (GPL); sheaf itself stays
MIT.
