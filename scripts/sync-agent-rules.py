"""Regenerate the portable core-rules document without starting emLek or a model."""

from pathlib import Path

from emlek.mcp_server.rules import document

if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "docs/AGENT_RULES.md"
    target.write_text(document(), encoding="utf-8", newline="\n")
    print("updated docs/AGENT_RULES.md")
