"""Tests for cross-harness translation, dialect adapters, pointer rules, and multi-target wiring."""

from __future__ import annotations

import json
from pathlib import Path

from cinch.adapters import get_adapter
from cinch.doc import Doc, parse_doc
from cinch.inventory import Item
from cinch.plan import resolve_plan
from cinch.wire import apply_plan


def _write_file(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestCrossHarnessAdapters:
    def test_claude_to_cursor_and_codex(self) -> None:
        doc = Doc(
            kind="skill",
            name="humanizer",
            description="Humanize AI prose.",
            body="Follow Hemingway rules.\n",
            paths=("*.md", "docs/**"),
        )
        adapter = get_adapter("cursor")
        rendered = adapter.render(doc)
        assert len(rendered) == 1
        rf = rendered[0]
        assert rf.relpath == ".agents/skills/humanizer/SKILL.md"
        assert 'name: "humanizer"' in rf.text
        assert 'description: "Humanize AI prose."' in rf.text
        assert "*.md" in rf.text
        assert "Follow Hemingway rules." in rf.text

    def test_claude_to_copilot_instructions(self) -> None:
        doc = Doc(
            kind="skill",
            name="reviewer",
            description="Code review instructions.",
            body="Check for security and simplicity.\n",
            paths=(),
        )
        adapter = get_adapter("copilot")
        rendered = adapter.render(doc)
        assert len(rendered) == 1
        rf = rendered[0]
        assert rf.relpath == ".github/instructions/reviewer.instructions.md"
        assert 'applyTo:\n  - "**"' in rf.text
        assert 'description: "Code review instructions."' in rf.text
        assert "Check for security and simplicity." in rf.text

    def test_claude_to_gemini_toml(self) -> None:
        doc = Doc(
            kind="skill",
            name="ship",
            description="Release helper",
            body="Run checks and tag git version.",
        )
        adapter = get_adapter("gemini")
        rendered = adapter.render(doc)
        assert len(rendered) == 1
        rf = rendered[0]
        assert rf.relpath == ".gemini/commands/ship.toml"
        assert 'description = "Release helper"' in rf.text
        assert 'prompt = """\nRun checks and tag git version.\n"""' in rf.text

    def test_claude_to_windsurf_rules(self) -> None:
        doc = Doc(
            kind="skill",
            name="tester",
            description="Testing guidelines",
            body="Write fast unit tests.",
            paths=("tests/**",),
        )
        adapter = get_adapter("windsurf")
        rendered = adapter.render(doc)
        assert len(rendered) == 1
        rf = rendered[0]
        assert rf.relpath == ".devin/rules/tester.md"
        assert 'trigger: "manual"' in rf.text
        assert 'description: "Testing guidelines"' in rf.text
        assert 'globs:\n  - "tests/**"' in rf.text

    def test_claude_to_aider_merge(self) -> None:
        doc = Doc(
            kind="skill",
            name="lint",
            description="Lint standards",
            body="Always run ruff check.",
        )
        adapter = get_adapter("aider")
        rendered = adapter.render(doc)
        assert len(rendered) == 2
        md_file = next(r for r in rendered if r.relpath.endswith(".md"))
        merge_file = next(r for r in rendered if r.relpath == ".aider.conf.yml")
        assert md_file.relpath == ".aider/lint.md"
        assert "Always run ruff check." in md_file.text
        assert merge_file.mode == "merge"
        assert 'read:\n  - ".aider/lint.md"' in merge_file.text


class TestMultiTargetWiring:
    def test_wire_claude_skill_to_cursor_copilot_gemini(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        skill_dir = home / ".claude" / "skills" / "humanizer"
        _write_file(
            skill_dir / "SKILL.md",
            "---\nname: humanizer\ndescription: Polish writing.\n---\nMake it concise.\n",
        )
        project = tmp_path / "app"
        project.mkdir()

        plan = resolve_plan(
            from_harness="claude",
            harness="cursor,copilot,gemini",
            project=project,
            home=home,
            skills=("humanizer",),
        )
        assert plan.targets == ("cursor", "copilot", "gemini")
        result = apply_plan(plan)
        assert len(result["results"]) == 3

        # Check Cursor output
        cursor_file = project / ".agents/skills/humanizer/SKILL.md"
        assert cursor_file.is_file()
        assert "Make it concise." in cursor_file.read_text(encoding="utf-8")

        # Check Copilot output
        copilot_file = project / ".github/instructions/humanizer.instructions.md"
        assert copilot_file.is_file()
        assert "applyTo" in copilot_file.read_text(encoding="utf-8")

        # Check Gemini output
        gemini_file = project / ".gemini/commands/humanizer.toml"
        assert gemini_file.is_file()
        assert "description = " in gemini_file.read_text(encoding="utf-8")

        # Manifest
        manifest = json.loads((project / ".cinch.json").read_text(encoding="utf-8"))
        assert manifest["source_harness"] == "claude"
        assert manifest["targets"] == ["cursor", "copilot", "gemini"]
        assert len(manifest["results"]) == 3
        for r in manifest["results"]:
            assert r["outcome"] == "written"

    def test_cursor_and_codex_share_agents_path(self, tmp_path: Path) -> None:
        """Cursor and Codex both write `.agents/skills/`; the second is shared."""
        home = tmp_path / "home"
        skill_dir = home / ".claude" / "skills" / "humanizer"
        _write_file(
            skill_dir / "SKILL.md",
            "---\nname: humanizer\ndescription: Polish writing.\n---\nMake it concise.\n",
        )
        project = tmp_path / "app"
        project.mkdir()

        plan = resolve_plan(
            from_harness="claude",
            harness="claude,cursor,codex",
            project=project,
            home=home,
            skills=("humanizer",),
        )
        result = apply_plan(plan)

        by_target = {r["target"]: r for r in result["results"]}
        assert by_target["claude"]["outcome"] == "written"
        assert by_target["claude"]["path"] == ".claude/skills/humanizer/SKILL.md"
        assert by_target["cursor"]["outcome"] == "written"
        assert by_target["cursor"]["path"] == ".agents/skills/humanizer/SKILL.md"
        assert by_target["codex"]["outcome"] == "shared"
        assert by_target["codex"]["path"] == ".agents/skills/humanizer/SKILL.md"
        assert by_target["codex"]["shared_with"] == "cursor"
        assert "skill:humanizer" in result["copied"]

        assert (project / ".claude/skills/humanizer/SKILL.md").is_file()
        assert (project / ".agents/skills/humanizer/SKILL.md").is_file()

        # Re-run: both Cursor and Codex paths already on disk → exists, not shared.
        result2 = apply_plan(plan)
        by_target2 = {r["target"]: r for r in result2["results"]}
        assert by_target2["claude"]["outcome"] == "exists"
        assert by_target2["cursor"]["outcome"] == "exists"
        assert by_target2["codex"]["outcome"] == "exists"
        assert result2["copied"] == []


class TestPointerAndSupportFiles:
    def test_skill_with_support_scripts(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        skill_dir = home / ".claude" / "skills" / "pentest"
        _write_file(
            skill_dir / "SKILL.md",
            "---\nname: pentest\ndescription: Pentest app\n---\nRun audit.\n",
        )
        _write_file(skill_dir / "scripts" / "probe.sh", "#!/bin/sh\necho probe\n")

        item = Item(kind="skill", name="pentest", source=skill_dir, tags=frozenset())
        doc = parse_doc(item)
        assert doc.support == skill_dir

        project = tmp_path / "app"
        project.mkdir()

        plan = resolve_plan(
            from_harness="claude",
            harness="copilot",
            project=project,
            home=home,
            skills=("pentest",),
        )
        apply_plan(plan)

        # Main copilot instruction
        assert (project / ".github/instructions/pentest.instructions.md").is_file()
        # Copied support directory
        assert (project / ".cinch/skills/pentest/scripts/probe.sh").is_file()

    def test_large_skill_exceeding_windsurf_limit(self) -> None:
        huge_body = "x" * 13000
        doc = Doc(
            kind="skill",
            name="huge-rule",
            description="Very large rule",
            body=huge_body,
        )
        adapter = get_adapter("windsurf")
        rendered = adapter.render(doc)
        assert len(rendered) == 2
        rule_file = next(r for r in rendered if r.relpath.startswith(".devin/rules/"))
        full_file = next(r for r in rendered if r.relpath.startswith(".cinch/skills/"))
        assert "Full documentation and support files located at" in rule_file.text
        assert len(full_file.text) >= 13000


class TestAiderConfigMerge:
    def test_aider_config_merge_append_and_idempotency(self, tmp_path: Path) -> None:
        project = tmp_path / "app"
        project.mkdir()
        conf_file = project / ".aider.conf.yml"
        conf_file.write_text('read:\n  - "README.md"\n', encoding="utf-8")

        home = tmp_path / "home"
        skill_dir = home / ".claude" / "skills" / "reviewer"
        _write_file(skill_dir / "SKILL.md", "Review rules.\n")

        plan = resolve_plan(
            from_harness="claude",
            harness="aider",
            project=project,
            home=home,
            skills=("reviewer",),
        )
        res1 = apply_plan(plan)
        merge_res1 = next(r for r in res1["results"] if r["path"] == ".aider.conf.yml")
        assert merge_res1["outcome"] == "written"
        content1 = conf_file.read_text(encoding="utf-8")
        assert '- "README.md"' in content1
        assert '- ".aider/reviewer.md"' in content1

        # Second run should report unchanged
        res2 = apply_plan(plan)
        merge_res2 = next(r for r in res2["results"] if r["path"] == ".aider.conf.yml")
        assert merge_res2["outcome"] == "unchanged"


class TestHookSkippedAcrossHarnesses:
    def test_hook_skipped_when_target_differs(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        _write_file(home / ".claude" / "hooks" / "pre-commit.sh", "#!/bin/sh\n")
        project = tmp_path / "app"
        project.mkdir()

        plan = resolve_plan(
            from_harness="claude",
            harness="cursor",
            project=project,
            home=home,
            hooks=("pre-commit.sh",),
        )
        assert len(plan.files) == 0
        assert len(plan.skipped) == 1
        assert plan.skipped[0].kind == "hook"
        assert "Hooks cannot be translated" in plan.skipped[0].reason
