"""Skill validation and linting for cinch."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Severity = Literal["error", "warning", "info"]

KEBAB_CASE_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    ".ruff_cache",
    ".pytest_cache",
    "node_modules",
    "__pycache__",
}


@dataclass(frozen=True)
class Diagnostic:
    path: Path
    line: int | None
    severity: Severity
    rule: str
    message: str


def _unquote(val: str) -> str:
    val = val.strip()
    if len(val) >= 2:
        is_quoted = (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        )
        if is_quoted:
            return val[1:-1]
    return val


def _parse_frontmatter(
    content: str, skill_file: Path
) -> tuple[dict[str, Any], dict[str, int], list[Diagnostic], str, int]:
    """Parse YAML frontmatter and return (meta, field_lines, errors, body, body_start_line)."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return (
            {},
            {},
            [
                Diagnostic(
                    path=skill_file,
                    line=1,
                    severity="error",
                    rule="E002",
                    message="Missing YAML frontmatter (file must start with '---')",
                )
            ],
            content,
            1,
        )

    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx == -1:
        return (
            {},
            {},
            [
                Diagnostic(
                    path=skill_file,
                    line=1,
                    severity="error",
                    rule="E002",
                    message="Unclosed YAML frontmatter (missing closing '---')",
                )
            ],
            content,
            1,
        )

    fm_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1 :])
    body_start_line = end_idx + 2

    meta: dict[str, Any] = {}
    field_lines: dict[str, int] = {}
    errors: list[Diagnostic] = []

    current_key: str | None = None
    current_mode: str | None = None  # "list" or "multiline_str"
    multiline_lines: list[str] = []

    for idx, raw_line in enumerate(fm_lines):
        line_no = idx + 2  # 1-based, line 1 was opening '---'

        if "\t" in raw_line:
            errors.append(
                Diagnostic(
                    path=skill_file,
                    line=line_no,
                    severity="error",
                    rule="E002",
                    message="Invalid YAML frontmatter syntax: tabs are not allowed for indentation",
                )
            )
            continue

        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Multiline string continuation: indented and not a list item or new key
        if current_mode == "multiline_str" and (
            raw_line.startswith(" ") or raw_line.startswith("  ")
        ):
            if not stripped.startswith("- "):
                multiline_lines.append(stripped)
                continue

        # Flush previous multiline string if we hit something else
        if current_mode == "multiline_str" and current_key:
            meta[current_key] = " ".join(multiline_lines)
            current_mode = None
            multiline_lines = []

        # List item
        if stripped.startswith("-"):
            if stripped == "-" or stripped.startswith("- "):
                if current_key is None:
                    errors.append(
                        Diagnostic(
                            path=skill_file,
                            line=line_no,
                            severity="error",
                            rule="E002",
                            message="Invalid YAML frontmatter syntax: unexpected list item at root",
                        )
                    )
                    continue

                item_val = stripped[1:].strip()
                if (item_val.startswith('"') and not item_val.endswith('"')) or (
                    item_val.startswith("'") and not item_val.endswith("'")
                ):
                    errors.append(
                        Diagnostic(
                            path=skill_file,
                            line=line_no,
                            severity="error",
                            rule="E002",
                            message=(
                                f"Invalid YAML frontmatter syntax: "
                                f"unclosed quote in list item '{stripped}'"
                            ),
                        )
                    )
                    continue

                unquoted = _unquote(item_val)
                if current_key not in meta or not isinstance(meta[current_key], list):
                    meta[current_key] = []
                meta[current_key].append(unquoted)
                current_mode = "list"
                continue
            else:
                errors.append(
                    Diagnostic(
                        path=skill_file,
                        line=line_no,
                        severity="error",
                        rule="E002",
                        message=(
                            f"Invalid YAML frontmatter syntax: "
                            f"missing space after '-' in '{stripped}'"
                        ),
                    )
                )
                continue

        # Check for key: value
        if ":" not in stripped:
            errors.append(
                Diagnostic(
                    path=skill_file,
                    line=line_no,
                    severity="error",
                    rule="E002",
                    message=(
                        f"Invalid YAML frontmatter syntax: expected 'key: value', got '{stripped}'"
                    ),
                )
            )
            continue

        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()

        if not key:
            errors.append(
                Diagnostic(
                    path=skill_file,
                    line=line_no,
                    severity="error",
                    rule="E002",
                    message="Invalid YAML frontmatter syntax: missing key before ':'",
                )
            )
            continue

        field_lines[key] = line_no
        current_key = key

        if not val:
            current_mode = None
            meta[key] = ""
        elif val in (">", "|", ">-", "|-"):
            current_mode = "multiline_str"
            multiline_lines = []
        elif val.startswith("["):
            if not val.endswith("]"):
                errors.append(
                    Diagnostic(
                        path=skill_file,
                        line=line_no,
                        severity="error",
                        rule="E002",
                        message=(
                            f"Invalid YAML frontmatter syntax: unclosed bracket in list '{val}'"
                        ),
                    )
                )
                continue
            inner = val[1:-1].strip()
            if not inner:
                meta[key] = []
            else:
                items: list[str] = []
                has_quote_err = False
                for p in inner.split(","):
                    p = p.strip()
                    if not p:
                        continue
                    if (p.startswith('"') and not p.endswith('"')) or (
                        p.startswith("'") and not p.endswith("'")
                    ):
                        errors.append(
                            Diagnostic(
                                path=skill_file,
                                line=line_no,
                                severity="error",
                                rule="E002",
                                message=(
                                    f"Invalid YAML frontmatter syntax: "
                                    f"unclosed quote in list item '{p}'"
                                ),
                            )
                        )
                        has_quote_err = True
                        break
                    items.append(_unquote(p))
                if not has_quote_err:
                    meta[key] = items
            current_mode = None
        elif (val.startswith('"') and not val.endswith('"')) or (
            val.startswith("'") and not val.endswith("'")
        ):
            errors.append(
                Diagnostic(
                    path=skill_file,
                    line=line_no,
                    severity="error",
                    rule="E002",
                    message=f"Invalid YAML frontmatter syntax: unclosed quote in '{val}'",
                )
            )
            continue
        else:
            meta[key] = _unquote(val)
            current_mode = None

    if current_mode == "multiline_str" and current_key:
        meta[current_key] = " ".join(multiline_lines)

    return meta, field_lines, errors, body, body_start_line


