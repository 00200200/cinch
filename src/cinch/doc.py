"""Canonical representation of skills, agents, and commands across harnesses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cinch.inventory import Item


@dataclass(frozen=True)
class Doc:
    """Canonical document for cross-harness translation."""

    kind: str  # skill | agent | command
    name: str
    description: str
    body: str  # markdown with frontmatter stripped
    paths: tuple[str, ...] = ()  # globs declared by the item
    support: Path | None = None  # source dir when it holds extra files (scripts, references)
    extra_meta: dict[str, Any] = field(default_factory=dict)


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-style frontmatter delimited by ---."""
    if not content.startswith("---"):
        return {}, content

    lines = content.splitlines()
    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx == -1:
        return {}, content

    meta: dict[str, Any] = {}
    fm_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1 :])

    current_key: str | None = None
    current_list: list[str] | None = None

    for line in fm_lines:
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue

        if line_stripped.startswith("- ") and current_key and current_list is not None:
            val = line_stripped[2:].strip().strip("\"'")
            current_list.append(val)
            continue

        if ":" in line:
            if current_key and current_list is not None:
                meta[current_key] = current_list
                current_list = None

            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()

            if val == "":
                current_key = key
                current_list = []
            elif val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                items = [x.strip().strip("\"'") for x in inner.split(",") if x.strip()]
                meta[key] = items
                current_key = None
            else:
                meta[key] = val.strip("\"'")
                current_key = None

    if current_key and current_list is not None:
        meta[current_key] = current_list

    return meta, body


def parse_doc(item: Item) -> Doc:
    """Parse an on-disk Item into a canonical Doc."""
    source = item.source
    name = item.name
    kind = item.kind
    support_dir: Path | None = None

    if source.is_dir():
        skill_file = source / "SKILL.md"
        if not skill_file.is_file():
            # Look for any markdown file or fallback to empty
            md_files = list(source.glob("*.md"))
            skill_file = md_files[0] if md_files else source / "README.md"

        content = skill_file.read_text(encoding="utf-8") if skill_file.is_file() else ""
        # Check if source directory contains support files
        entries = [
            f for f in source.iterdir() if f.name not in ("SKILL.md", ".DS_Store", "__pycache__")
        ]
        if entries:
            support_dir = source
    else:
        content = source.read_text(encoding="utf-8") if source.is_file() else ""

    meta, body = parse_frontmatter(content)

    doc_name = meta.get("name") or name
    description = meta.get("description", "")

    # Extract description from body if missing
    if not description:
        for line in body.splitlines():
            line_str = line.strip()
            if line_str and not line_str.startswith("#"):
                description = line_str
                break
        if not description:
            description = f"{doc_name} {kind}"

    paths_val = meta.get("paths") or meta.get("globs") or meta.get("applyTo") or ()
    if isinstance(paths_val, str):
        paths: tuple[str, ...] = (paths_val,)
    else:
        paths = tuple(paths_val)

    if meta:
        clean_body = body.strip()
        lines = clean_body.splitlines()
        if lines and lines[0].strip().lower() in (f"# {doc_name.lower()}", f"# {name.lower()}"):
            clean_body = "\n".join(lines[1:]).strip()
    else:
        clean_body = body

    return Doc(
        kind=kind,
        name=doc_name,
        description=description,
        body=clean_body,
        paths=paths,
        support=support_dir,
        extra_meta=meta,
    )
