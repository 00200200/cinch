"""Strict skill frontmatter schema validation without Pydantic.

Cinch intentionally stays dependency-light (questionary + rich only). This module
implements the SkillManifestSchema contract from the lint roadmap using the
stdlib so we do not pull in Pydantic.
"""

from __future__ import annotations

import difflib
import fnmatch
import re
from dataclasses import dataclass
from typing import Any

# Canonical frontmatter keys accepted across dialects Cinch wires.
REQUIRED_KEYS = frozenset({"name", "description"})
OPTIONAL_META_KEYS = frozenset({"version", "author", "license"})
DIALECT_KEYS = frozenset(
    {
        "paths",
        "globs",
        "applyTo",
        "trigger",
        "disable-model-invocation",
    }
)
# Cinch-native keys consumed at wire/compile time (stripped before dialect output).
CINCH_KEYS = frozenset({"parameters", "requires"})
ALLOWED_KEYS = REQUIRED_KEYS | OPTIONAL_META_KEYS | DIALECT_KEYS | CINCH_KEYS

# Soft upper bound used by Cursor/Windsurf-style rule UIs (chars).
MAX_DESCRIPTION_LENGTH = 1024
MIN_DESCRIPTION_LENGTH = 10

KEBAB_CASE_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass(frozen=True)
class SchemaIssue:
    """A single schema validation finding."""

    field: str | None
    rule: str
    message: str
    hint: str | None = None


def suggest_key(unknown: str, *, cutoff: float = 0.5) -> str | None:
    """Return the closest allowed key for a misspelling, e.g. desc -> description."""
    aliases = {
        "desc": "description",
        "descr": "description",
        "describe": "description",
        "path": "paths",
        "glob": "globs",
        "applyto": "applyTo",
        "apply_to": "applyTo",
        "apply-to": "applyTo",
        "licence": "license",
        "compatibility": "applyTo",
        "compat": "applyTo",
        "variables": "parameters",
        "vars": "parameters",
        "variable": "parameters",
        "param": "parameters",
        "params": "parameters",
        "require": "requires",
        "dep": "requires",
        "deps": "requires",
        "dependencies": "requires",
    }
    raw = unknown.strip().lower()
    if raw in aliases:
        return aliases[raw]
    hyphenated = raw.replace("_", "-")
    if hyphenated in aliases:
        return aliases[hyphenated]

    matches = difflib.get_close_matches(unknown, sorted(ALLOWED_KEYS), n=1, cutoff=cutoff)
    if matches:
        return matches[0]
    matches = difflib.get_close_matches(hyphenated, sorted(ALLOWED_KEYS), n=1, cutoff=cutoff)
    return matches[0] if matches else None


def _is_valid_glob(pattern: str) -> tuple[bool, str | None]:
    if "\\" in pattern:
        return False, "contains backslashes (use forward slashes)"
    try:
        re.compile(fnmatch.translate(pattern))
    except re.error as exc:
        return False, str(exc)
    return True, None


def _collect_glob_patterns(meta: dict[str, Any], key: str, issues: list[SchemaIssue]) -> list[str]:
    if key not in meta:
        return []
    val = meta[key]
    items: list[str] = []
    if isinstance(val, str):
        items = [val]
    elif isinstance(val, (list, tuple)):
        for item in val:
            if isinstance(item, str):
                items.append(item)
            else:
                issues.append(
                    SchemaIssue(
                        field=key,
                        rule="E006",
                        message=(
                            f"Invalid glob pattern in '{key}': "
                            f"expected string, got {type(item).__name__}"
                        ),
                    )
                )
    else:
        issues.append(
            SchemaIssue(
                field=key,
                rule="E006",
                message=(
                    f"Invalid '{key}': expected string or list of strings, got {type(val).__name__}"
                ),
            )
        )
        return []

    for pattern in items:
        ok, reason = _is_valid_glob(pattern)
        if not ok:
            issues.append(
                SchemaIssue(
                    field=key,
                    rule="E006",
                    message=f"Invalid path glob pattern '{pattern}': {reason}",
                    hint="Use forward-slash globs like '**/*.py'",
                )
            )
    return items


def _collect_requires(meta: dict[str, Any], issues: list[SchemaIssue]) -> tuple[str, ...]:
    """Validate optional ``requires`` list of skill name strings."""
    if "requires" not in meta:
        return ()
    val = meta["requires"]
    items: list[str] = []
    if isinstance(val, str):
        items = [val]
    elif isinstance(val, (list, tuple)):
        for item in val:
            if isinstance(item, str):
                items.append(item)
            else:
                issues.append(
                    SchemaIssue(
                        field="requires",
                        rule="E008",
                        message=(
                            f"Invalid entry in 'requires': expected skill name string, "
                            f"got {type(item).__name__}"
                        ),
                        hint="Use requires: [skill-a, skill-b]",
                    )
                )
    else:
        issues.append(
            SchemaIssue(
                field="requires",
                rule="E008",
                message=(
                    f"Invalid 'requires': expected string or list of strings, "
                    f"got {type(val).__name__}"
                ),
                hint="Use requires: [skill-a, skill-b]",
            )
        )
        return ()

    names: list[str] = []
    seen: set[str] = set()
    for raw in items:
        name = raw.strip()
        if not name:
            issues.append(
                SchemaIssue(
                    field="requires",
                    rule="E008",
                    message="Invalid 'requires': skill name must be a non-empty string",
                )
            )
            continue
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return tuple(names)