def lint_skill(skill_dir_or_file: Path) -> list[Diagnostic]:
    """Validate and lint a single SKILL.md file or skill directory against rules."""
    path = Path(skill_dir_or_file)
    if path.is_dir():
        skill_file = path / "SKILL.md"
        skill_dir = path
    else:
        skill_file = path
        skill_dir = path.parent

    # E001: SKILL.md does not exist in skill directory, or file cannot be read
    if not skill_file.is_file():
        return [
            Diagnostic(
                path=skill_file,
                line=None,
                severity="error",
                rule="E001",
                message=f"SKILL.md does not exist at {skill_file}",
            )
        ]

    try:
        content = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [
            Diagnostic(
                path=skill_file,
                line=None,
                severity="error",
                rule="E001",
                message=f"Cannot read SKILL.md at {skill_file}: {exc}",
            )
        ]

    # E002: Invalid YAML frontmatter syntax
    meta, field_lines, fm_errors, body, body_start_line = _parse_frontmatter(content, skill_file)
    if fm_errors:
        return fm_errors

    diagnostics: list[Diagnostic] = []

    # E003: Missing name in frontmatter or empty name
    name = meta.get("name")
    if name is None or (isinstance(name, str) and not name.strip()):
        diagnostics.append(
            Diagnostic(
                path=skill_file,
                line=field_lines.get("name", 1),
                severity="error",
                rule="E003",
                message="Missing 'name' in frontmatter or empty name",
            )
        )
    elif isinstance(name, str):
        # W001: Name is not valid kebab-case (^[a-z0-9]+(-[a-z0-9]+)*$)
        if not KEBAB_CASE_PATTERN.match(name):
            diagnostics.append(
                Diagnostic(
                    path=skill_file,
                    line=field_lines.get("name", 1),
                    severity="warning",
                    rule="W001",
                    message=(
                        f"Skill name '{name}' is not valid kebab-case "
                        "(expected ^[a-z0-9]+(-[a-z0-9]+)*$)"
                    ),
                )
            )

    # W002: Missing description or description shorter than 10 characters
    desc = meta.get("description")
    if desc is None or not isinstance(desc, str) or len(desc.strip()) < 10:
        diagnostics.append(
            Diagnostic(
                path=skill_file,
                line=field_lines.get("description", 1),
                severity="warning",
                rule="W002",
                message=(
                    "Missing 'description' in frontmatter or description shorter than 10 characters"
                ),
            )
        )

    # W003: Skill body exceeds 12,000 characters (will require pointer file in Windsurf)
    if len(body) > 12000:
        diagnostics.append(
            Diagnostic(
                path=skill_file,
                line=body_start_line,
                severity="warning",
                rule="W003",
                message=(
                    "Skill body exceeds 12,000 characters (will require pointer file in Windsurf)"
                ),
            )
        )

    # W004: Invalid path glob pattern in paths / globs (fails fnmatch or contains backslashes)
    for key in ("paths", "globs"):
        if key in meta:
            val = meta[key]
            line_no = field_lines.get(key, 1)
            patterns: list[str] = []
            if isinstance(val, str):
                patterns.append(val)
            elif isinstance(val, (list, tuple)):
                for item in val:
                    if isinstance(item, str):
                        patterns.append(item)
                    else:
                        diagnostics.append(
                            Diagnostic(
                                path=skill_file,
                                line=line_no,
                                severity="warning",
                                rule="W004",
                                message=(
                                    f"Invalid glob pattern in '{key}': "
                                    f"expected string, got {type(item).__name__}"
                                ),
                            )
                        )
            for pattern in patterns:
                if "\\" in pattern:
                    diagnostics.append(
                        Diagnostic(
                            path=skill_file,
                            line=line_no,
                            severity="warning",
                            rule="W004",
                            message=(
                                f"Invalid path glob pattern '{pattern}': "
                                "contains backslashes (use forward slashes)"
                            ),
                        )
                    )
                else:
                    try:
                        regex = fnmatch.translate(pattern)
                        re.compile(regex)
                    except Exception as exc:
                        diagnostics.append(
                            Diagnostic(
                                path=skill_file,
                                line=line_no,
                                severity="warning",
                                rule="W004",
                                message=f"Invalid path glob pattern '{pattern}': {exc}",
                            )
                        )

    # I001: Multi-file skill detected (has scripts/ or references/ directory)
    if (skill_dir / "scripts").is_dir() or (skill_dir / "references").is_dir():
        diagnostics.append(
            Diagnostic(
                path=skill_file,
                line=None,
                severity="info",
                rule="I001",
                message="Multi-file skill detected (has scripts/ or references/ directory)",
            )
        )

    return diagnostics


def lint_directory(root: Path) -> list[Diagnostic]:
    """Recursively or via glob find all SKILL.md files under root and lint them."""
    root = Path(root)
    if not root.exists():
        return [
            Diagnostic(
                path=root / "SKILL.md",
                line=None,
                severity="error",
                rule="E001",
                message=f"Path does not exist: {root}",
            )
        ]
    if root.is_file():
        return lint_skill(root)

    skill_files: list[Path] = []
    for skill_file in sorted(root.rglob("SKILL.md")):
        try:
            rel = skill_file.relative_to(root)
        except ValueError:
            rel = skill_file
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        skill_files.append(skill_file)

    if not skill_files:
        return [
            Diagnostic(
                path=root / "SKILL.md",
                line=None,
                severity="error",
                rule="E001",
                message=f"SKILL.md does not exist in skill directory {root}",
            )
        ]

    diagnostics: list[Diagnostic] = []
    for sf in skill_files:
        diagnostics.extend(lint_skill(sf))
    return diagnostics
