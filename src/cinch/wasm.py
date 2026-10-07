"""WebAssembly and Pyodide compilation engine for in-browser Cinch playground.

Provides high-speed, zero-dependency translation of Cinch skills into all
supported AI harness dialects (Claude, Cursor, Codex, Copilot, Gemini, Windsurf,
Cline, OpenCode, Aider, Zed, Continue, Grok).
"""

from __future__ import annotations

import json
import time
from typing import Any

from cinch.adapters import ADAPTERS, get_adapter
from cinch.doc import Doc, parse_frontmatter
from cinch.lsp import parse_diagnostics


def doc_from_markdown(
    content: str,
    name: str | None = None,
    kind: str = "skill",
) -> Doc:
    """Parse markdown skill content into a canonical Doc object."""
    meta, body = parse_frontmatter(content)
    doc_name = meta.get("name") or name or "sample-skill"
    description = meta.get("description", "")

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

    requires_val = meta.get("requires") or ()
    if isinstance(requires_val, str):
        requires: tuple[str, ...] = (requires_val.strip(),) if requires_val.strip() else ()
    elif isinstance(requires_val, (list, tuple)):
        requires = tuple(
            item.strip() for item in requires_val if isinstance(item, str) and item.strip()
        )
    else:
        requires = ()

    clean_body = body.strip()
    lines = clean_body.splitlines()
    if lines and lines[0].startswith("# "):
        h1 = lines[0][2:].strip().lower()
        if h1 in (doc_name.lower(), doc_name.lower().replace("-", " "), "skill"):
            clean_body = "\n".join(lines[1:]).strip()

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
        requires=requires,
        extra_meta=meta,
    )


def compile_skill(content: str, target: str) -> list[dict[str, str]]:
    """Compile markdown skill to a target harness dialect."""
    doc = doc_from_markdown(content)
    adapter = get_adapter(target)
    files = adapter.render(doc)
    return [
        {
            "relpath": f.relpath,
            "text": f.text,
            "mode": f.mode,
        }
        for f in files
    ]


def compile_all_dialects(content: str) -> dict[str, list[dict[str, str]]]:
    """Compile markdown skill into all 12 supported AI harness dialects."""
    doc = doc_from_markdown(content)
    results: dict[str, list[dict[str, str]]] = {}
    for target, adapter in ADAPTERS.items():
        files = adapter.render(doc)
        results[target] = [
            {
                "relpath": f.relpath,
                "text": f.text,
                "mode": f.mode,
            }
            for f in files
        ]
    return results


def validate_skill(content: str) -> list[dict[str, Any]]:
    """Validate skill frontmatter and return diagnostic warnings/errors."""
    return parse_diagnostics(content)


def compile_json(content: str, target: str | None = None) -> str:
    """Entry point for WebAssembly / Pyodide / JS interop.

    Accepts raw markdown string, returns JSON string containing:
    - valid: bool
    - diagnostics: list of lint issues
    - dialects: dict of rendered files per dialect (or single target)
    - elapsed_ms: compilation time in milliseconds
    """
    t0 = time.perf_counter()
    diagnostics = validate_skill(content)
    has_errors = any(d.get("severity") == 1 for d in diagnostics)

    if target:
        dialects = {target: compile_skill(content, target)}
    else:
        dialects = compile_all_dialects(content)

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)

    return json.dumps(
        {
            "valid": not has_errors,
            "diagnostics": diagnostics,
            "dialects": dialects,
            "elapsed_ms": elapsed_ms,
        },
        indent=2,
    )


__all__ = [
    "doc_from_markdown",
    "compile_skill",
    "compile_all_dialects",
    "validate_skill",
    "compile_json",
]
