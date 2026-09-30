"""Tests for `cinch import` legacy decompile into canonical Cinch skills."""

from __future__ import annotations

from pathlib import Path

import pytest

from cinch.adapters import get_adapter, render_cinch_skill
from cinch.cli import main
from cinch.doc import Doc, parse_frontmatter
from cinch.importer import (
    collect_import_items,
    detect_dialects,
    resolve_dialect,
    run_import,
    slugify,
)
from cinch.plan import CinchError


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestDetectDialect:
    def test_cursorrules_file(self, tmp_path: Path) -> None:
        path = _write(tmp_path / ".cursorrules", "# Project rules\nBe concise.\n")
        assert detect_dialects(path) == ["cursor"]
        assert resolve_dialect(path, None) == "cursor"

    def test_cursor_rules_dir(self, tmp_path: Path) -> None:
        rules = tmp_path / ".cursor" / "rules"
        rules.mkdir(parents=True)
        assert detect_dialects(rules) == ["cursor"]

    def test_claude_skill_dir(self, tmp_path: Path) -> None:
        skill = tmp_path / "humanizer"
        _write(
            skill / "SKILL.md",
            '---\nname: "humanizer"\ndescription: "Humanize prose"\n---\n\nBe direct.\n',
        )
        assert detect_dialects(skill) == ["claude"]

    def test_copilot_instructions(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path / ".github" / "copilot-instructions.md",
            '---\napplyTo: "**"\n---\n\nUse TypeScript.\n',
        )
        assert detect_dialects(path) == ["copilot"]

    def test_clinerules_file(self, tmp_path: Path) -> None:
        path = _write(tmp_path / ".clinerules", "# Always run tests\n")
        assert detect_dialects(path) == ["cline"]

    def test_ambiguous_project_requires_flag(self, tmp_path: Path) -> None:
        _write(tmp_path / ".cursorrules", "cursor rules\n")
        _write(tmp_path / ".clinerules", "cline rules\n")
        found = detect_dialects(tmp_path)
        assert set(found) == {"cursor", "cline"}
        with pytest.raises(CinchError, match="Ambiguous"):
            resolve_dialect(tmp_path, None)
        assert resolve_dialect(tmp_path, "cursor") == "cursor"

    def test_unknown_path_requires_flag(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "notes.txt", "hello\n")
        with pytest.raises(CinchError, match="Could not detect"):
            resolve_dialect(path, None)


