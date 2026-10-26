"""The two texts an agent is given (SPEC 14.5): the skill `sheaf init claude` installs, and the
five lines of the AGENTS.md snippet the README shows.

Both are public and neutral: they name no person, no company and no client, and every command in
them is one this build has. The link rule is the sentence the page hands an agent in a Tell, said
once in the code and quoted here, not written twice."""
import re
from importlib import resources
from pathlib import Path

import pytest

from helpers import BRAND_WORDS
from sheafmd import agent_setup, links
from sheafmd.cli import COMMANDS

FILES = resources.files("sheafmd") / "agent_files"
SKILL = (FILES / "claude-skill.md").read_text(encoding="utf-8")
SNIPPET = (FILES / "agents-snippet.md").read_text(encoding="utf-8")
README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")


def front_matter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "front matter must open the file: Claude Code reads it only there"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines())


# ── the skill ────────────────────────────────────────────────────────────────

def test_the_skill_opens_with_front_matter_that_names_it_and_says_when_to_use_it():
    fm = front_matter(SKILL)
    assert fm["name"] == "sheaf"
    assert len(fm["description"]) > 60 and len(fm["description"]) < 600


def test_the_skill_carries_the_line_that_lets_init_replace_it_and_init_sees_it():
    assert agent_setup.MARKER in SKILL.splitlines()
    assert agent_setup.written_by_init(SKILL)


def test_the_skill_tells_what_the_spec_says_it_tells():
    text = SKILL.lower()
    for need in ("sheaf <file>", "threads", "reply", "resolve", "never delete", "role",
                 "action", "sheaf diag note", "paste"):
        assert need in text, need
    assert links.RULE in SKILL, "the link rule, in the words the page hands an agent"


def test_every_sheaf_command_the_skill_shows_is_a_command_of_this_build():
    shown = set(re.findall(r"(?:`|^    )sheaf ([a-z][a-z-]*)(?![\w.])", SKILL, re.M))
    assert {"comments", "reply", "diag"} <= shown
    for word in shown:
        assert word in COMMANDS, f"the skill shows `sheaf {word}`, which is not a command"


def test_the_reply_flags_the_skill_shows_exist(capsys):
    from sheafmd.cli import main
    assert main(["reply", "--help"]) == 0
    help_text = capsys.readouterr().out
    shown = re.findall(r"^    sheaf reply .*$|`sheaf reply [^`]*`", SKILL, re.M) + re.findall(r"`(--[a-z-]+)`", SKILL)
    flags = {f for line in shown for f in re.findall(r"--[a-z-]+", line)}
    assert {"--resolve", "--role"} <= flags
    for f in flags:
        assert f in help_text, f


@pytest.mark.parametrize("text", [SKILL, SNIPPET], ids=["skill", "snippet"])
def test_the_texts_name_no_brand_person_company_or_client(text):
    low = text.lower()
    assert [w for w in BRAND_WORDS if w in low] == []
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), "no address"
    assert "/home/" not in text and "/Users/" not in text


def test_the_skill_never_asks_an_agent_to_show_the_key():
    assert "signin-url" in SKILL and "never" in SKILL.lower()


def test_the_skill_tells_the_agent_not_to_run_signin_url_itself_and_to_ask_the_person_to():
    # The command prints the hub's key in a URL: run by the agent, the key is in its transcript.
    text = " ".join(SKILL.split())
    assert "Never run it yourself" in text and "ask the person to run it" in text


# ── the snippet ──────────────────────────────────────────────────────────────

def test_the_snippet_is_five_lines_and_says_the_same_things_in_brief():
    lines = [ln for ln in SNIPPET.splitlines() if ln.strip()]
    assert len(lines) == 5
    low = SNIPPET.lower()
    for need in ("sheaf", "comments", "reply", "resolve", "never delete", "link"):
        assert need in low, need


def test_the_snippet_says_what_the_skill_says_about_diag_note_pasting_and_the_key():
    text = " ".join(SNIPPET.split())
    assert "`sheaf diag note" in text, "record what goes wrong"
    assert re.search(r"do not render text meant for pasting", text, re.I), "when not to render"
    assert "Never run `sheaf signin-url`" in text, "and never run the command that prints the hub's key"


def test_every_sheaf_command_the_snippet_shows_is_a_command_of_this_build():
    shown = set(re.findall(r"`sheaf ([a-z][a-z-]*)(?![\w.])", SNIPPET))
    assert {"comments", "reply", "diag", "signin-url"} <= shown
    for word in shown:
        assert word in COMMANDS, f"the snippet shows `sheaf {word}`, which is not a command"


def test_the_readme_shows_the_snippet_as_it_is_in_the_package():
    assert SNIPPET.strip() in README, "the README quotes agent_files/agents-snippet.md word for word"
    assert "AGENTS.md" in README


def test_sheaf_never_writes_an_agents_md():
    source = (Path(agent_setup.__file__)).read_text(encoding="utf-8")
    assert "AGENTS.md" not in source
