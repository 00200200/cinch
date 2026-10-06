"""Tests for standalone HTML documentation catalog generator."""

from __future__ import annotations

from pathlib import Path

from cinch.cli import main
from cinch.doc import Doc
from cinch.html import discover_skills, export_html_catalog, generate_html_catalog


def test_generate_html_catalog_contains_embedded_assets_and_cards():
    doc1 = Doc(
        kind="skill",
        name="test-skill",
        description="A helpful test skill for automated testing.",
        body="## Instructions\nDo test things deterministically.",
        paths=("src/**/*.py",),
        extra_meta={"tags": ["python", "testing"]},
    )
    doc2 = Doc(
        kind="skill",
        name="ml-optimizer",
        description="Optimize machine learning training loops.",
        body="## ML\nSet seed for reproducibility.",
        extra_meta={"tags": ["ml", "python"]},
    )

    html_out = generate_html_catalog([doc1, doc2], project_name="My Project Catalog")

    # Document validity and metadata
    assert "<!DOCTYPE html>" in html_out
    assert "<title>My Project Catalog</title>" in html_out

    # Embedded CSS & Dark mode theme variables
    assert ":root {" in html_out
    assert '[data-theme="dark"]' in html_out
    assert "theme-toggle" in html_out

    # Search & Tag controls
    assert 'id="search"' in html_out
    assert 'data-tag="python"' in html_out
    assert 'data-tag="ml"' in html_out

    # Action buttons
    assert "btn-copy-prompt" in html_out
    assert "btn-copy-claude" in html_out
    assert "btn-copy-cursor" in html_out

    # Zero CDN / external network requests
    assert "http://" not in html_out
    assert "https://" not in html_out

    # Size constraint: strictly under 500 KB
    assert len(html_out.encode("utf-8")) < 500 * 1024


def test_discover_skills_and_export_html_catalog(tmp_path: Path):
    skill_dir = tmp_path / "skills" / "deploy"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: deploy\ndescription: Deploy app to cloud\ntags: [web, ops]\n---\nPrompt body\n",
        encoding="utf-8",
    )

    skills = discover_skills(project_root=tmp_path, include_starter=False)
    assert len(skills) == 1
    assert skills[0].name == "deploy"

    out_file = tmp_path / "docs" / "skills.html"
    result = export_html_catalog(
        project_root=tmp_path,
        output_path=out_file,
        include_starter=False,
        title="Custom Title",
    )

    assert out_file.is_file()
    assert out_file.read_text(encoding="utf-8") == result
    assert "Custom Title" in result
    assert "deploy" in result


def test_cli_export_command(tmp_path: Path, capsys):
    skill_dir = tmp_path / ".skills" / "linter"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: linter\ndescription: Lint codebase\n---\nRun ruff.\n",
        encoding="utf-8",
    )

    out_path = tmp_path / "catalog.html"
    code = main(["export", str(tmp_path), "--format", "html", "-o", str(out_path), "--no-starter"])
    assert code == 0
    assert out_path.is_file()
    content = out_path.read_text(encoding="utf-8")
    assert "linter" in content
    assert "btn-copy-prompt" in content

    # Test stdout export
    capsys.readouterr()
    code_stdout = main(["export", str(tmp_path), "--format", "html", "--no-starter"])
    assert code_stdout == 0
    captured = capsys.readouterr().out
    assert "<!DOCTYPE html>" in captured
    assert "linter" in captured