class TestImportDialects:
    def test_import_cursorrules(self, tmp_path: Path) -> None:
        src = _write(
            tmp_path / "src" / ".cursorrules",
            '---\nglobs:\n  - "**/*.py"\n---\n\n# Python Style\n\nUse ruff.\n',
        )
        out = tmp_path / "out"
        result = run_import(src, out=out, overwrite=True)
        assert result.dialect == "cursor"
        skill = out / "cursorrules" / "SKILL.md"
        assert skill.is_file()
        text = skill.read_text(encoding="utf-8")
        assert 'name: "cursorrules"' in text
        assert "Python Style" in text
        assert "**/*.py" in text
        assert "Use ruff." in text

    def test_import_cursor_mdc_rules(self, tmp_path: Path) -> None:
        rules = tmp_path / ".cursor" / "rules"
        _write(
            rules / "react.mdc",
            '---\ndescription: "React conventions"\nglobs: "**/*.tsx"\n---\n\nUse hooks.\n',
        )
        out = tmp_path / "imported"
        result = run_import(rules, out=out, overwrite=True)
        assert "react/SKILL.md" in result.written
        meta, body = parse_frontmatter((out / "react" / "SKILL.md").read_text(encoding="utf-8"))
        assert meta["name"] == "react"
        assert meta["description"] == "React conventions"
        assert meta["paths"] == ["**/*.tsx"] or "**/*.tsx" in str(meta.get("paths"))
        assert "Use hooks." in body

    def test_import_claude_skill_keeps_known_meta(self, tmp_path: Path) -> None:
        skill = tmp_path / "deploy"
        _write(
            skill / "SKILL.md",
            "---\n"
            'name: "deploy"\n'
            'description: "Ship containers safely"\n'
            'paths:\n  - "Dockerfile"\n'
            'unknown-vendor-key: "drop-me"\n'
            "---\n\n"
            "Run verify.sh before push.\n",
        )
        _write(skill / "scripts" / "verify.sh", "#!/bin/sh\necho ok\n")
        out = tmp_path / ".cinch" / "imported"
        result = run_import(skill, out=out, overwrite=True)
        assert result.dialect == "claude"
        text = (out / "deploy" / "SKILL.md").read_text(encoding="utf-8")
        assert 'name: "deploy"' in text
        assert "Ship containers safely" in text
        assert "unknown-vendor-key" not in text
        assert "Run verify.sh before push." in text
        assert (out / "deploy" / "scripts" / "verify.sh").is_file()

    def test_import_copilot_instructions(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _write(
            root / ".github" / "copilot-instructions.md",
            (
                '---\napplyTo: "**/*.ts"\n'
                'description: "Repo-wide Copilot guidance"\n'
                "---\n\nPrefer named exports.\n"
            ),
        )
        _write(
            root / ".github" / "instructions" / "python.instructions.md",
            '---\napplyTo:\n  - "**/*.py"\n---\n\n# Python Copilot\n\nUse type hints.\n',
        )
        out = tmp_path / "out"
        result = run_import(root, out=out, dialect="copilot", overwrite=True)
        assert result.dialect == "copilot"
        assert (out / "copilot-instructions" / "SKILL.md").is_file()
        assert (out / "python" / "SKILL.md").is_file()
        py = (out / "python" / "SKILL.md").read_text(encoding="utf-8")
        assert "Use type hints." in py
        assert "**/*.py" in py

    def test_import_clinerules_dir(self, tmp_path: Path) -> None:
        rules = tmp_path / ".clinerules"
        _write(
            rules / "testing.md",
            (
                '---\npaths:\n  - "tests/**"\n---\n\n'
                "# testing\n> Prefer pytest\n\nWrite focused unit tests.\n"
            ),
        )
        out = tmp_path / "out"
        result = run_import(rules, out=out, overwrite=True)
        assert result.dialect == "cline"
        text = (out / "testing" / "SKILL.md").read_text(encoding="utf-8")
        assert 'name: "testing"' in text
        assert "Prefer pytest" in text
        assert "Write focused unit tests." in text
        assert "tests/**" in text

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        src = _write(tmp_path / ".clinerules", "# Safety\nNo secrets in logs.\n")
        out = tmp_path / "out"
        result = run_import(src, out=out, dry_run=True)
        assert result.dry_run is True
        assert result.written
        assert not out.exists() or not any(out.rglob("SKILL.md"))

    def test_skip_existing_without_yes(self, tmp_path: Path) -> None:
        src = _write(tmp_path / ".cursorrules", "# One\nBody A\n")
        out = tmp_path / "out"
        run_import(src, out=out, overwrite=True)
        _write(tmp_path / ".cursorrules", "# Two\nBody B\n")
        result = run_import(tmp_path / ".cursorrules", out=out, overwrite=False)
        assert any("exists" in s for s in result.skipped)
        text = (out / "cursorrules" / "SKILL.md").read_text(encoding="utf-8")
        assert "Body A" in text
        assert "Body B" not in text


class TestRoundTrip:
    def test_cline_export_import_round_trip(self, tmp_path: Path) -> None:
        original = Doc(
            kind="skill",
            name="humanizer",
            description="Humanize AI prose.",
            body="Cut filler openers.\nPrefer active voice.",
            paths=("*.md", "docs/**"),
        )
        rendered = get_adapter("cline").render(original)
        assert len(rendered) >= 1
        legacy = tmp_path / ".clinerules" / "humanizer.md"
        _write(legacy, rendered[0].text)

        items = collect_import_items(legacy, "cline")
        assert len(items) == 1
        imported = items[0].doc
        assert imported.name == original.name
        assert imported.description == original.description
        assert "Cut filler openers." in imported.body
        assert set(imported.paths) == set(original.paths)

        # Canonical render stays stable
        again = render_cinch_skill(imported)
        meta, body = parse_frontmatter(again)
        assert meta["name"] == "humanizer"
        assert "Cut filler openers." in body

    def test_claude_skill_round_trip(self, tmp_path: Path) -> None:
        original = Doc(
            kind="skill",
            name="ship",
            description="Release helper skill",
            body="Tag the release after CI is green.",
            paths=("CHANGELOG.md",),
        )
        rendered = get_adapter("claude").render(original)
        skill_dir = tmp_path / "ship"
        _write(skill_dir / "SKILL.md", rendered[0].text)
        items = collect_import_items(skill_dir, "claude")
        imported = items[0].doc
        assert imported.name == original.name
        assert imported.description == original.description
        assert imported.body.strip() == original.body.strip()
        assert set(imported.paths) == set(original.paths)


class TestCliImport:
    def test_cli_import_dry_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path / ".cursorrules", "# CLI Rules\nKeep diffs small.\n")
        code = main(["import", str(src), "--dry-run"])
        assert code == 0
        assert not (tmp_path / ".cinch" / "imported").exists()

    def test_cli_import_writes_default_out(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        src = _write(
            tmp_path / "rules.md",
            '---\ndescription: "Loose file"\n---\n\nHello from rules.\n',
        )
        code = main(["import", str(src), "--from", "cursor", "--yes"])
        assert code == 0
        skill = tmp_path / ".cinch" / "imported" / "rules" / "SKILL.md"
        assert skill.is_file()
        assert "Hello from rules." in skill.read_text(encoding="utf-8")

    def test_cli_import_ambiguous_fails(self, tmp_path: Path) -> None:
        _write(tmp_path / ".cursorrules", "a\n")
        _write(tmp_path / ".clinerules", "b\n")
        code = main(["import", str(tmp_path)])
        assert code == 2


class TestSlugify:
    def test_slugify_basic(self) -> None:
        assert slugify("Hello_World") == "hello-world"
        assert slugify("***") == "imported-skill"
