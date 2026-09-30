"""Decompile legacy harness rule/skill files into canonical Cinch skills."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from cinch.adapters import render_cinch_skill
from cinch.doc import Doc, parse_frontmatter
from cinch.errors import CinchError
from cinch.schema import ALLOWED_KEYS

# Dialects `cinch import` can reverse-sync in v1.
IMPORT_DIALECTS = ("claude", "cursor", "copilot", "cline")

DEFAULT_OUT = Path(".cinch/imported")

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_HEADING_RE = re.compile(r"^#+\s+(.+)$")


@dataclass(frozen=True)
class ImportPlanItem:
    """One skill Doc ready to write under ``out/<name>/SKILL.md``."""

    doc: Doc
    source: Path
    dialect: str


@dataclass(frozen=True)
class ImportResult:
    dialect: str
    out: Path
    dry_run: bool
    written: tuple[str, ...]
    skipped: tuple[str, ...]
    preview: tuple[tuple[str, str], ...]  # (relpath, text) for dry-run / summary


def slugify(name: str) -> str:
    """Normalize a filename/dir into kebab-case skill name."""
    cleaned = name.strip().lower().replace("_", "-")
    cleaned = _SLUG_RE.sub("-", cleaned).strip("-")
    return cleaned or "imported-skill"


def _description_from_heading(body: str, default: str) -> str:
    for line in body.splitlines():
        match = _HEADING_RE.match(line.strip())
        if match:
            text = match.group(1).strip()
            if text:
                return text
    return default


def _as_paths(val: Any) -> tuple[str, ...]:
    if val is None or val == "":
        return ()
    if isinstance(val, str):
        # Copilot sometimes uses a single quoted glob string
        return (val,) if val.strip() else ()
    if isinstance(val, (list, tuple)):
        return tuple(str(item) for item in val if item is not None and str(item).strip())
    return (str(val),)


def _filter_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Keep known Cinch frontmatter keys; drop unrecognized dialect noise."""
    return {k: v for k, v in meta.items() if k in ALLOWED_KEYS}


def detect_dialects(path: Path) -> list[str]:
    """Return harness ids suggested by path markers (may be empty or multiple)."""
    path = path.expanduser()
    resolved = path.resolve() if path.exists() else path
    name = resolved.name
    parts = {p.lower() for p in resolved.parts}
    dialects: list[str] = []

    # Precise file / leaf markers first
    if name == ".cursorrules" or name == "cursorrules":
        return ["cursor"]
    if name == "SKILL.md":
        return ["claude"]
    if name == "copilot-instructions.md":
        return ["copilot"]
    if name.endswith(".instructions.md"):
        return ["copilot"]
    if name == ".clinerules" or name == "clinerules":
        return ["cline"]

    # Directory markers
    if name == "rules" and resolved.parent.name == ".cursor":
        return ["cursor"]
    if name == "instructions" and resolved.parent.name == ".github":
        return ["copilot"]
    if name == "skills" and resolved.parent.name == ".claude":
        return ["claude"]
    if resolved.is_dir() and (resolved / "SKILL.md").is_file():
        return ["claude"]

    # Path contains known segments
    if ".cursor" in parts and "rules" in parts:
        dialects.append("cursor")
    if name == ".cursor" or (resolved.is_dir() and (resolved / "rules").exists()):
        if "cursor" not in dialects:
            # Only if rules or .cursorrules nearby — checked below for project roots
            pass

    if resolved.is_dir():
        found: list[str] = []
        if (resolved / ".cursorrules").exists() or (resolved / ".cursor" / "rules").exists():
            found.append("cursor")
        if (resolved / ".claude" / "skills").is_dir() or any(resolved.glob("**/SKILL.md")):
            # Prefer explicit .claude/skills; bare SKILL.md package already handled above
            if (resolved / ".claude" / "skills").is_dir():
                found.append("claude")
            elif (resolved / "SKILL.md").is_file():
                found.append("claude")
        copilot_file = resolved / ".github" / "copilot-instructions.md"
        instructions_dir = resolved / ".github" / "instructions"
        if copilot_file.is_file() or instructions_dir.is_dir():
            found.append("copilot")
        clinerules = resolved / ".clinerules"
        if clinerules.exists():
            found.append("cline")
        if found:
            return found

    # Suffix / extension hints for loose files
    if resolved.is_file():
        suffix = resolved.suffix.lower()
        if suffix in {".mdc", ".md"} and ".cursor" in parts:
            return ["cursor"]
        if suffix == ".md" and ".clinerules" in parts:
            return ["cline"]
        if suffix == ".md" and ".github" in parts:
            return ["copilot"]

    return dialects


