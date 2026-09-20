"""Enumerate skills, agents, hooks, commands, plugins, and MCP servers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cinch.catalog import HARNESSES, tags_for
from cinch.errors import CinchError

STARTER_DIR = Path(__file__).parent / "starter"

__all__ = ["STARTER_DIR", "Item", "collect_inventory"]


@dataclass(frozen=True)
class Item:
    kind: str
    name: str
    source: Path
    tags: frozenset[str]


def collect_inventory(
    *,
    harness: str,
    home: Path,
    project: Path,
    purpose: str | None = None,
    extra_roots: tuple[Path, ...] = (),
    include_starter: bool = False,
) -> list[Item]:
    if harness not in HARNESSES:
        raise CinchError(f"Unknown harness: {harness}")
    spec = HARNESSES[harness]
    home = home.expanduser()
    items: dict[tuple[str, str], Item] = {}

    def add(item: Item) -> None:
        items.setdefault((item.kind, item.name), item)

    mapping = (
        ("skill", spec.skill_sources, _skills_in),
        ("agent", spec.agent_sources, _named_files_in),
        ("hook", spec.hook_sources, _hooks_in),
        ("command", spec.command_sources, _named_files_in),
        ("plugin", spec.plugin_sources, _plugins_in),
    )
    for kind, sources, scanner in mapping:
        for template in sources:
            scanner(add, kind, Path(_expand(template, home=home, project=project)))
        if kind in spec.project_dirs:
            scanner(add, kind, project / spec.project_dirs[kind])

    for template in spec.mcp_sources:
        _mcp_in(add, Path(_expand(template, home=home, project=project)))
    for name in (".mcp.json", ".cursor/mcp.json"):
        _mcp_in(add, project / name)

    for root in extra_roots:
        _skills_in(add, "skill", root)
        _skills_in(add, "skill", root / "skills")
        _named_files_in(add, "agent", root / "agents")
        _named_files_in(add, "command", root / "commands")
        _skills_in(add, "skill", root / "grok-bot" / "skills")
        _named_files_in(add, "agent", root / "grok-bot" / "agents")

    if include_starter:
        _skills_in(add, "skill", STARTER_DIR)

    result = list(items.values())
    if purpose:
        result = [item for item in result if purpose in item.tags]
    return sorted(result, key=lambda item: (item.kind, item.name))


def _expand(template: str, *, home: Path, project: Path) -> str:
    return template.format(home=str(home), project=str(project))


def _hidden(path: Path) -> bool:
    return any(part.startswith(".") and part not in {".", ".."} for part in path.parts)


def _skills_in(add, kind: str, root: Path) -> None:
    if not root.is_dir():
        return
    for skill_md in sorted(root.glob("*/SKILL.md")):
        if _hidden(skill_md.relative_to(root)):
            continue
        name = skill_md.parent.name
        add(Item(kind, name, skill_md.parent, tags_for(name)))


def _named_files_in(add, kind: str, root: Path) -> None:
    if not root.is_dir():
        return
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in {".md", ".toml", ".txt", ".yml", ".yaml"}:
            continue
        add(Item(kind, path.stem, path, tags_for(path.stem)))


def _hooks_in(add, kind: str, root: Path) -> None:
    if root.is_file():
        add(Item(kind, root.name, root, tags_for(root.stem)))
        return
    if not root.is_dir():
        return
    for path in sorted(root.iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        add(Item(kind, path.name, path, tags_for(path.stem)))


def _plugins_in(add, kind: str, root: Path) -> None:
    if not root.is_dir():
        return
    for path in sorted(root.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        if (path / "plugin.json").is_file() or (path / ".claude-plugin" / "plugin.json").is_file():
            add(Item(kind, path.name, path, tags_for(path.name)))


def _mcp_in(add, path: Path) -> None:
    if not path.is_file():
        return
    if path.suffix.lower() == ".toml":
        text = path.read_text(encoding="utf-8")
        if "mcp" not in text.lower():
            return
        add(Item("mcp", path.name, path, tags_for(path.stem)))
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    servers = payload.get("mcpServers") or payload.get("mcp") or {}
    if isinstance(servers, dict):
        for name in servers:
            add(Item("mcp", str(name), path, tags_for(str(name))))
