"""The marketplace entry at the repository root points at the plugin, so `claude plugin install sheaf@sheaf` finds it."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_marketplace_lists_the_plugin_at_a_directory_that_holds_its_manifest():
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    entry = next(p for p in market["plugins"] if p["name"] == "sheaf")
    assert entry["source"].startswith("./")
    manifest = json.loads((ROOT / entry["source"] / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == entry["name"]
    assert (ROOT / entry["source"] / "hooks" / "hooks.json").is_file()
