"""Copy selected harness items into the project layout."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from cinch.plan import Plan


def apply_plan(plan: Plan) -> dict:
    copied: list[str] = []
    if not plan.dry_run:
        for item in plan.copies:
            _copy(item.source, item.destination)
            copied.append(f"{item.kind}:{item.name}")
        manifest = {
            "harness": plan.harness,
            "title": plan.title,
            "toolchain": plan.toolchain,
            "copied": copied,
            "skipped": list(plan.skipped),
        }
        path = plan.project / ".cinch.json"
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    else:
        copied = [f"{item.kind}:{item.name}" for item in plan.copies]
    return {
        "harness": plan.harness,
        "title": plan.title,
        "toolchain": plan.toolchain,
        "dry_run": plan.dry_run,
        "copied": copied,
        "skipped": list(plan.skipped),
        "project": str(plan.project),
    }


def _copy(source: Path, destination: Path) -> None:
    if source.is_dir():
        if destination.exists():
            return
        shutil.copytree(source, destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return
    shutil.copy2(source, destination)