def resolve_dialect(path: Path, explicit: str | None) -> str:
    """Pick a single import dialect or raise when detection is ambiguous/missing."""
    if explicit:
        if explicit not in IMPORT_DIALECTS:
            raise CinchError(
                f"Unsupported import dialect '{explicit}'. "
                f"Choose one of: {', '.join(IMPORT_DIALECTS)}"
            )
        return explicit

    found = detect_dialects(path)
    if len(found) == 1:
        return found[0]
    if not found:
        raise CinchError(
            f"Could not detect legacy dialect for {path}. "
            f"Pass --from-harness one of: {', '.join(IMPORT_DIALECTS)}"
        )
    raise CinchError(
        f"Ambiguous import source at {path} (found: {', '.join(found)}). "
        f"Pass --from-harness to choose one."
    )


def _name_from_path(path: Path) -> str:
    name = path.name
    if name in {".cursorrules", "cursorrules"}:
        return "cursorrules"
    if name in {".clinerules", "clinerules"}:
        return "clinerules"
    if name == "copilot-instructions.md":
        return "copilot-instructions"
    if name == "SKILL.md":
        return slugify(path.parent.name)
    if name.endswith(".instructions.md"):
        return slugify(name[: -len(".instructions.md")])
    if name.endswith(".mdc"):
        return slugify(path.stem)
    if name.endswith(".md"):
        return slugify(path.stem)
    return slugify(name)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CinchError(f"Cannot read {path}: {exc}") from exc


def _doc_from_markdown_rules(
    path: Path,
    *,
    default_name: str | None = None,
) -> Doc:
    """Parse a markdown/MDC rules file into a skill Doc."""
    content = _read_text(path)
    meta, body = parse_frontmatter(content)
    body = body.strip()
    name = slugify(str(meta.get("name") or default_name or _name_from_path(path)))
    description = meta.get("description")
    if not isinstance(description, str) or not description.strip():
        description = _description_from_heading(body, f"Imported rules from {path.name}")
    paths = _as_paths(meta.get("paths") or meta.get("globs") or meta.get("applyTo"))
    # Drop name/description/paths from extra; keep other allowed keys
    extra = _filter_meta(
        {k: v for k, v in meta.items() if k not in ("name", "description", "paths", "globs")}
    )
    # Prefer paths over applyTo/globs in Doc.paths; drop applyTo from extra if we mapped it
    extra.pop("applyTo", None)
    return Doc(
        kind="skill",
        name=name,
        description=description.strip(),
        body=body,
        paths=paths,
        extra_meta=extra,
    )


def _import_claude(path: Path) -> list[ImportPlanItem]:
    path = path.expanduser().resolve()
    items: list[ImportPlanItem] = []

    def add_skill_dir(skill_dir: Path) -> None:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            return
        content = _read_text(skill_md)
        meta, body = parse_frontmatter(content)
        body = body.strip()
        # Strip duplicate leading H1 matching the skill name
        name = slugify(str(meta.get("name") or skill_dir.name))
        lines = body.splitlines()
        if lines and lines[0].strip().lower() in (f"# {name}", f"# {skill_dir.name.lower()}"):
            body = "\n".join(lines[1:]).strip()
        description = meta.get("description")
        if not isinstance(description, str) or not description.strip():
            description = _description_from_heading(body, f"{name} skill")
        paths = _as_paths(meta.get("paths") or meta.get("globs") or meta.get("applyTo"))
        extra = _filter_meta(
            {k: v for k, v in meta.items() if k not in ("name", "description", "paths", "globs")}
        )
        extra.pop("applyTo", None)
        support: Path | None = None
        entries = [
            f for f in skill_dir.iterdir() if f.name not in ("SKILL.md", ".DS_Store", "__pycache__")
        ]
        if entries:
            support = skill_dir
        doc = Doc(
            kind="skill",
            name=name,
            description=description.strip(),
            body=body,
            paths=paths,
            support=support,
            extra_meta=extra,
        )
        items.append(ImportPlanItem(doc=doc, source=skill_md, dialect="claude"))

    if path.is_file() and path.name == "SKILL.md":
        add_skill_dir(path.parent)
        return items
    if path.is_dir() and (path / "SKILL.md").is_file():
        add_skill_dir(path)
        return items

    skills_root = path / ".claude" / "skills" if (path / ".claude" / "skills").is_dir() else path
    if skills_root.is_dir():
        # Nested skill packages
        for skill_md in sorted(skills_root.rglob("SKILL.md")):
            add_skill_dir(skill_md.parent)
    if not items:
        raise CinchError(f"No Claude SKILL.md found under {path}")
    return items


