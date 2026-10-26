---
name: sheaf
description: Show a markdown document to the person as a page in their browser and work through the comments they leave on it. Use when the person wants to read, review or edit a .md document on a page, when a document has open comments to answer, or when a message that starts "Tell from sheaf" arrives.
---
<!-- written by sheaf init; sheaf may replace it -->

# sheaf

sheaf turns a markdown file into a working page for the person: they read it, edit it and leave
comments on passages. The `.md` stays the source; whatever they do on the page lands back in it.
You work on the same file, and you see their comments in it.

## Show a document

`sheaf <file>` (for example `sheaf plan.md`) starts the hub if none runs, opens the page in the
person's browser and prints its URL. Give them that URL in your reply. Do it for what they will
read or review: plans, reports, comparisons, specifications, handoff notes. If they would have to
read it twice in the terminal, render it once.

Do not render text meant for pasting somewhere else (an email, a post, a commit message, a
prompt, a config file). A page gets in the way of the paste: put it in the conversation.

`sheaf <file> --share` writes a copy with no comments and no script, one HTML file to send on.

## Before you revise a document, read its comments

    sheaf comments plan.md            # the open comments: id, author, line, the passage, the thread
    sheaf comments plan.md --all      # the resolved ones too

If the sheaf tools are connected to you (`documents`, `threads`, `reply`, `resolve`), they do the
same. A comment sits in the `.md` right after the passage it is about. Edit the text around it
freely; never write, change or delete a comment by hand, because the commands keep the format the
page reads.

## After you handle a comment, reply and resolve it

    sheaf reply plan.md c3 "Moved the date to March and said why." --resolve

Reply in the thread, and resolve it when it is done. Never delete a comment: the person reads the
answers comment by comment. Add a comment of your own on a passage with
`sheaf comment plan.md "the exact passage" "your note"`.

## A message that starts "Tell from sheaf"

The person pressed Tell on a comment: act on it in this conversation, then answer in the thread
with the role `action`, so the page shows that you did it:

    sheaf reply plan.md c3 "What you did." --role action

With the tools: `reply(doc=..., id=..., text=..., role="action")`. A reply with no role is an
answer (use it when you only answer a question and change nothing). If you cannot do what the
comment asks, say so in the thread.

## Links

Every page, article, tool or document you name, in text you write into the document or in a reply, is a markdown link [words](https://full-url) to its URL, checked with curl that it answers. Link only what the text names, and never a generic page (a home page, a search page) where a specific one is meant.

## When something goes wrong

Record what only you can see, for the person who looks after sheaf: `sheaf diag note "what went
wrong, and what you were doing"`. It goes to the diagnostics log on their machine, nowhere else.

`sheaf signin-url` prints a URL that signs a browser in and holds the hub's key. Never run it
yourself: the key would be in your transcript. If the person needs one, ask the person to run it
in their own terminal. Never paste such a URL into a conversation or a file.
