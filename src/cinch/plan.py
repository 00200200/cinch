"""Turn CLI flags into a cross-harness wiring plan."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cinch.adapters import get_adapter
from cinch.catalog import HARNESSES, PURPOSES
from cinch.detect import detect_harnesses, detect_toolchain
from cinch.doc import parse_doc
from cinch.errors import CinchError
from cinch.inventory import Item, collect_inventory

__all__ = ["CinchError", "Plan", "PlannedFile", "SkippedItem", "parse_csv", "resolve_plan"]


@dataclass(frozen=True)
class PlannedFile:
    """A file to be created, merged, or copied."""

    target: str
    relpath: str
    content: str
    mode: str  # "create" | "merge"
    kind: str
    name: str
    destination: Path
    source: Path | None = None
    support_source: Path | None = None
    support_dest: str | None = None


@dataclass(frozen=True)
class SkippedItem:
    kind: str
    name: str
    target: str
    reason: str


@dataclass(frozen=True)
class Plan:
    source_harness: str
    source_title: str
    targets: tuple[str, ...]
    title: str
    project: Path
    toolchain: str
    dry_run: bool
    files: tuple[PlannedFile, ...]
    skipped: tuple[SkippedItem, ...] = field(default_factory=tuple)

    @property
    def harness(self) -> str:
        """Primary target harness for backwards compatibility."""
        return self.targets[0] if self.targets else self.source_harness

    @property
    def copies(self) -> tuple[PlannedFile, ...]:
        """Alias for files for backwards compatibility."""
        return self.files


def parse_csv(value: str | tuple[str, ...] | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, (tuple, list)):
        return tuple(value)
    parts = tuple(item.strip() for item in value.split(",") if item.strip())
    return parts


def resolve_plan(
    *,
    harness: str | tuple[str, ...] | None = None,
    from_harness: str | None = None,
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
    project = (project or Path.cwd()).resolve()
    home = (home or Path.home()).expanduser()

    if purpose is not None and purpose not in PURPOSES:
        raise CinchError(f"Unknown purpose: {purpose}")

    # Validate target harnesses if explicitly passed
    targets: tuple[str, ...]
    if harness is not None:
        parsed_targets = parse_csv(harness)
        if parsed_targets:
            for t in parsed_targets:
                if t not in HARNESSES:
                    raise CinchError(f"Unknown harness: {t}")
            targets = parsed_targets
        else:
            targets = ()
    else:
        targets = ()

    # Determine source harness
    if from_harness is not None:
        if from_harness not in HARNESSES:
            raise CinchError(f"Unknown harness: {from_harness}")
        resolved_source = from_harness
    else:
        detected = detect_harnesses(home=home)
        present = [h.id for h in detected if h.present]
        if len(present) == 1:
            resolved_source = present[0]
        elif len(present) == 0:
            if harness and isinstance(harness, str) and "," not in harness and harness in HARNESSES:
                resolved_source = harness
            elif extra_roots:
                resolved_source = "claude"
            else:
                raise CinchError(
                    "No installed harness detected on disk. Specify source with --from-harness."
                )
        else:
            # Multiple present on disk
            if harness and isinstance(harness, str) and "," not in harness and harness in present:
                resolved_source = harness
            else:
                cands = ", ".join(present)
                raise CinchError(
                    f"Multiple harnesses detected ({cands}). Specify source with --from-harness."
                )

    # Determine target harnesses
    if not targets:
        targets = (resolved_source,)

    # Collect inventory from source harness
    inventory = collect_inventory(
        harness=resolved_source,
        home=home,
        project=project,
        purpose=None,
        extra_roots=extra_roots,
    )

    selected: list[Item] = []
    skipped_items: list[SkippedItem] = []
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
                    raise CinchError(f"{name} is not in the {resolved_source} inventory")
                selected.append(item)
    else:
        pool = inventory
        if purpose:
            pool = [item for item in inventory if purpose in item.tags]
        selected.extend(pool)

    files: list[PlannedFile] = []

    for item in selected:
        if item.kind == "hook":
            for target in targets:
                if target != resolved_source:
                    skipped_items.append(
                        SkippedItem(
                            kind="hook",
                            name=item.name,
                            target=target,
                            reason="Hooks cannot be translated across different harnesses",
                        )
                    )
                else:
                    # Same harness hook: copy verbatim
                    spec = HARNESSES[target]
                    dest_root = spec.project_dirs.get("hook", ".claude/hooks")
                    dest = project / dest_root / item.source.name
                    files.append(
                        PlannedFile(
                            target=target,
                            relpath=str(dest.relative_to(project)),
                            content="",
                            mode="create",
                            kind="hook",
                            name=item.name,
                            destination=dest,
                            source=item.source,
                        )
                    )
            continue

        doc = parse_doc(item)
        for target in targets:
            adapter = get_adapter(target)
            rendered_list = adapter.render(doc)
            for rf in rendered_list:
                files.append(
                    PlannedFile(
                        target=target,
                        relpath=rf.relpath,
                        content=rf.text,
                        mode=rf.mode,
                        kind=item.kind,
                        name=item.name,
                        destination=project / rf.relpath,
                        source=item.source,
                        support_source=rf.support_source,
                        support_dest=rf.support_dest,
                    )
                )

    source_spec = HARNESSES[resolved_source]
    target_titles = [HARNESSES[t].title for t in targets]
    display_title = ", ".join(target_titles)

    return Plan(
        source_harness=resolved_source,
        source_title=source_spec.title,
        targets=targets,
        title=display_title,
        project=project,
        toolchain=detect_toolchain(project),
        dry_run=dry_run,
        files=tuple(files),
        skipped=tuple(skipped_items),
    )
