"""Stdlib polling watcher that re-wires skills on markdown changes."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from cinch.catalog import HARNESSES
from cinch.errors import CinchError
from cinch.plan import resolve_plan
from cinch.wire import apply_plan

DEFAULT_DEBOUNCE_MS = 150
DEFAULT_POLL_MS = 50

__all__ = [
    "DEFAULT_DEBOUNCE_MS",
    "DEFAULT_POLL_MS",
    "WatchChange",
    "WatchConfig",
    "diff_snapshots",
    "rebuild",
    "resolve_watch_roots",
    "run_watch",
    "scan_skill_mtimes",
    "watch_once",
]


@dataclass(frozen=True)
class WatchChange:
    """A create / modify / delete relative to the previous mtime snapshot."""

    path: str
    kind: str  # "created" | "modified" | "deleted"


@dataclass(frozen=True)
class WatchConfig:
    project: Path
    home: Path
    harness: str | tuple[str, ...] | None = None
    from_harness: str | None = None
    extra_roots: tuple[Path, ...] = ()
    skills: tuple[str, ...] | None = None
    agents: tuple[str, ...] | None = None
    hooks: tuple[str, ...] | None = None
    commands: tuple[str, ...] | None = None
    purpose: str | None = None
    param_overrides: Mapping[str, str] | None = None
    debounce_ms: int = DEFAULT_DEBOUNCE_MS
    poll_ms: int = DEFAULT_POLL_MS


def resolve_watch_roots(
    *,
    project: Path,
    home: Path,
    from_harness: str | None = None,
    harness: str | tuple[str, ...] | None = None,
    extra_roots: tuple[Path, ...] = (),
) -> tuple[Path, ...]:
    """Directories whose skill markdown should be polled.

    Prefer explicit ``--from-dir`` roots. Otherwise watch the project skill
    directory for the resolved source harness (same discovery init uses).
    """
    project = project.resolve()
    home = home.expanduser()
    roots: list[Path] = []

    for root in extra_roots:
        resolved = root.expanduser().resolve()
        if resolved not in roots:
            roots.append(resolved)

    source = _resolve_source(
        from_harness=from_harness,
        harness=harness,
        home=home,
        project=project,
        extra_roots=extra_roots,
    )
    if source in HARNESSES:
        skill_rel = HARNESSES[source].project_dirs.get("skill")
        if skill_rel:
            project_skills = (project / skill_rel).resolve()
            if project_skills not in roots:
                roots.append(project_skills)

    if not roots:
        raise CinchError(
            "Nothing to watch. Pass --from-dir or create a project skills directory "
            f"(e.g. {project / '.claude/skills'})."
        )
    return tuple(roots)


def scan_skill_mtimes(roots: Sequence[Path]) -> dict[str, float]:
    """Map absolute skill-markdown paths to mtime_ns for polling."""
    snapshot: dict[str, float] = {}
    for root in roots:
        root = root.expanduser()
        if not root.exists():
            continue
        for path in _iter_skill_markdown(root):
            try:
                snapshot[str(path.resolve())] = float(path.stat().st_mtime_ns)
            except OSError:
                continue
    return snapshot


def diff_snapshots(
    previous: Mapping[str, float],
    current: Mapping[str, float],
) -> list[WatchChange]:
    """Return create/modify/delete events between two mtime snapshots."""
    changes: list[WatchChange] = []
    prev_keys = set(previous)
    curr_keys = set(current)
    for path in sorted(curr_keys - prev_keys):
        changes.append(WatchChange(path=path, kind="created"))
    for path in sorted(prev_keys - curr_keys):
        changes.append(WatchChange(path=path, kind="deleted"))
    for path in sorted(prev_keys & curr_keys):
        if previous[path] != current[path]:
            changes.append(WatchChange(path=path, kind="modified"))
    return changes


def rebuild(config: WatchConfig) -> dict:
    """Re-resolve and apply the wire plan, overwriting existing target files."""
    plan = resolve_plan(
        harness=config.harness,
        from_harness=config.from_harness,
        project=config.project,
        home=config.home,
        purpose=config.purpose,
        skills=config.skills,
        agents=config.agents,
        hooks=config.hooks,
        commands=config.commands,
        extra_roots=config.extra_roots,
        dry_run=False,
        param_overrides=config.param_overrides,
        interactive_params=False,
    )
    return apply_plan(plan, overwrite=True)


def watch_once(
    config: WatchConfig,
    *,
    roots: Sequence[Path] | None = None,
) -> tuple[dict[str, float], dict]:
    """Scan once and rebuild. Returns (snapshot, apply result)."""
    watch_roots = (
        tuple(roots)
        if roots is not None
        else resolve_watch_roots(
            project=config.project,
            home=config.home,
            from_harness=config.from_harness,
            harness=config.harness,
            extra_roots=config.extra_roots,
        )
    )
    snapshot = scan_skill_mtimes(watch_roots)
    result = rebuild(config)
    # Refresh after writes so same-harness targets do not loop.
    snapshot = scan_skill_mtimes(watch_roots)
    return snapshot, result


def run_watch(
    config: WatchConfig,
    *,
    once: bool = False,
    on_rebuild: Callable[[list[WatchChange], dict, float], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
    on_start: Callable[[tuple[Path, ...]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    """Poll skill roots and rebuild after a quiet debounce window.

    Exits 0 on ``once``, stop signal, or KeyboardInterrupt.
    """
    roots = resolve_watch_roots(
        project=config.project,
        home=config.home,
        from_harness=config.from_harness,
        harness=config.harness,
        extra_roots=config.extra_roots,
    )
    if on_start:
        on_start(roots)

    if once:
        _, result = watch_once(config, roots=roots)
        if on_rebuild:
            on_rebuild([], result, 0.0)
        return 0

    snapshot = scan_skill_mtimes(roots)
    pending: list[WatchChange] = []
    quiet_since: float | None = None
    debounce_s = max(config.debounce_ms, 0) / 1000.0
    poll_s = max(config.poll_ms, 1) / 1000.0

    try:
        while True:
            if should_stop and should_stop():
                return 0
            sleep(poll_s)
            current = scan_skill_mtimes(roots)
            changes = diff_snapshots(snapshot, current)
            if changes:
                snapshot = current
                pending.extend(changes)
                quiet_since = time.monotonic()
                continue
            if pending and quiet_since is not None:
                if time.monotonic() - quiet_since < debounce_s:
                    continue
                batch = list(pending)
                pending.clear()
                quiet_since = None
                started = time.perf_counter()
                try:
                    result = rebuild(config)
                    # Absorb our own writes into the baseline snapshot.
                    snapshot = scan_skill_mtimes(roots)
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    if on_rebuild:
                        on_rebuild(batch, result, elapsed_ms)
                except Exception as exc:
                    snapshot = scan_skill_mtimes(roots)
                    if on_error:
                        on_error(exc)
                    else:
                        raise
    except KeyboardInterrupt:
        return 0


def _resolve_source(
    *,
    from_harness: str | None,
    harness: str | tuple[str, ...] | None,
    home: Path,
    project: Path,
    extra_roots: tuple[Path, ...],
) -> str:
    """Best-effort source harness id for choosing a project skills directory."""
    if from_harness is not None:
        return from_harness
    if extra_roots:
        return "claude"
    # Mirror resolve_plan defaults without raising on multi-detect.
    from cinch.detect import detect_harnesses
    from cinch.plan import parse_csv

    targets = parse_csv(harness) or ()
    detected = detect_harnesses(home=home, project=project)
    present = [row.id for row in detected if row.present]
    if len(targets) == 1 and targets[0] in HARNESSES:
        if not present or targets[0] in present:
            return targets[0]
    if len(present) == 1:
        return present[0]
    if present:
        return present[0]
    return targets[0] if len(targets) == 1 else "claude"


def _iter_skill_markdown(root: Path) -> list[Path]:
    """Yield markdown files that inventory-style skill discovery cares about."""
    found: list[Path] = []
    if root.is_file():
        if _is_watched_markdown(root):
            found.append(root)
        return found

    if not root.is_dir():
        return found

    direct = root / "SKILL.md"
    if direct.is_file():
        found.append(direct)
        return found

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if _hidden(relative):
            continue
        if _is_watched_markdown(path):
            found.append(path)
    return found


def _is_watched_markdown(path: Path) -> bool:
    name = path.name
    if name == "SKILL.md":
        return True
    return path.suffix.lower() == ".md" and name.lower() != "readme.md"


def _hidden(path: Path) -> bool:
    return any(part.startswith(".") and part not in {".", ".."} for part in path.parts)