@dataclass(frozen=True)
class SkillManifestSchema:
    """Validated skill frontmatter. Build via :meth:`validate`."""

    name: str
    description: str
    version: str | None = None
    author: str | None = None
    license: str | None = None
    paths: tuple[str, ...] = ()
    globs: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()

    @classmethod
    def validate(cls, meta: dict[str, Any]) -> tuple[SkillManifestSchema | None, list[SchemaIssue]]:
        """Validate raw frontmatter meta. Returns (model_or_None, issues)."""
        issues: list[SchemaIssue] = []

        for key in meta:
            if key not in ALLOWED_KEYS:
                suggestion = suggest_key(key)
                hint = f"Did you mean '{suggestion}'?" if suggestion else None
                msg = f"Unrecognized frontmatter key '{key}'"
                if hint:
                    msg = f"{msg}. {hint}"
                issues.append(SchemaIssue(field=key, rule="E005", message=msg, hint=hint))

        name = meta.get("name")
        if name is None or (isinstance(name, str) and not name.strip()):
            issues.append(
                SchemaIssue(
                    field="name",
                    rule="E003",
                    message="Missing 'name' in frontmatter or empty name",
                )
            )
            name_str = ""
        elif not isinstance(name, str):
            issues.append(
                SchemaIssue(
                    field="name",
                    rule="E003",
                    message=f"Invalid 'name': expected string, got {type(name).__name__}",
                )
            )
            name_str = ""
        else:
            name_str = name.strip()
            if not KEBAB_CASE_PATTERN.match(name_str):
                issues.append(
                    SchemaIssue(
                        field="name",
                        rule="W001",
                        message=(
                            f"Skill name '{name_str}' is not valid kebab-case "
                            "(expected ^[a-z0-9]+(-[a-z0-9]+)*$)"
                        ),
                    )
                )

        desc = meta.get("description")
        if desc is None or (isinstance(desc, str) and not desc.strip()):
            issues.append(
                SchemaIssue(
                    field="description",
                    rule="E004",
                    message="Missing 'description' in frontmatter (required in --strict mode)",
                    hint="Add a description key, e.g. description: What this skill does",
                )
            )
            desc_str = ""
        elif not isinstance(desc, str):
            issues.append(
                SchemaIssue(
                    field="description",
                    rule="E004",
                    message=f"Invalid 'description': expected string, got {type(desc).__name__}",
                )
            )
            desc_str = ""
        else:
            desc_str = desc.strip()
            if len(desc_str) < MIN_DESCRIPTION_LENGTH:
                issues.append(
                    SchemaIssue(
                        field="description",
                        rule="E004",
                        message=(
                            "Description shorter than "
                            f"{MIN_DESCRIPTION_LENGTH} characters (required in --strict mode)"
                        ),
                    )
                )
            elif len(desc_str) > MAX_DESCRIPTION_LENGTH:
                issues.append(
                    SchemaIssue(
                        field="description",
                        rule="E007",
                        message=(
                            f"Description exceeds {MAX_DESCRIPTION_LENGTH} characters "
                            "(Cursor/Windsurf dialect limit)"
                        ),
                        hint="Shorten the description or move detail into the skill body",
                    )
                )

        collected_paths = _collect_glob_patterns(meta, "paths", issues)
        collected_globs = _collect_glob_patterns(meta, "globs", issues)
        collected_requires = _collect_requires(meta, issues)

        def _opt_str(key: str) -> str | None:
            if key not in meta:
                return None
            val = meta[key]
            if val is None or val == "":
                return None
            if not isinstance(val, str):
                issues.append(
                    SchemaIssue(
                        field=key,
                        rule="E005",
                        message=f"Invalid '{key}': expected string, got {type(val).__name__}",
                    )
                )
                return None
            return val

        version = _opt_str("version")
        author = _opt_str("author")
        license_ = _opt_str("license")

        has_blocking = any(i.rule.startswith("E") for i in issues)
        if has_blocking or not name_str or not desc_str:
            return None, issues

        return (
            cls(
                name=name_str,
                description=desc_str,
                version=version,
                author=author,
                license=license_,
                paths=tuple(collected_paths),
                globs=tuple(collected_globs),
                requires=collected_requires,
            ),
            issues,
        )