def _import_cursor(path: Path) -> list[ImportPlanItem]:
    path = path.expanduser().resolve()
    items: list[ImportPlanItem] = []

    def add_file(file_path: Path) -> None:
        if not file_path.is_file():
            return
        if file_path.suffix.lower() not in {".md", ".mdc", ""} and file_path.name not in {
            ".cursorrules",
            "cursorrules",
        }:
            return
        doc = _doc_from_markdown_rules(file_path)
        items.append(ImportPlanItem(doc=doc, source=file_path, dialect="cursor"))

    if path.is_file():
        add_file(path)
        return items

    # Directory: .cursor/rules, project root, or a rules folder
    candidates: list[Path] = []
    cursorrules = path / ".cursorrules"
    if cursorrules.is_file():
        candidates.append(cursorrules)
    rules_dir = path / ".cursor" / "rules"
    if not rules_dir.is_dir() and path.name == "rules" and path.parent.name == ".cursor":
        rules_dir = path
    if not rules_dir.is_dir() and (path / "rules").is_dir() and path.name == ".cursor":
        rules_dir = path / "rules"
    if rules_dir.is_dir():
        for child in sorted(rules_dir.iterdir()):
            if child.is_file() and child.suffix.lower() in {".md", ".mdc"}:
                candidates.append(child)
    # If path itself is a folder of rule markdown (no markers), import md/mdc children
    if not candidates and path.is_dir():
        for child in sorted(path.iterdir()):
            if child.is_file() and child.suffix.lower() in {".md", ".mdc"}:
                candidates.append(child)
        if (path / ".cursorrules").is_file():
            candidates.append(path / ".cursorrules")

    for file_path in candidates:
        add_file(file_path)

    if not items:
        raise CinchError(f"No Cursor rules found under {path}")
    return items


def _import_copilot(path: Path) -> list[ImportPlanItem]:
    path = path.expanduser().resolve()
    items: list[ImportPlanItem] = []

    def add_file(file_path: Path, default_name: str | None = None) -> None:
        doc = _doc_from_markdown_rules(file_path, default_name=default_name)
        items.append(ImportPlanItem(doc=doc, source=file_path, dialect="copilot"))

    if path.is_file():
        add_file(path)
        return items

    copilot = path / ".github" / "copilot-instructions.md"
    if copilot.is_file():
        add_file(copilot, default_name="copilot-instructions")

    instructions = path / ".github" / "instructions"
    if not instructions.is_dir() and path.name == "instructions":
        instructions = path
    if instructions.is_dir():
        for child in sorted(instructions.iterdir()):
            if child.is_file() and child.name.endswith(".instructions.md"):
                add_file(child)
            elif child.is_file() and child.suffix.lower() == ".md":
                add_file(child)

    if not items:
        raise CinchError(f"No Copilot instructions found under {path}")
    return items


def _parse_cline_markdown(path: Path) -> Doc:
    """Parse a Cline rule file, including the adapter's ``# name`` / ``> desc`` shape."""
    content = _read_text(path)
    meta, body = parse_frontmatter(content)
    body = body.strip()
    paths = _as_paths(meta.get("paths") or meta.get("globs"))

    name = meta.get("name")
    description = meta.get("description")
    lines = body.splitlines()
    body_start = 0

    if lines and lines[0].startswith("# "):
        heading = lines[0][2:].strip()
        if not isinstance(name, str) or not name.strip():
            name = heading
        body_start = 1
        # Optional blockquote description on the next non-empty line
        idx = body_start
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        if idx < len(lines) and lines[idx].lstrip().startswith(">"):
            quote = lines[idx].lstrip()[1:].strip()
            if not isinstance(description, str) or not description.strip():
                description = quote
            body_start = idx + 1
            while body_start < len(lines) and not lines[body_start].strip():
                body_start += 1

    clean_body = "\n".join(lines[body_start:]).strip()
    if not isinstance(name, str) or not name.strip():
        name = _name_from_path(path)
    name = slugify(str(name))
    if not isinstance(description, str) or not description.strip():
        description = _description_from_heading(clean_body, f"Imported Cline rules ({name})")
    extra = _filter_meta(
        {k: v for k, v in meta.items() if k not in ("name", "description", "paths", "globs")}
    )
    return Doc(
        kind="skill",
        name=name,
        description=description.strip(),
        body=clean_body,
        paths=paths,
        extra_meta=extra,
    )


