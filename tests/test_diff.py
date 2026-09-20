"""Tests for cinch diff command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from cinch.cli import main


def write(path: Path, content: str = "ok\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def make_skill(root: Path, name: str, body: str = "Use this skill.\n") -> Path:
    path = root / name / "SKILL.md"
    write(
        path,
        f'---\nname: "{name}"\ndescription: "A {name} skill for testing"\n---\n\n{body}',
    )
    return path.parent


def test_diff_missing_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test cinch diff returns 1 when .cinch.json is missing."""
    project = tmp_path / "project"
    project.mkdir()

    code = main(["diff", str(project)])
    assert code == 1

    out = capsys.readouterr().out
    assert "No .cinch.json manifest found" in out
    assert "Run 'cinch init' to wire skills" in out


def test_diff_synced(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test cinch diff returns 0 when files are synced."""
    home = tmp_path / "home"
    make_skill(home / ".claude" / "skills", "code-reviewer")
    project = tmp_path / "project"
    project.mkdir()

    # Wire the skill into the project
    init_code = main(
        [
            "init",
            str(project),
            "--from-harness",
            "claude",
            "--harness",
            "cursor",
            "--skills",
            "code-reviewer",
            "--yes",
            "--home",
            str(home),
        ]
    )
    assert init_code == 0
    capsys.readouterr()

    # Run diff on synced project
    diff_code = main(["diff", str(project), "--home", str(home)])
    assert diff_code == 0

    out = capsys.readouterr().out
    assert "No drift detected. Project is up to date." in out


def test_diff_modified_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test cinch diff returns 1 and shows diff when a wired file is modified on disk."""
    home = tmp_path / "home"
    make_skill(home / ".claude" / "skills", "code-reviewer")
    project = tmp_path / "project"
    project.mkdir()

    # Wire the skill
    main(
        [
            "init",
            str(project),
            "--from-harness",
            "claude",
            "--harness",
            "cursor",
            "--skills",
            "code-reviewer",
            "--yes",
            "--home",
            str(home),
        ]
    )
    capsys.readouterr()

    # Modify the wired rule on disk
    rule_file = project / ".agents" / "skills" / "code-reviewer" / "SKILL.md"
    assert rule_file.exists()
    rule_file.write_text("Modified locally by developer.\nAdded custom rule.\n")

    # Run diff
    diff_code = main(["diff", str(project), "--home", str(home)])
    assert diff_code == 1

    out = capsys.readouterr().out
    assert "--- a/.agents/skills/code-reviewer/SKILL.md" in out
    assert "+++ b/.agents/skills/code-reviewer/SKILL.md" in out
    assert "+Modified locally by developer." in out


def test_diff_missing_file_on_disk(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test cinch diff returns 1 and notes missing file when deleted on disk."""
    home = tmp_path / "home"
    make_skill(home / ".claude" / "skills", "code-reviewer")
    project = tmp_path / "project"
    project.mkdir()

    # Wire the skill
    main(
        [
            "init",
            str(project),
            "--from-harness",
            "claude",
            "--harness",
            "cursor",
            "--skills",
            "code-reviewer",
            "--yes",
            "--home",
            str(home),
        ]
    )
    capsys.readouterr()

    # Remove the wired file
    rule_file = project / ".agents" / "skills" / "code-reviewer" / "SKILL.md"
    rule_file.unlink()

    # Run diff
    diff_code = main(["diff", str(project), "--home", str(home)])
    assert diff_code == 1

    out = capsys.readouterr().out
    assert ".agents/skills/code-reviewer/SKILL.md: [missing on disk]" in out


def test_diff_rich_output_modified(tmp_path: Path) -> None:
    """Test cinch diff renders properly under Rich terminal when file is modified."""
    home = tmp_path / "home"
    make_skill(home / ".claude" / "skills", "code-reviewer")
    project = tmp_path / "project"
    project.mkdir()

    main(
        [
            "init",
            str(project),
            "--from-harness",
            "claude",
            "--harness",
            "cursor",
            "--skills",
            "code-reviewer",
            "--yes",
            "--home",
            str(home),
        ]
    )

    rule_file = project / ".agents" / "skills" / "code-reviewer" / "SKILL.md"
    rule_file.write_text("Modified locally in terminal test.\n")

    with patch("cinch.cli.console", Console(force_terminal=True)):
        diff_code = main(["diff", str(project), "--home", str(home)])
        assert diff_code == 1


def test_diff_rich_output_synced(tmp_path: Path) -> None:
    """Test cinch diff renders properly under Rich terminal when files are synced."""
    home = tmp_path / "home"
    make_skill(home / ".claude" / "skills", "code-reviewer")
    project = tmp_path / "project"
    project.mkdir()

    main(
        [
            "init",
            str(project),
            "--from-harness",
            "claude",
            "--harness",
            "cursor",
            "--skills",
            "code-reviewer",
            "--yes",
            "--home",
            str(home),
        ]
    )

    with patch("cinch.cli.console", Console(force_terminal=True)):
        diff_code = main(["diff", str(project), "--home", str(home)])
        assert diff_code == 0


def test_diff_multiple_targets(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test cinch diff across multiple target harnesses."""
    home = tmp_path / "home"
    make_skill(home / ".claude" / "skills", "code-reviewer")
    project = tmp_path / "project"
    project.mkdir()

    main(
        [
            "init",
            str(project),
            "--from-harness",
            "claude",
            "--harness",
            "cursor,copilot",
            "--skills",
            "code-reviewer",
            "--yes",
            "--home",
            str(home),
        ]
    )
    capsys.readouterr()

    # Synced across both targets
    assert main(["diff", str(project), "--home", str(home)]) == 0
    capsys.readouterr()

    # Modify only copilot file
    copilot_file = project / ".github" / "instructions" / "code-reviewer.instructions.md"
    assert copilot_file.exists()
    copilot_file.write_text("Modified copilot instructions.\n")

    code = main(["diff", str(project), "--home", str(home)])
    assert code == 1
    out = capsys.readouterr().out
    assert "--- a/.github/instructions/code-reviewer.instructions.md" in out
    assert "+Modified copilot instructions." in out
