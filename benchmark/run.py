#!/usr/bin/env python3
"""Standalone benchmark suite measuring Cinch translation latency and throughput.

Generates 10, 50, and 100 synthetic skills and measures:
- Frontmatter parsing throughput (skills/sec) and latency (µs)
- Full translation across all 9 adapters (dialects/sec and latency per skill)
- Plan resolution and wiring throughput (skills/sec and latency per skill)
"""

from __future__ import annotations

import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Add src to sys.path so benchmark runs standalone
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cinch.adapters import ADAPTERS  # noqa: E402
from cinch.doc import Doc, parse_frontmatter  # noqa: E402
from cinch.plan import resolve_plan  # noqa: E402
from cinch.wire import apply_plan  # noqa: E402


def make_synthetic_skill(idx: int) -> str:
    """Generate a realistic synthetic skill with frontmatter, metadata, and markdown body."""
    adapters_list = ", ".join(ADAPTERS.keys())
    return f"""---
name: synthetic-skill-{idx:03d}
description: "Synthetic benchmarking skill number {idx} for measuring throughput across adapters."
globs: ["src/**/*.py", "tests/**/*.py", "docs/**/*.md"]
tags: [benchmark, test, automated, utility]
version: 1.0.0
---
# Synthetic Skill {idx}

## Overview
This is synthetic skill {idx} used to benchmark Cinch performance.
It includes structured markdown content, directives, guidance, and code examples.

## Instructions
1. Always validate inputs before executing actions in the target workspace.
2. Ensure idempotent behavior across all harness environments ({adapters_list}).
3. Maintain translation integrity and preserve comments when transforming skill instructions.

### Scenarios and Edge Cases
- Scenario A: Standard transformation for component {idx}.
- Scenario B: High-throughput batch processing mode.
- Scenario C: Recovery and graceful degradation for missing prerequisites.

```python
def execute_skill_{idx}(context: dict) -> dict:
    \"\"\"Execute synthetic skill action {idx}.\"\"\"
    result = {{"skill_id": {idx}, "status": "success", "length": len(context)}}
    return result
```
"""


def benchmark_frontmatter(skills: list[str]) -> tuple[float, float]:
    """Measure frontmatter parsing throughput (skills/s) and latency (µs/skill)."""
    n = len(skills)
    # Warmup
    for s in skills[:5]:
        parse_frontmatter(s)

    # Dynamic repetitions to target >= 0.15s duration
    target_duration = 0.15
    t0 = time.perf_counter()
    for s in skills:
        parse_frontmatter(s)
    single_pass = max(time.perf_counter() - t0, 1e-6)
    reps = max(2, int(target_duration / single_pass))

    t0 = time.perf_counter()
    for _ in range(reps):
        for s in skills:
            parse_frontmatter(s)
    total_time = time.perf_counter() - t0

    total_skills = n * reps
    throughput = total_skills / total_time
    latency_us = (total_time / total_skills) * 1_000_000
    return throughput, latency_us


def build_docs(skills: list[str]) -> list[Doc]:
    """Convert raw skill text into canonical Doc instances."""
    docs = []
    for s in skills:
        meta, body = parse_frontmatter(s)
        paths = tuple(meta.get("globs") or ())
        docs.append(
            Doc(
                kind="skill",
                name=meta.get("name", "skill"),
                description=meta.get("description", ""),
                body=body,
                paths=paths,
                extra_meta=meta,
            )
        )
    return docs


def benchmark_translation(docs: list[Doc]) -> tuple[float, float]:
    """Measure full translation across all 9 adapters (dialects/s and latency per skill)."""
    adapters = list(ADAPTERS.values())
    n = len(docs)
    num_adapters = len(adapters)

    # Warmup
    for d in docs[:3]:
        for a in adapters:
            a.render(d)

    target_duration = 0.15
    t0 = time.perf_counter()
    for d in docs:
        for a in adapters:
            a.render(d)
    single_pass = max(time.perf_counter() - t0, 1e-6)
    reps = max(2, int(target_duration / single_pass))

    t0 = time.perf_counter()
    for _ in range(reps):
        for d in docs:
            for a in adapters:
                a.render(d)
    total_time = time.perf_counter() - t0

    total_dialects = n * num_adapters * reps
    dialects_per_sec = total_dialects / total_time
    latency_ms_per_skill = (total_time / (n * reps)) * 1_000
    return dialects_per_sec, latency_ms_per_skill


