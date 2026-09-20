"""Tests for cinch check (Skill Linter & Validator)."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from cinch.check import lint_directory, lint_skill
from cinch.cli import main


def _create_skill(
    path: Path,
    content: str,
    *,
    has_scripts: bool = False,
    has_references: bool = False,
) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    skill_file = path / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    if has_scripts:
        (path / "scripts").mkdir(exist_ok=True)
    if has_references:
        (path / "references").mkdir(exist_ok=True)
    return skill_file


def test_valid_skill(tmp_path: Path) -> None:
    """Valid skill returns 0 diagnostics."""
    skill_dir = tmp_path / "my-skill"
    _create_skill(
        skill_dir,
        """\
---
name: my-skill
description: A comprehensive description of the skill
paths:
  - "**/*.py"
---
# My Skill
This is the markdown body of the skill.
""",
    )

    diags_dir = lint_skill(skill_dir)
    assert diags_dir == []

    diags_file = lint_skill(skill_dir / "SKILL.md")
    assert diags_file == []


def test_valid_multi_file_skill(tmp_path: Path) -> None:
    """Multi-file skill returns only I001 info diagnostic."""
    skill_dir = tmp_path / "multi-skill"
    _create_skill(
        skill_dir,
        """\
---
name: multi-skill
description: A valid skill with scripts directory
---
# Body
""",
        has_scripts=True,
    )

    diags = lint_skill(skill_dir)
    assert len(diags) == 1
    assert diags[0].rule == "I001"
    assert diags[0].severity == "info"
    assert "scripts/" in diags[0].message


def test_missing_skill_file(tmp_path: Path) -> None:
    """Missing SKILL.md produces E001 error."""
    empty_dir = tmp_path / "empty-skill"
    empty_dir.mkdir()

    diags = lint_skill(empty_dir)
    assert len(diags) == 1
    assert diags[0].rule == "E001"
    assert diags[0].severity == "error"

    nonexistent_file = tmp_path / "no-such-skill" / "SKILL.md"
    diags_file = lint_skill(nonexistent_file)
    assert len(diags_file) == 1
    assert diags_file[0].rule == "E001"


def test_missing_frontmatter_produces_e002(tmp_path: Path) -> None:
    """Missing frontmatter entirely produces E002 error."""
    skill_dir = tmp_path / "no-fm"
    _create_skill(
        skill_dir,
        """\
# No Frontmatter
Just regular markdown content without yaml headers.
""",
    )

    diags = lint_skill(skill_dir)
    assert len(diags) == 1
    assert diags[0].rule == "E002"
    assert diags[0].severity == "error"


def test_unclosed_frontmatter_produces_e002(tmp_path: Path) -> None:
    """Unclosed frontmatter delimiter produces E002 error."""
    skill_dir = tmp_path / "unclosed-fm"
    _create_skill(
        skill_dir,
        """\
---
name: unclosed-fm
description: Missing closing delimiter
# No closing delimiter here
""",
    )

    diags = lint_skill(skill_dir)
    assert any(d.rule == "E002" and d.severity == "error" for d in diags)


def test_invalid_yaml_syntax_produces_e002(tmp_path: Path) -> None:
    """Invalid YAML syntax (unclosed quotes, malformed keys) produces E002."""
    skill_dir = tmp_path / "bad-yaml"
    _create_skill(
        skill_dir,
        """\
---
name: bad-yaml
description: "unclosed quote
---
# Body
""",
    )

    diags = lint_skill(skill_dir)
    assert any(d.rule == "E002" and d.severity == "error" for d in diags)

    # Test bad list syntax
    bad_list_dir = tmp_path / "bad-list"
    _create_skill(
        bad_list_dir,
        """\
