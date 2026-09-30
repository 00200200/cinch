"""Tests for `cinch watch` stdlib mtime polling and rebuild."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from cinch.cli import main
from cinch.watch import (
    WatchChange,
    WatchConfig,
    diff_snapshots,
    rebuild,
    resolve_watch_roots,
    run_watch,
    scan_skill_mtimes,
    watch_once,
)


def _skill(root: Path, name: str, body: str = "Use this skill.\n") -> Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'---\nname: "{name}"\ndescription: "A {name} skill"\n---\n\n{body}',
        encoding="utf-8",
    )
    return path


class TestScanAndDiff:
    def test_scan_skill_mtimes_finds_nested_skill_md(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        _skill(skills, "alpha")
        _skill(skills, "beta")
        snap = scan_skill_mtimes([skills])
        assert len(snap) == 2
        assert all(path.endswith("SKILL.md") for path in snap)

    def test_diff_snapshots_create_modify_delete(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        a = _skill(skills, "alpha", "v1\n")
        prev = scan_skill_mtimes([skills])

        a.write_text(
            '---\nname: "alpha"\ndescription: "A alpha skill"\n---\n\nv2\n',
            encoding="utf-8",
        )
        b = _skill(skills, "beta")
        mid = scan_skill_mtimes([skills])
        changes = diff_snapshots(prev, mid)
        kinds = {c.kind for c in changes}
        assert "modified" in kinds
        assert "created" in kinds

        b.unlink()
        b.parent.rmdir()
        after = scan_skill_mtimes([skills])
        deleted = diff_snapshots(mid, after)
        assert any(c.kind == "deleted" for c in deleted)


class TestWatchRoots:
    def test_from_dir_is_watched(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        skills.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        roots = resolve_watch_roots(
            project=project,
            home=tmp_path / "home",
            harness="cursor",
            extra_roots=(skills,),
        )
        assert skills.resolve() in roots

    def test_defaults_to_project_skills_dir_even_if_missing(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        roots = resolve_watch_roots(
            project=project,
            home=tmp_path / "home",
            from_harness="claude",
            harness="cursor",
        )
        assert (project / ".claude" / "skills").resolve() in roots


class TestRebuildOverwrite:
    def test_rebuild_updates_existing_target(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        skills = tmp_path / "skills"
        skill_md = _skill(skills, "demo", "version one\n")
        project = tmp_path / "project"
        project.mkdir()

        config = WatchConfig(
            project=project,
            home=home,
            harness="cursor",
            from_harness="claude",
            extra_roots=(skills,),
            skills=("demo",),
        )
        result = rebuild(config)
        assert "skill:demo" in result["copied"]
        target = project / ".agents" / "skills" / "demo" / "SKILL.md"
        assert target.is_file()
        assert "version one" in target.read_text(encoding="utf-8")

        skill_md.write_text(
            '---\nname: "demo"\ndescription: "A demo skill"\n---\n\nversion two\n',
            encoding="utf-8",
        )
        result2 = rebuild(config)
        assert "skill:demo" in result2["copied"]
        assert "version two" in target.read_text(encoding="utf-8")
        outcomes = {row["outcome"] for row in result2["results"]}
        assert "written" in outcomes


class TestWatchOnceAndLoop:
    def test_watch_once_wires_and_returns_snapshot(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        _skill(skills, "demo")
        project = tmp_path / "project"
        project.mkdir()
        config = WatchConfig(
            project=project,
            home=tmp_path / "home",
            harness="copilot",
            extra_roots=(skills,),
            skills=("demo",),
        )
        snapshot, result = watch_once(config)
        assert snapshot
        assert "skill:demo" in result["copied"]
        assert (project / ".github" / "instructions" / "demo.instructions.md").is_file()

    def test_run_watch_once_flag(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        _skill(skills, "demo")
        project = tmp_path / "project"
        project.mkdir()
        config = WatchConfig(
            project=project,
            home=tmp_path / "home",
            harness="cursor",
            extra_roots=(skills,),
        )
        rebuilds: list[dict] = []

        code = run_watch(
            config,
            once=True,
            on_rebuild=lambda changes, result, ms: rebuilds.append(result),
        )
        assert code == 0
        assert len(rebuilds) == 1
        assert (project / ".agents" / "skills" / "demo" / "SKILL.md").is_file()

    def test_run_watch_debounces_then_rebuilds(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        skill_md = _skill(skills, "demo", "before\n")
        project = tmp_path / "project"
        project.mkdir()
        config = WatchConfig(
            project=project,
            home=tmp_path / "home",
            harness="cursor",
            extra_roots=(skills,),
            skills=("demo",),
            debounce_ms=0,
            poll_ms=1,
        )
        # Prime target so rebuild is an overwrite.
        rebuild(config)
        target = project / ".agents" / "skills" / "demo" / "SKILL.md"
        assert "before" in target.read_text(encoding="utf-8")

        ticks = {"n": 0}
        rebuilds: list[list[WatchChange]] = []

        def fake_sleep(_seconds: float) -> None:
            ticks["n"] += 1
            if ticks["n"] == 1:
                skill_md.write_text(
                    '---\nname: "demo"\ndescription: "A demo skill"\n---\n\nafter\n',
                    encoding="utf-8",
                )

        code = run_watch(
            config,
            once=False,
            sleep=fake_sleep,
            should_stop=lambda: ticks["n"] >= 4,
            on_rebuild=lambda changes, result, ms: rebuilds.append(changes),
        )
        assert code == 0
        assert rebuilds
        assert any(c.kind == "modified" for batch in rebuilds for c in batch)
        assert "after" in target.read_text(encoding="utf-8")

    def test_keyboard_interrupt_exits_cleanly(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        skills.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        config = WatchConfig(
            project=project,
            home=tmp_path / "home",
            harness="cursor",
            extra_roots=(skills,),
            poll_ms=1,
            debounce_ms=0,
        )

        def boom(_seconds: float) -> None:
            raise KeyboardInterrupt

        assert run_watch(config, sleep=boom) == 0


class TestWatchCli:
    def test_cli_once(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        skills = tmp_path / "skills"
        _skill(skills, "demo")
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.chdir(project)
        code = main(
            [
                "watch",
                str(project),
                "--from-dir",
                str(skills),
                "--harness",
                "cursor",
                "--skills",
                "demo",
                "--once",
                "--home",
                str(tmp_path / "home"),
            ]
        )
        assert code == 0
        assert (project / ".agents" / "skills" / "demo" / "SKILL.md").is_file()

    def test_cli_requires_harness_noninteractive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        code = main(["watch", str(project), "--home", str(tmp_path / "home")])
        assert code == 2

    def test_cli_rich_once(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        _skill(skills, "demo")
        project = tmp_path / "project"
        project.mkdir()
        with patch("cinch.cli.console", Console(force_terminal=True)):
            code = main(
                [
                    "watch",
                    str(project),
                    "--from-dir",
                    str(skills),
                    "--harness",
                    "cursor",
                    "--once",
                    "--home",
                    str(tmp_path / "home"),
                ]
            )
        assert code == 0
