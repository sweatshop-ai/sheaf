This project keeps documents in markdown and uses sheaf: `sheaf FILE.md` opens a page for the person and prints its URL, which you give them. Do not render text meant for pasting somewhere else (an email, a post, a commit message, a prompt, a config file): put it in the conversation.
Before you revise a document, read its comments with `sheaf comments FILE.md`.
After you handle a comment, reply with `sheaf reply FILE.md ID "what you did" --resolve`; never delete a comment. A message that starts "Tell from sheaf" is a comment to act on: do it, then reply with `--role action`.
Record what goes wrong with `sheaf diag note "what went wrong"`. Never run `sheaf signin-url` yourself: it prints the hub's key; ask the person to run it.
Every page, article, tool or document you name is a markdown link to its URL, checked with curl that it answers.