def _import_cline(path: Path) -> list[ImportPlanItem]:
    path = path.expanduser().resolve()
    items: list[ImportPlanItem] = []

    def add_file(file_path: Path) -> None:
        doc = _parse_cline_markdown(file_path)
        items.append(ImportPlanItem(doc=doc, source=file_path, dialect="cline"))

    if path.is_file():
        add_file(path)
        return items

    clinerules = path / ".clinerules"
    if clinerules.is_file():
        add_file(clinerules)
        return items
    if clinerules.is_dir():
        root = clinerules
    elif path.name == ".clinerules" or path.is_dir():
        root = path
    else:
        root = path

    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_file() and child.suffix.lower() in {".md", ".txt"}:
                add_file(child)

    if not items:
        raise CinchError(f"No Cline rules found under {path}")
    return items


def collect_import_items(path: Path, dialect: str) -> list[ImportPlanItem]:
    """Collect ImportPlanItems for a path using the given dialect."""
    if dialect == "claude":
        return _import_claude(path)
    if dialect == "cursor":
        return _import_cursor(path)
    if dialect == "copilot":
        return _import_copilot(path)
    if dialect == "cline":
        return _import_cline(path)
    raise CinchError(f"Unsupported import dialect: {dialect}")


def write_import(
    items: list[ImportPlanItem],
    *,
    out: Path,
    dry_run: bool = False,
    overwrite: bool = False,
) -> ImportResult:
    """Write imported skills as ``out/<name>/SKILL.md`` (plus support files)."""
    out = out.expanduser().resolve()
    written: list[str] = []
    skipped: list[str] = []
    preview: list[tuple[str, str]] = []

    # Deduplicate by skill name (last wins, with notice via skip of earlier — keep first)
    seen: dict[str, ImportPlanItem] = {}
    for item in items:
        if item.doc.name in seen:
            skipped.append(f"{item.doc.name} (duplicate name from {item.source})")
            continue
        seen[item.doc.name] = item

    dialect = items[0].dialect if items else "unknown"

    for name, item in seen.items():
        text = render_cinch_skill(item.doc)
        rel = f"{name}/SKILL.md"
        preview.append((rel, text))
        dest_dir = out / name
        dest = dest_dir / "SKILL.md"
        if dry_run:
            written.append(rel)
            continue
        if dest.exists() and not overwrite:
            skipped.append(f"{rel} (exists; pass --yes to overwrite)")
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        if item.doc.support and item.doc.support.is_dir():
            for entry in item.doc.support.iterdir():
                if entry.name in ("SKILL.md", ".DS_Store", "__pycache__"):
                    continue
                target = dest_dir / entry.name
                if entry.is_dir():
                    if target.exists() and overwrite:
                        shutil.rmtree(target)
                    if not target.exists():
                        shutil.copytree(entry, target)
                elif entry.is_file():
                    if target.exists() and not overwrite:
                        continue
                    shutil.copy2(entry, target)
        written.append(rel)

    return ImportResult(
        dialect=dialect,
        out=out,
        dry_run=dry_run,
        written=tuple(written),
        skipped=tuple(skipped),
        preview=tuple(preview),
    )


def run_import(
    path: Path,
    *,
    out: Path | None = None,
    dialect: str | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
) -> ImportResult:
    """Detect dialect, collect docs, and write (or dry-run) canonical Cinch skills."""
    path = path.expanduser()
    if not path.exists():
        raise CinchError(f"Path not found: {path}")
    resolved = resolve_dialect(path, dialect)
    items = collect_import_items(path, resolved)
    if not items:
        raise CinchError(f"Nothing to import from {path}")
    # Ensure dialect field is consistent
    items = [
        replace(item, dialect=resolved) if item.dialect != resolved else item for item in items
    ]
    return write_import(
        items,
        out=out or (Path.cwd() / DEFAULT_OUT),
        dry_run=dry_run,
        overwrite=overwrite,
    )
