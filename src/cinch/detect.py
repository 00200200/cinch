"""Detect which harnesses exist on this machine."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cinch.catalog import HARNESS_ORDER, HARNESSES, HarnessSpec


@dataclass(frozen=True)
class HarnessPresence:
    id: str
    title: str
    present: bool
    reasons: tuple[str, ...]


def detect_toolchain(project: Path) -> str:
    project = project.resolve()
    if (project / "Cargo.toml").is_file():
        return "cargo"
    if (project / "go.mod").is_file():
        return "go"
    if (project / "package.json").is_file():
        if (project / "pnpm-lock.yaml").is_file():
            return "pnpm"
        if (project / "yarn.lock").is_file():
            return "yarn"
        if (project / "bun.lock").is_file() or (project / "bun.lockb").is_file():
            return "bun"
        return "npm"
    if (project / "uv.lock").is_file():
        return "uv"
    pyproject = project / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8")
        if (project / "poetry.lock").is_file() or "[tool.poetry]" in text:
            return "poetry"
        if "[tool.uv]" in text:
            return "uv"
        return "pip"
    if (project / "poetry.lock").is_file():
        return "poetry"
    if (project / "requirements.txt").is_file() or (project / "Pipfile").is_file():
        return "pip"
    return "generic"


def path_binaries(path_var: str | None = None) -> set[str]:
    names: set[str] = set()
    for directory in (path_var if path_var is not None else os.environ.get("PATH", "")).split(
        os.pathsep
    ):
        if not directory:
            continue
        root = Path(directory)
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_file() and os.access(entry, os.X_OK):
                    names.add(entry.name)
            except OSError:
                continue
    return names


def detect_harnesses(
    *,
    home: Path,
    binaries: set[str] | None = None,
    project: Path | None = None,
) -> list[HarnessPresence]:
    home = home.expanduser()
    found = binaries if binaries is not None else path_binaries()
    results = []
    for harness_id in HARNESS_ORDER:
        spec = HARNESSES[harness_id]
        results.append(_presence(spec, home=home, binaries=found, project=project))
    return results


def _presence(
    spec: HarnessSpec,
    *,
    home: Path,
    binaries: set[str],
    project: Path | None,
) -> HarnessPresence:
    reasons: list[str] = []
    for binary in spec.binaries:
        if binary in binaries:
            reasons.append(f"binary:{binary}")
    for marker in spec.home_markers:
        if (home / marker).exists():
            reasons.append(f"home:{marker}")
    if project is not None:
        for marker in spec.project_markers:
            if (project / marker).exists():
                reasons.append(f"project:{marker}")
    return HarnessPresence(
        id=spec.id,
        title=spec.title,
        present=bool(reasons),
        reasons=tuple(reasons),
    )
