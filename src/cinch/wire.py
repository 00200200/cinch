"""Write translated harness items into the project layout with verified outcomes."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Literal

from cinch.plan import Plan, PlannedFile

Outcome = Literal["written", "unchanged", "exists", "shared", "skipped"]


def apply_plan(plan: Plan) -> dict:
    results: list[dict] = []
    copied_list: list[str] = []
    seen: set[str] = set()
    # Paths written earlier in this apply pass → first target that wrote them.
    # Cursor and Codex both land on `.agents/skills/…`, so the second target
    # should report "shared" (covered by the first write) instead of "exists".
    written_this_pass: dict[str, str] = {}

    if not plan.dry_run:
        for file in plan.files:
            outcome = _apply_file(file, plan.project, written_this_pass)
            entry: dict = {
                "kind": file.kind,
                "name": file.name,
                "target": file.target,
                "path": file.relpath,
                "outcome": outcome,
            }
            if outcome == "shared" and file.relpath in written_this_pass:
                entry["shared_with"] = written_this_pass[file.relpath]
            results.append(entry)
            if outcome in ("written", "unchanged", "shared"):
                key = f"{file.kind}:{file.name}"
                if key not in seen:
                    seen.add(key)
                    copied_list.append(key)

        manifest = {
            "harness": plan.harness,
            "source_harness": plan.source_harness,
            "targets": list(plan.targets),
            "title": plan.title,
            "toolchain": plan.toolchain,
            "copied": copied_list,
            "results": results,
            "skipped": [
                {
                    "kind": s.kind,
                    "name": s.name,
                    "target": s.target,
                    "reason": s.reason,
                }
                for s in plan.skipped
            ],
        }
        path = plan.project / ".cinch.json"
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    else:
        for file in plan.files:
            key = f"{file.kind}:{file.name}"
            if key not in seen:
                seen.add(key)
                copied_list.append(key)
            if file.relpath in written_this_pass:
                results.append(
                    {
                        "kind": file.kind,
                        "name": file.name,
                        "target": file.target,
                        "path": file.relpath,
                        "outcome": "shared",
                        "shared_with": written_this_pass[file.relpath],
                    }
                )
            else:
                written_this_pass[file.relpath] = file.target
                results.append(
                    {
                        "kind": file.kind,
                        "name": file.name,
                        "target": file.target,
                        "path": file.relpath,
                        "outcome": "written",
                    }
                )

    return {
        "harness": plan.harness,
        "source_harness": plan.source_harness,
        "targets": list(plan.targets),
        "title": plan.title,
        "toolchain": plan.toolchain,
        "dry_run": plan.dry_run,
        "copied": copied_list,
        "results": results,
        "skipped": [f"{s.kind}:{s.name} ({s.reason})" for s in plan.skipped],
        "project": str(plan.project),
    }


def _apply_file(
    file: PlannedFile,
    project: Path,
    written_this_pass: dict[str, str],
) -> Outcome:
    dest = project / file.relpath

    if file.support_source and file.support_dest:
        support_dir = project / file.support_dest
        if not support_dir.exists():
            shutil.copytree(file.support_source, support_dir)

    if file.mode == "merge":
        outcome = _merge_file(dest, file.content)
        if outcome == "written":
            written_this_pass[file.relpath] = file.target
        return outcome

    if dest.exists():
        if file.relpath in written_this_pass:
            return "shared"
        return "exists"

    dest.parent.mkdir(parents=True, exist_ok=True)

    if file.content:
        dest.write_text(file.content, encoding="utf-8")
        written_this_pass[file.relpath] = file.target
        return "written"

    if file.source:
        _copy(file.source, dest)
        written_this_pass[file.relpath] = file.target
        return "written"

    dest.write_text("", encoding="utf-8")
    written_this_pass[file.relpath] = file.target
    return "written"


def _merge_file(dest: Path, addition: str) -> Outcome:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(addition, encoding="utf-8")
        return "written"

    existing_text = dest.read_text(encoding="utf-8")
    addition_lines = [line.strip() for line in addition.splitlines() if line.strip()]

    # Check if lines already exist
    all_present = True
    for line in addition_lines:
        if line != "read:" and line not in existing_text:
            all_present = False
            break

    if all_present:
        return "unchanged"

    if "read:" in existing_text and addition.startswith("read:\n"):
        entries = addition.replace("read:\n", "", 1)
        new_text = existing_text.rstrip() + "\n" + entries.lstrip("\n")
    else:
        new_text = existing_text.rstrip() + "\n" + addition

    dest.write_text(new_text, encoding="utf-8")
    return "written"


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