def benchmark_plan_and_wire(skills: list[str]) -> tuple[float, float]:
    """Measure plan resolution and wiring throughput (skills/s and latency ms/skill)."""
    n = len(skills)
    temp_dir = Path(tempfile.mkdtemp(prefix="cinch_bench_"))
    try:
        home = temp_dir / "home"
        for i, s in enumerate(skills):
            skill_dir = home / ".claude" / "skills" / f"synthetic-skill-{i:03d}"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(s, encoding="utf-8")

        target_harnesses = tuple(ADAPTERS.keys())

        # Warmup
        p0 = temp_dir / "proj_warmup"
        plan0 = resolve_plan(
            harness=target_harnesses,
            from_harness="claude",
            project=p0,
            home=home,
        )
        apply_plan(plan0)

        reps = 3 if n <= 50 else 2
        total_time = 0.0
        for r in range(reps):
            proj = temp_dir / f"proj_{r}"
            proj.mkdir(parents=True, exist_ok=True)

            t0 = time.perf_counter()
            plan = resolve_plan(
                harness=target_harnesses,
                from_harness="claude",
                project=proj,
                home=home,
            )
            apply_plan(plan)
            total_time += time.perf_counter() - t0

        total_skills = n * reps
        throughput = total_skills / total_time
        latency_ms_per_skill = (total_time / total_skills) * 1_000
        return throughput, latency_ms_per_skill
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_benchmark() -> None:
    batch_sizes = [10, 50, 100]
    results = []

    print("Running Cinch translation benchmark suite...")
    for size in batch_sizes:
        print(f"  Generating and benchmarking {size} synthetic skills...")
        raw_skills = [make_synthetic_skill(i) for i in range(size)]
        docs = build_docs(raw_skills)

        fm_tp, fm_lat = benchmark_frontmatter(raw_skills)
        tr_tp, tr_lat = benchmark_translation(docs)
        pw_tp, pw_lat = benchmark_plan_and_wire(raw_skills)

        results.append(
            {
                "size": size,
                "fm_tp": fm_tp,
                "fm_lat": fm_lat,
                "tr_tp": tr_tp,
                "tr_lat": tr_lat,
                "pw_tp": pw_tp,
                "pw_lat": pw_lat,
            }
        )

    print("\n")
    print("# Cinch Translation Benchmark")
    print()
    print("### Environment")
    print(f"- **Python:** {platform.python_version()} ({platform.python_implementation()})")
    print(f"- **System:** {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"- **Adapters Tested ({len(ADAPTERS)}):** {', '.join(ADAPTERS.keys())}")
    print()
    print("### Results")
    print()
    print(
        "| Batch Size | FM Parsing Throughput | FM Parse Latency | "
        "Translation Throughput | Translation Latency (9 dialects) | "
        "Plan & Wire Throughput | Plan & Wire Latency |"
    )
    print(
        "|:-----------|----------------------:|-----------------:|"
        "-----------------------:|----------------------------------:|"
        "-----------------------:|--------------------:|"
    )

    for r in results:
        size_label = f"{r['size']} skills"
        fm_tp_str = f"{r['fm_tp']:,.0f} skills/s"
        fm_lat_str = f"{r['fm_lat']:.2f} µs"
        tr_tp_str = f"{r['tr_tp']:,.0f} dialects/s"
        tr_lat_str = f"{r['tr_lat']:.2f} ms"
        pw_tp_str = f"{r['pw_tp']:,.0f} skills/s"
        pw_lat_str = f"{r['pw_lat']:.2f} ms"

        print(
            f"| {size_label:<10} | {fm_tp_str:>21} | {fm_lat_str:>16} | "
            f"{tr_tp_str:>22} | {tr_lat_str:>32} | "
            f"{pw_tp_str:>22} | {pw_lat_str:>19} |"
        )
    print()


def main() -> None:
    run_benchmark()


if __name__ == "__main__":
    main()
