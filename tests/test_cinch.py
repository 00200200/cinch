from __future__ import annotations

import json
from pathlib import Path

import pytest

from cinch.cli import main
from cinch.detect import detect_harnesses, detect_toolchain
from cinch.inventory import collect_inventory
from cinch.plan import CinchError, resolve_plan
from cinch.wire import apply_plan


def write(path: Path, content: str = "ok\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def skill(root: Path, name: str, body: str = "Use this skill.\n") -> Path:
    path = root / name / "SKILL.md"
    write(
        path,
        f'---\nname: "{name}"\ndescription: "A {name} skill"\n---\n\n{body}',
    )
    return path.parent


class TestToolchain:
    def test_detects_uv_from_lockfile(self, tmp_path: Path) -> None:
        write(tmp_path / "pyproject.toml", "[project]\nname = 'demo'\n")
        write(tmp_path / "uv.lock", "# lock\n")
        assert detect_toolchain(tmp_path) == "uv"

    def test_detects_poetry(self, tmp_path: Path) -> None:
        write(tmp_path / "pyproject.toml", "[tool.poetry]\nname = 'demo'\n")
        write(tmp_path / "poetry.lock", "# lock\n")
        assert detect_toolchain(tmp_path) == "poetry"

    def test_detects_pnpm_over_npm(self, tmp_path: Path) -> None:
        write(tmp_path / "package.json", '{"name":"demo"}\n')
        write(tmp_path / "pnpm-lock.yaml", "lockfileVersion: 9\n")
        assert detect_toolchain(tmp_path) == "pnpm"

    def test_detects_yarn(self, tmp_path: Path) -> None:
        write(tmp_path / "package.json", '{"name":"demo"}\n')
        write(tmp_path / "yarn.lock", "# yarn\n")
        assert detect_toolchain(tmp_path) == "yarn"

    def test_detects_bun(self, tmp_path: Path) -> None:
        write(tmp_path / "package.json", '{"name":"demo"}\n')
        write(tmp_path / "bun.lock", "{}\n")
        assert detect_toolchain(tmp_path) == "bun"

    def test_detects_npm(self, tmp_path: Path) -> None:
        write(tmp_path / "package.json", '{"name":"demo"}\n')
        assert detect_toolchain(tmp_path) == "npm"

    def test_detects_cargo(self, tmp_path: Path) -> None:
        write(tmp_path / "Cargo.toml", "[package]\nname = 'demo'\n")
        assert detect_toolchain(tmp_path) == "cargo"

    def test_detects_go(self, tmp_path: Path) -> None:
        write(tmp_path / "go.mod", "module example.com/demo\n")
        assert detect_toolchain(tmp_path) == "go"

    def test_detects_pip_from_requirements(self, tmp_path: Path) -> None:
        write(tmp_path / "requirements.txt", "rich\n")
        assert detect_toolchain(tmp_path) == "pip"

    def test_generic_docs_path_when_empty(self, tmp_path: Path) -> None:
        assert detect_toolchain(tmp_path) == "generic"


class TestHarnessPresence:
    def test_detects_claude_from_binary_and_home(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        found = {item.id: item for item in detect_harnesses(home=home, binaries={"claude"})}
        assert found["claude"].present
        assert found["cursor"].present is False
        assert found["codex"].title == "Codex"

    def test_detects_cursor_from_home_without_binary(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        (home / ".cursor").mkdir(parents=True)
        found = {item.id: item for item in detect_harnesses(home=home, binaries=set())}
        assert found["cursor"].present

    def test_supported_harness_ids_are_real_products(self, tmp_path: Path) -> None:
        ids = [item.id for item in detect_harnesses(home=tmp_path, binaries=set())]
        assert ids == [
            "claude",
            "cursor",
            "codex",
            "grok",
            "opencode",
            "continue",
            "aider",
            "windsurf",
            "cline",
            "gemini",
            "copilot",
        ]
        titles = {item.id: item.title for item in detect_harnesses(home=tmp_path, binaries=set())}
        assert "OpenAI" not in titles["codex"]
        assert titles["codex"] == "Codex"
        assert titles["claude"] == "Claude Code"


class TestInventory:
    def test_lists_what_claude_actually_has(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        skill(home / ".claude" / "skills", "humanizer")
        write(home / ".claude" / "agents" / "reviewer.md", "# reviewer\n")
        write(home / ".claude" / "commands" / "ship.md", "# ship\n")
        write(home / ".claude" / "hooks" / "format.sh", "#!/bin/sh\n")
        write(home / ".claude" / "settings.json", '{"mcpServers": {"docs": {}}}\n')
        items = collect_inventory(harness="claude", home=home, project=tmp_path / "proj")
        kinds = {(item.kind, item.name) for item in items}
        assert ("skill", "humanizer") in kinds
        assert ("agent", "reviewer") in kinds
        assert ("command", "ship") in kinds
        assert ("hook", "format.sh") in kinds
        assert ("mcp", "docs") in kinds

    def test_codex_skips_system_skills(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        skill(home / ".codex" / "skills", "humanizer")
        skill(home / ".codex" / "skills" / ".system", "skill-creator")
        names = {
            item.name
            for item in collect_inventory(harness="codex", home=home, project=tmp_path / "proj")
            if item.kind == "skill"
        }
        assert names == {"humanizer"}

    def test_purpose_filters_inventory(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        skill(home / ".cursor" / "skills", "mkl-humanize")
        skill(home / ".cursor" / "skills", "mkl-debug-ml-training")
        skill(home / ".cursor" / "skills", "unrelated-web")
        items = collect_inventory(
            harness="cursor",
            home=home,
            project=tmp_path / "proj",
            purpose="ml",
        )
        names = {item.name for item in items if item.kind == "skill"}
        assert names == {"mkl-humanize", "mkl-debug-ml-training"}

    def test_lab_from_path_is_an_extra_source_not_a_vendor_copy(self, tmp_path: Path) -> None:
        lab = tmp_path / "maintainer-skills-lab"
        skill(lab / "skills", "mkl-humanize")
        write(lab / "agents" / "mkl-pr-reviewer.toml", "name = 'mkl-pr-reviewer'\n")
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        items = collect_inventory(
            harness="claude",
            home=home,
            project=tmp_path / "proj",
            extra_roots=(lab,),
        )
        names = {(item.kind, item.name) for item in items}
        assert ("skill", "mkl-humanize") in names
        assert ("agent", "mkl-pr-reviewer") in names


class TestPlanAndWire:
    def test_unknown_harness_is_rejected(self) -> None:
        with pytest.raises(CinchError, match="Unknown harness"):
            resolve_plan(harness="not-a-product")

    def test_init_copies_selected_items_into_project_layout(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        skill(home / ".claude" / "skills", "humanizer", "Humanize drafts.\n")
        write(home / ".claude" / "agents" / "reviewer.md", "Review the diff.\n")
        project = tmp_path / "app"
        project.mkdir()
        write(project / "pyproject.toml", "[project]\nname = 'app'\nversion = '0.0.1'\n")
        original = (project / "pyproject.toml").read_bytes()
        plan = resolve_plan(
            harness="claude",
            project=project,
            home=home,
            skills=("humanizer",),
            agents=("reviewer",),
        )
        result = apply_plan(plan)
        copied = project / ".claude" / "skills" / "humanizer" / "SKILL.md"
        assert copied.read_text(encoding="utf-8").endswith("Humanize drafts.\n")
        assert (project / ".claude" / "agents" / "reviewer.md").read_text(encoding="utf-8") == (
            "Review the diff.\n"
        )
        assert (project / ".cinch.json").is_file()
        assert (project / "pyproject.toml").read_bytes() == original
        assert "skill:humanizer" in result["copied"]

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        skill(home / ".claude" / "skills", "humanizer")
        project = tmp_path / "app"
        project.mkdir()
        plan = resolve_plan(
            harness="claude",
            project=project,
            home=home,
            skills=("humanizer",),
            dry_run=True,
        )
        apply_plan(plan)
        assert not (project / ".claude").exists()
        assert not (project / ".cinch.json").exists()

    def test_missing_selection_is_explicit(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        project = tmp_path / "app"
        project.mkdir()
        with pytest.raises(CinchError, match="not in the claude inventory"):
            resolve_plan(
                harness="claude",
                project=project,
                home=home,
                skills=("nope",),
            )


class TestCliNoninteractive:
    def test_init_noninteractive(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        home = tmp_path / "home"
        skill(home / ".cursor" / "skills", "mkl-humanize")
        write(home / ".cursor" / "hooks.json", '{"hooks": []}\n')
        project = tmp_path / "web"
        project.mkdir()
        write(project / "package.json", '{"name":"web"}\n')
        write(project / "pnpm-lock.yaml", "lockfileVersion: 9\n")
        code = main(
            [
                "init",
                str(project),
                "--harness",
                "cursor",
                "--skills",
                "mkl-humanize",
                "--yes",
                "--home",
                str(home),
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "Universal agents for every harness" in out
        assert "Cursor" in out
        assert "skill:mkl-humanize" in out
        manifest = json.loads((project / ".cinch.json").read_text(encoding="utf-8"))
        assert manifest["harness"] == "cursor"
        assert (project / ".cursor" / "skills" / "mkl-humanize" / "SKILL.md").is_file()
        assert json.loads((project / "package.json").read_text(encoding="utf-8"))["name"] == "web"

    def test_inventory_lists_that_harness(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / "home"
        skill(home / ".claude" / "skills", "humanizer")
        write(home / ".claude" / "agents" / "reviewer.md", "# reviewer\n")
        code = main(["inventory", "--harness", "claude", "--home", str(home)])
        assert code == 0
        out = capsys.readouterr().out
        assert "humanizer" in out
        assert "reviewer" in out
        assert "skill" in out

    def test_help_mentions_wizard_order(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = main(["--help"])
        assert code == 0
        text = capsys.readouterr().out
        assert "Universal agents for every harness" in text
        code = main(["init", "--help"])
        assert code == 0
        text = capsys.readouterr().out
        assert "harness" in text
        assert "skills" in text
        assert "hooks" in text


class TestRecordedDemoStdout:
    """README demo.svg must match real CLI output from a fixed fixture home."""

    @pytest.fixture()
    def demo_home(self, tmp_path: Path) -> Path:
        home = tmp_path / "home"
        skill(home / ".claude" / "skills", "humanizer")
        write(home / ".claude" / "agents" / "reviewer.md", "# reviewer\n")
        write(home / ".claude" / "hooks" / "format.sh", "#!/bin/sh\n")
        write(home / ".claude" / "commands" / "ship.md", "# ship\n")
        return home

    def test_harnesses_header_and_rows(
        self, demo_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(["harnesses", "--home", str(demo_home)])
        assert code == 0
        out = capsys.readouterr().out.splitlines()
        assert out[0] == "cinch  Universal agents for every harness."
        assert out[1] == "id          harness           this machine"
        assert out[2] == "claude      Claude Code       on disk"

    def test_inventory_sorted_by_kind_then_name(
        self, demo_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(["inventory", "--harness", "claude", "--home", str(demo_home)])
        assert code == 0
        out = capsys.readouterr().out.splitlines()
        assert out[0] == "cinch  Claude Code"
        assert out[1] == "kind      name"
        assert out[2:] == [
            "agent     reviewer",
            "command   ship",
            "hook      format.sh",
            "skill     humanizer",
        ]

    def test_init_attached_line(
        self, demo_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "app"
        project.mkdir()
        code = main(
            [
                "init",
                str(project),
                "--harness",
                "claude",
                "--skills",
                "humanizer",
                "--agents",
                "reviewer",
                "--yes",
                "--home",
                str(demo_home),
            ]
        )
        assert code == 0
        out = capsys.readouterr().out.splitlines()
        assert out[0] == "cinch  Universal agents for every harness."
        assert out[1] == "  harness   Claude Code (claude)"
        assert out[2] == "  attached  skill:humanizer, agent:reviewer"

