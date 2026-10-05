"""Turn CLI flags into a cross-harness wiring plan."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from cinch.adapters import get_adapter
from cinch.catalog import HARNESSES, PURPOSES
from cinch.detect import detect_harnesses, detect_toolchain
from cinch.doc import Doc, parse_doc
from cinch.errors import CinchError
from cinch.inventory import Item, collect_inventory
from cinch.params import apply_parameters_to_doc
from cinch.resolver import expand_with_requires, requires_from_meta

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
    binaries: set[str] | None = None,
    param_overrides: Mapping[str, str] | None = None,
    interactive_params: bool = False,
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
    elif extra_roots:
        resolved_source = "claude"
    else:
        detected = detect_harnesses(home=home, binaries=binaries, project=project)
        present = [h.id for h in detected if h.present]
        if len(present) == 1:
            resolved_source = present[0]
        elif len(present) == 0:
            # Nothing on disk: allow same-harness wiring when a single target is named.
            if len(targets) == 1:
                resolved_source = targets[0]
            else:
                raise CinchError(
                    "No installed harness detected on disk. Specify source with --from-harness."
                )
        else:
            # Same-harness shortcut: a single named target that is installed may
            # serve as the source. Cross-wiring (other/missing targets) must be explicit.
            if len(targets) == 1 and targets[0] in present:
                resolved_source = targets[0]
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

    selected = _expand_selected_requires(selected, inventory)

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

        doc = apply_parameters_to_doc(
            parse_doc(item),
            cli_overrides=param_overrides,
            interactive=interactive_params,
        )
        doc = _strip_requires_meta(doc)
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


def _strip_requires_meta(doc: Doc) -> Doc:
    """Drop Cinch-native ``requires`` before dialect adapters render frontmatter."""
    if not doc.extra_meta or "requires" not in doc.extra_meta:
        return doc if not doc.requires else replace(doc, requires=())
    new_meta = {k: v for k, v in doc.extra_meta.items() if k != "requires"}
    return replace(doc, requires=(), extra_meta=new_meta)


def _expand_selected_requires(selected: list[Item], inventory: list[Item]) -> list[Item]:
    """Include transitive ``requires`` skills (deduped, dependency-first order)."""
    skill_by_name = {item.name: item for item in inventory if item.kind == "skill"}
    if not skill_by_name:
        return selected

    graph: dict[str, tuple[str, ...]] = {}
    for name, item in skill_by_name.items():
        doc = parse_doc(item)
        if "requires" not in doc.extra_meta:
            graph[name] = ()
            continue
        try:
            graph[name] = requires_from_meta(doc.extra_meta)
        except CinchError as exc:
            raise CinchError(f"Skill '{name}': {exc}") from exc

    selected_skills = [item.name for item in selected if item.kind == "skill"]
    if not selected_skills:
        return selected

    # Only expand when at least one selected skill declares requires.
    if not any(graph.get(name) for name in selected_skills):
        return selected

    ordered = expand_with_requires(
        selected_skills,
        graph,
        available=skill_by_name.keys(),
    )

    non_skills = [item for item in selected if item.kind != "skill"]
    expanded_skills = [skill_by_name[name] for name in ordered]
    return expanded_skills + non_skills
