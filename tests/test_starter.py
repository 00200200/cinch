from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cinch.cli import main
from cinch.doc import parse_doc
from cinch.inventory import STARTER_DIR, Item, collect_inventory


class TestStarterSkills:
    def test_starter_dir_exists_and_has_four_skills(self) -> None:
        assert STARTER_DIR.is_dir()
        skill_files = sorted(STARTER_DIR.glob("*/SKILL.md"))
        assert len(skill_files) == 4
        names = [f.parent.name for f in skill_files]
        assert names == ["git-commit", "humanizer", "security-auditor", "test-writer"]

        # Check each skill can be parsed as a valid Doc
        for sf in skill_files:
            item = Item("skill", sf.parent.name, sf.parent, frozenset())
            doc = parse_doc(item)
            assert doc.name == sf.parent.name
            assert doc.description
            assert len(doc.body) > 0

    def test_collect_inventory_discovers_all_starter_skills(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        project = tmp_path / "project"
        home.mkdir()
        project.mkdir()

        # Without include_starter, inventory is empty
        items_without = collect_inventory(
            harness="claude",
            home=home,
            project=project,
            include_starter=False,
        )
        assert len(items_without) == 0

        # With include_starter, all 4 are discovered
        items_with = collect_inventory(
            harness="claude",
            home=home,
            project=project,
            include_starter=True,
        )
        assert len(items_with) == 4
        starter_names = [i.name for i in items_with]
        assert starter_names == ["git-commit", "humanizer", "security-auditor", "test-writer"]
        assert all(i.kind == "skill" for i in items_with)

    def test_init_with_starter_flag_wires_skills_to_disk(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / "home"
        project = tmp_path / "project"
        home.mkdir()
        project.mkdir()

        code = main(
            [
                "init",
                str(project),
                "--starter",
                "--harness",
                "cursor,copilot",
                "--yes",
                "--home",
                str(home),
            ]
        )
        assert code == 0

        # Verify cursor skills written to .agents/skills/
        cursor_skills = project / ".agents" / "skills"
        assert (cursor_skills / "humanizer" / "SKILL.md").is_file()
        assert (cursor_skills / "security-auditor" / "SKILL.md").is_file()
        assert (cursor_skills / "test-writer" / "SKILL.md").is_file()
        assert (cursor_skills / "git-commit" / "SKILL.md").is_file()

        # Verify copilot instructions written to .github/instructions/
        copilot_dir = project / ".github" / "instructions"
        assert (copilot_dir / "humanizer.instructions.md").is_file()
        assert (copilot_dir / "security-auditor.instructions.md").is_file()
        assert (copilot_dir / "test-writer.instructions.md").is_file()
        assert (copilot_dir / "git-commit.instructions.md").is_file()

        # Verify .cinch.json exists and lists all 4 copied skills
        manifest_file = project / ".cinch.json"
        assert manifest_file.is_file()
        import json

        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert set(manifest["copied"]) == {
            "skill:humanizer",
            "skill:security-auditor",
            "skill:test-writer",
            "skill:git-commit",
        }
        assert set(manifest["targets"]) == {"cursor", "copilot"}

    def test_inventory_lists_starter_skills(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / "home"
        home.mkdir()

        code = main(["inventory", "--harness", "claude", "--starter", "--home", str(home)])
        assert code == 0
        out = capsys.readouterr().out.splitlines()
        assert out[0] == "cinch  Claude Code"
        assert out[1] == "kind      name"
        assert "skill     git-commit" in out
        assert "skill     humanizer" in out
        assert "skill     security-auditor" in out
        assert "skill     test-writer" in out

    def test_interactive_empty_inventory_prompts_starter_skills(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        project = tmp_path / "project"
        home.mkdir()
        project.mkdir()

        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        mock_ask = MagicMock(return_value=["humanizer", "git-commit"])
        mock_checkbox = MagicMock(return_value=MagicMock(ask=mock_ask))

        with patch("questionary.checkbox", mock_checkbox):
            code = main(
                [
                    "init",
                    str(project),
                    "--harness",
                    "cursor",
                    "--home",
                    str(home),
                ]
            )
            assert code == 0

        # Verify prompt was called with the right question and choices
        mock_checkbox.assert_called_once_with(
            "No local skills found. Wire curated starter skills?",
            choices=["humanizer", "security-auditor", "test-writer", "git-commit"],
        )

        # Verify selected skills were wired
        cursor_skills = project / ".agents" / "skills"
        assert (cursor_skills / "humanizer" / "SKILL.md").is_file()
        assert (cursor_skills / "git-commit" / "SKILL.md").is_file()
        assert not (cursor_skills / "security-auditor" / "SKILL.md").exists()
        assert not (cursor_skills / "test-writer" / "SKILL.md").exists()

    def test_interactive_empty_inventory_cancelled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        project = tmp_path / "project"
        home.mkdir()
        project.mkdir()

        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        mock_ask = MagicMock(return_value=None)
        mock_checkbox = MagicMock(return_value=MagicMock(ask=mock_ask))

        with patch("questionary.checkbox", mock_checkbox):
            code = main(
                [
                    "init",
                    str(project),
                    "--harness",
                    "cursor",
                    "--home",
                    str(home),
                ]
            )
            assert code == 2

    def test_interactive_empty_inventory_none_selected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        project = tmp_path / "project"
        home.mkdir()
        project.mkdir()

        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        mock_ask = MagicMock(return_value=[])
        mock_checkbox = MagicMock(return_value=MagicMock(ask=mock_ask))

        with patch("questionary.checkbox", mock_checkbox):
            code = main(
                [
                    "init",
                    str(project),
                    "--harness",
                    "cursor",
                    "--home",
                    str(home),
                ]
            )
            assert code == 0

        cursor_skills = project / ".agents" / "skills"
        assert not cursor_skills.exists()

    def test_init_starter_with_specific_skill_filter(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        project = tmp_path / "project"
        home.mkdir()
        project.mkdir()

        code = main(
            [
                "init",
                str(project),
                "--starter",
                "--skills",
                "humanizer",
                "--harness",
                "cursor",
                "--yes",
                "--home",
                str(home),
            ]
        )
        assert code == 0
        cursor_skills = project / ".agents" / "skills"
        assert (cursor_skills / "humanizer" / "SKILL.md").is_file()
        assert not (cursor_skills / "security-auditor" / "SKILL.md").exists()
