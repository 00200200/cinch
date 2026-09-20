"""Tests for Rich terminal output formatting and direct --from-dir skill discovery."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from cinch.cli import main
from cinch.inventory import collect_inventory


def test_inventory_direct_skills_dir(tmp_path: Path) -> None:
    """--from-dir pointing directly to a directory of skills (like examples/skills)."""
    skills_dir = tmp_path / "skills"
    skill_a = skills_dir / "my-skill"
    skill_a.mkdir(parents=True)
    (skill_a / "SKILL.md").write_text("---\nname: my-skill\n---\n# Body\n")

    items = collect_inventory(
        harness="claude",
        home=tmp_path / "empty_home",
        project=tmp_path / "empty_proj",
        extra_roots=(skills_dir,),
    )
    names = [it.name for it in items if it.kind == "skill"]
    assert "my-skill" in names


def test_rich_harnesses_output(tmp_path: Path) -> None:
    """Rich output renders table without crashing when is_terminal is True."""
    with patch("cinch.cli.console", Console(force_terminal=True)):
        code = main(["harnesses", "--home", str(tmp_path)])
        assert code == 0


def test_rich_inventory_output(tmp_path: Path) -> None:
    """Rich output renders inventory table when is_terminal is True."""
    home = tmp_path / "home"
    skill_dir = home / ".claude" / "skills" / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: test-skill\n---\n# Test\n")

    with patch("cinch.cli.console", Console(force_terminal=True)):
        code = main(["inventory", "--harness", "claude", "--home", str(home)])
        assert code == 0


def test_rich_inventory_empty_output(tmp_path: Path) -> None:
    """Rich output renders empty inventory panel when no items exist."""
    home = tmp_path / "home"
    home.mkdir()

    with patch("cinch.cli.console", Console(force_terminal=True)):
        code = main(["inventory", "--harness", "claude", "--home", str(home)])
        assert code == 0


def test_rich_init_output(tmp_path: Path) -> None:
    """Rich output renders init panel when is_terminal is True."""
    home = tmp_path / "home"
    skill_dir = home / ".claude" / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo-skill\n---\n# Demo\n")

    project = tmp_path / "project"
    project.mkdir()

    with patch("cinch.cli.console", Console(force_terminal=True)):
        code = main(
            [
                "init",
                str(project),
                "--from-harness",
                "claude",
                "--harness",
                "cursor,copilot",
                "--skills",
                "demo-skill",
                "--yes",
                "--home",
                str(home),
            ]
        )
        assert code == 0

    assert (project / ".agents" / "skills" / "demo-skill" / "SKILL.md").exists()
    assert (project / ".github" / "instructions" / "demo-skill.instructions.md").exists()


def test_rich_status_synced_and_missing(tmp_path: Path) -> None:
    """Rich status output renders table with synced and missing indicators."""
    project = tmp_path / "project"
    project.mkdir()

    # Create a manifest
    file_a = project / "a.md"
    file_a.write_text("hello")
    manifest = {
        "harness": "cursor",
        "source_harness": "claude",
        "targets": ["cursor"],
        "results": [
            {
                "kind": "skill",
                "name": "a",
                "target": "cursor",
                "path": "a.md",
                "outcome": "written",
            },
            {
                "kind": "skill",
                "name": "b",
                "target": "cursor",
                "path": "b.md",
                "outcome": "written",
            },
        ],
    }
    (project / ".cinch.json").write_text(json.dumps(manifest))

    with patch("cinch.cli.console", Console(force_terminal=True)):
        code = main(["status", str(project)])
        assert code == 0

    # Also test completely synced
    (project / "b.md").write_text("world")
    with patch("cinch.cli.console", Console(force_terminal=True)):
        code = main(["status", str(project)])
        assert code == 0


def test_rich_preview_output(tmp_path: Path) -> None:
    """Rich preview renders syntax-highlighted panel when is_terminal is True."""
    home = tmp_path / "home"
    skill_dir = home / ".claude" / "skills" / "preview-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: preview-skill\ndescription: Test\n---\n# Content\n"
    )

    with patch("cinch.cli.console", Console(force_terminal=True)):
        code = main(
            [
                "preview",
                "preview-skill",
                "--target",
                "gemini",
                "--from-harness",
                "claude",
                "--home",
                str(home),
            ]
        )
        assert code == 0