---
name: bad-list
description: Valid description
paths: [unclosed, list
---
# Body
""",
    )
    diags_list = lint_skill(bad_list_dir)
    assert any(d.rule == "E002" and d.severity == "error" for d in diags_list)


def test_missing_name_produces_e003(tmp_path: Path) -> None:
    """Missing name in frontmatter or empty name produces E003."""
    skill_dir = tmp_path / "no-name"
    _create_skill(
        skill_dir,
        """\
---
description: Valid description but missing name
---
# Body
""",
    )

    diags = lint_skill(skill_dir)
    assert any(d.rule == "E003" and d.severity == "error" for d in diags)

    empty_name_dir = tmp_path / "empty-name"
    _create_skill(
        empty_name_dir,
        """\
---
name: ""
description: Valid description but empty name
---
# Body
""",
    )

    diags_empty = lint_skill(empty_name_dir)
    assert any(d.rule == "E003" and d.severity == "error" for d in diags_empty)


def test_uppercase_name_produces_w001(tmp_path: Path) -> None:
    """Non-kebab-case name (uppercase, underscores) produces W001 warning."""
    skill_dir = tmp_path / "camel-case"
    _create_skill(
        skill_dir,
        """\
---
name: MySkill
description: Valid description of the skill
---
# Body
""",
    )

    diags = lint_skill(skill_dir)
    assert any(d.rule == "W001" and d.severity == "warning" for d in diags)

    underscore_dir = tmp_path / "underscore"
    _create_skill(
        underscore_dir,
        """\
---
name: my_skill
description: Valid description of the skill
---
# Body
""",
    )

    diags_under = lint_skill(underscore_dir)
    assert any(d.rule == "W001" and d.severity == "warning" for d in diags_under)


def test_missing_or_short_description_produces_w002(tmp_path: Path) -> None:
    """Missing description or description shorter than 10 characters produces W002."""
    missing_desc_dir = tmp_path / "missing-desc"
    _create_skill(
        missing_desc_dir,
        """\
---
name: my-skill
---
# Body
""",
    )

    diags_missing = lint_skill(missing_desc_dir)
    assert any(d.rule == "W002" and d.severity == "warning" for d in diags_missing)

    short_desc_dir = tmp_path / "short-desc"
    _create_skill(
        short_desc_dir,
        """\
---
name: my-skill
description: Too short
---
# Body
""",
    )

    diags_short = lint_skill(short_desc_dir)
    assert any(d.rule == "W002" and d.severity == "warning" for d in diags_short)


def test_large_body_produces_w003(tmp_path: Path) -> None:
    """Body exceeding 12,000 characters produces W003 warning."""
    large_body = "x" * 12050
    skill_dir = tmp_path / "large-skill"
    _create_skill(
        skill_dir,
        f"""\
---
name: large-skill
description: Valid description of the large skill
---
# Large Body
{large_body}
""",
    )

    diags = lint_skill(skill_dir)
    assert any(d.rule == "W003" and d.severity == "warning" for d in diags)


def test_invalid_glob_pattern_produces_w004(tmp_path: Path) -> None:
    """Backslashes in paths/globs produce W004 warning."""
    skill_dir = tmp_path / "bad-glob"
    _create_skill(
        skill_dir,
        r"""---
name: bad-glob
description: Valid description of the skill
paths:
  - "src\windows\path\*.py"
---
# Body
""",
    )

    diags = lint_skill(skill_dir)
    assert any(d.rule == "W004" and d.severity == "warning" for d in diags)


def test_lint_directory(tmp_path: Path) -> None:
    """lint_directory finds and lints all skills recursively."""
    skills_root = tmp_path / "skills"
    _create_skill(
        skills_root / "skill-a",
        """\
---
name: skill-a
description: Valid description for skill-a
---
# Body A
""",
    )
    _create_skill(
        skills_root / "skill-b",
        """\
---
name: skill-b
description: Too short
---
# Body B
""",
    )

    diags = lint_directory(skills_root)
    assert len(diags) == 1
    assert diags[0].rule == "W002"
    assert "skill-b" in str(diags[0].path)


def test_cli_return_codes(tmp_path: Path) -> None:
    """CLI returns 1 on error, 0 on warning/clean."""
    clean_dir = tmp_path / "clean-skill"
    _create_skill(
        clean_dir,
        """\
---
name: clean-skill
description: A perfectly valid clean skill
---
# Body
""",
    )

    warning_dir = tmp_path / "warning-skill"
    _create_skill(
        warning_dir,
        """\
---
name: WarningSkill
description: Valid description but uppercase name
---
# Body
""",
    )

    error_dir = tmp_path / "error-skill"
    _create_skill(
        error_dir,
        """\
---
description: Missing name in frontmatter
---
# Body
""",
    )

    # Clean skill -> 0
    assert main(["check", str(clean_dir)]) == 0

    # Warning only -> 0
    assert main(["check", str(warning_dir)]) == 0

    # Error -> 1
    assert main(["check", str(error_dir)]) == 1

    # Nonexistent path -> 1
    assert main(["check", str(tmp_path / "nonexistent")]) == 1


def test_cli_pipe_output(tmp_path: Path, capsys) -> None:
    """Non-terminal (pipe) output matches standard GNU-style format."""
    skill_dir = tmp_path / "pipe-skill"
    _create_skill(
        skill_dir,
        """\
---
name: PipeSkill
description: Too short
---
# Body
""",
    )

    fake_console = Console(force_terminal=False)
    with patch("cinch.cli.console", fake_console):
        code = main(["check", str(skill_dir)])
        assert code == 0

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 2
    # Verify standard GNU style: path:line: [SEVERITY] rule: message
    assert any("[WARNING] W001:" in line for line in lines)
    assert any("[WARNING] W002:" in line for line in lines)
    assert any(str(skill_dir / "SKILL.md") in line for line in lines)


def test_rich_terminal_output_mocked(tmp_path: Path) -> None:
    """Rich terminal output renders table and summary panel when mocked."""
    # Test clean skill
    clean_dir = tmp_path / "clean-skill"
    _create_skill(
        clean_dir,
        """\
---
name: clean-skill
description: Perfectly valid skill for testing
---
# Clean
""",
    )

    buf = io.StringIO()
    clean_console = Console(file=buf, force_terminal=True, width=120)
    with patch("cinch.cli.console", clean_console):
        code = main(["check", str(clean_dir)])
        assert code == 0

    clean_out = buf.getvalue()
    assert "✓ All checks passed" in clean_out

    # Test skill with diagnostics (both warnings and errors)
    err_dir = tmp_path / "err-skill"
    _create_skill(
        err_dir,
        """\
---
name: ErrSkill
description: Too short
---
# Body
""",
    )

    buf_err = io.StringIO()
    err_console = Console(file=buf_err, force_terminal=True, width=120)
    with patch("cinch.cli.console", err_console):
        code = main(["check", str(err_dir)])
        assert code == 0  # Only warnings (W001, W002)

    err_out = buf_err.getvalue()
    assert "Severity" in err_out
    assert "Rule" in err_out
    assert "W001" in err_out
    assert "W002" in err_out
    assert "Found 2 diagnostics" in err_out
