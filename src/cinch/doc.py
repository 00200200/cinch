"""Canonical representation of skills, agents, and commands across harnesses."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cinch.inventory import Item

_INT_RE = re.compile(r"^[+-]?\d+$")


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


def _unquote(val: str) -> str:
    val = val.strip()
    if len(val) >= 2 and ((val[0] == val[-1] == '"') or (val[0] == val[-1] == "'")):
        return val[1:-1]
    return val


def _split_top_level(inner: str, sep: str = ",") -> list[str]:
    """Split on ``sep`` not inside quotes, brackets, or braces."""
    parts: list[str] = []
    buf: list[str] = []
    depth_brack = 0
    depth_brace = 0
    quote: str | None = None
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < len(inner):
                buf.append(inner[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == "[":
            depth_brack += 1
            buf.append(ch)
        elif ch == "]":
            depth_brack = max(0, depth_brack - 1)
            buf.append(ch)
        elif ch == "{":
            depth_brace += 1
            buf.append(ch)
        elif ch == "}":
            depth_brace = max(0, depth_brace - 1)
            buf.append(ch)
        elif ch == sep and depth_brack == 0 and depth_brace == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_flow_value(val: str) -> Any:
    """Parse a single YAML-ish scalar, inline list, or inline mapping."""
    val = val.strip()
    if not val:
        return ""
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [_parse_flow_value(p) for p in _split_top_level(inner)]
    if val.startswith("{") and val.endswith("}"):
        inner = val[1:-1].strip()
        if not inner:
            return {}
        out: dict[str, Any] = {}
        for part in _split_top_level(inner):
            if ":" not in part:
                continue
            k, _, v = part.partition(":")
            out[k.strip()] = _parse_flow_value(v.strip())
        return out
    lowered = val.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null" or lowered == "~":
        return None
    if _INT_RE.fullmatch(val):
        return int(val)
    return _unquote(val)


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-style frontmatter delimited by ---.

    Supports flat keys, indented lists, nested mappings (e.g. ``parameters``),
    and inline ``{...}`` / ``[...]`` flow values. Intentionally not full YAML.
    """
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

    fm_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1 :])

    root: dict[str, Any] = {}
    # Stack of (indent, container) where container is dict or list
    stack: list[tuple[int, Any]] = [(-1, root)]
    pending: tuple[int, dict[str, Any], str] | None = None

    def _close_pending_as(kind: str) -> None:
        nonlocal pending
        if pending is None:
            return
        indent, parent, key = pending
        if kind == "list":
            container: list[Any] | dict[str, Any] = []
        else:
            container = {}
        parent[key] = container
        stack.append((indent, container))
        pending = None

    for raw_line in fm_lines:
        if "\t" in raw_line:
            continue
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        if pending is not None:
            p_indent, _, _ = pending
            if indent > p_indent:
                if stripped.startswith("- ") or stripped == "-":
                    _close_pending_as("list")
                else:
                    _close_pending_as("map")
            else:
                # Empty key with no children → empty string (legacy flat behaviour)
                p_indent, parent, key = pending
                parent[key] = ""
                pending = None

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        container = stack[-1][1]

        if stripped.startswith("- ") or stripped == "-":
            item_raw = stripped[1:].strip()
            value = _parse_flow_value(item_raw) if item_raw else ""
            if isinstance(container, list):
                container.append(value)
            elif isinstance(container, dict):
                # Rare: list item without pending — ignore malformed
                continue
            continue

        if ":" not in stripped:
            continue

        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()
        if not key or not isinstance(container, dict):
            continue

        if val == "":
            pending = (indent, container, key)
            continue

        container[key] = _parse_flow_value(val)

    if pending is not None:
        _, parent, key = pending
        parent[key] = ""

    return root, body


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

    # Ensure description is a string (frontmatter may parse unquoted nums rarely)
    if not isinstance(description, str):
        description = str(description)
    if not isinstance(doc_name, str):
        doc_name = str(doc_name)

    return Doc(
        kind=kind,
        name=doc_name,
        description=description,
        body=clean_body,
        paths=paths,
        support=support_dir,
        extra_meta=meta,
    )
