"""Turn CLI flags into a wiring plan."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cinch.catalog import HARNESSES, PURPOSES
from cinch.detect import detect_toolchain


class CinchError(Exception):
    """User-facing configuration or inventory error."""


@dataclass(frozen=True)
class PlannedCopy:
    kind: str
    name: str
    source: Path
    destination: Path


@dataclass(frozen=True)
class Plan:
    harness: str
    title: str
    project: Path
    toolchain: str
    dry_run: bool
    copies: tuple[PlannedCopy, ...]
    skipped: tuple[str, ...] = field(default_factory=tuple)


def parse_csv(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    parts = tuple(item.strip() for item in value.split(",") if item.strip())
    return parts


def resolve_plan(
    *,
    harness: str,
    project: Path | None = None,
    home: Path | None = None,
    purpose: str | None = None,
    skills: tuple[str, ...] | None = None,
    agents: tuple[str, ...] | None = None,
    hooks: tuple[str, ...] | None = None,
    commands: tuple[str, ...] | None = None,
    extra_roots: tuple[Path, ...] = (),
    dry_run: bool = False,
) -> Plan:
    from cinch.inventory import Item, collect_inventory

    if harness not in HARNESSES:
        raise CinchError(f"Unknown harness: {harness}")
    if purpose is not None and purpose not in PURPOSES:
        raise CinchError(f"Unknown purpose: {purpose}")
    spec = HARNESSES[harness]
    project = (project or Path.cwd()).resolve()
    home = (home or Path.home()).expanduser()
    inventory = collect_inventory(
        harness=harness,
        home=home,
        project=project,
        purpose=None,
        extra_roots=extra_roots,
    )
    selected: list[Item] = []
    skipped: list[str] = []
    requested = {
        "skill": skills,
        "agent": agents,
        "hook": hooks,
        "command": commands,
    }
    explicit = any(value is not None for value in requested.values())
    if explicit:
        by_kind: dict[str, dict[str, Item]] = {}
        for item in inventory:
            by_kind.setdefault(item.kind, {})[item.name] = item
        for kind, names in requested.items():
            if names is None:
                continue
            for name in names:
                item = by_kind.get(kind, {}).get(name)
                if item is None:
                    raise CinchError(f"{name} is not in the {harness} inventory")
                selected.append(item)
    else:
        pool = inventory
        if purpose:
            pool = [item for item in inventory if purpose in item.tags]
        selected.extend(pool)

    copies = []
    for item in selected:
        dest_root = spec.project_dirs.get(item.kind)
        if not dest_root:
            skipped.append(f"{item.kind}:{item.name}")
            continue
        destination = project / dest_root
        if item.source.is_dir():
            destination = destination / item.name
        elif dest_root.endswith(("hooks.json",)) or dest_root in {".", ".clinerules"}:
            destination = project / dest_root
            if dest_root == ".":
                destination = project / item.source.name
        else:
            destination = destination / item.source.name
        copies.append(
            PlannedCopy(kind=item.kind, name=item.name, source=item.source, destination=destination)
        )
    return Plan(
        harness=harness,
        title=spec.title,
        project=project,
        toolchain=detect_toolchain(project),
        dry_run=dry_run,
        copies=tuple(copies),
        skipped=tuple(skipped),
    )
