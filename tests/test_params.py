"""Tests for parameterized skills: schema, overrides, and template substitution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cinch.cli import main
from cinch.doc import parse_doc, parse_frontmatter
from cinch.errors import CinchError
from cinch.inventory import Item
from cinch.params import (
    apply_parameters_to_doc,
    coerce_value,
    parse_param_flags,
    parse_param_specs,
    render_template,
    resolve_param_values,
)
from cinch.plan import resolve_plan
from cinch.schema import SkillManifestSchema


def _write_param_skill(root: Path, name: str = "coverage-gate") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""\
---
name: {name}
description: Enforce minimum coverage of {{{{ min_coverage }}}} using $framework
parameters:
  min_coverage: {{ type: int, default: 80, help: "Minimum test coverage %" }}
  framework: {{ type: string, choices: [pytest, jest, vitest] }}
---

# {name}

Require {{{{ min_coverage }}}}% coverage with ${{framework}}.
""",
        encoding="utf-8",
    )
    return skill_dir


class TestFrontmatterParameters:
    def test_parses_inline_parameter_maps(self) -> None:
        meta, body = parse_frontmatter(
            """\
---
name: demo
description: A parameterized demo skill
parameters:
  min_coverage: { type: int, default: 80, help: "Minimum test coverage %" }
  framework: { type: string, choices: [pytest, jest, vitest] }
---
Body {{ min_coverage }}
"""
        )
        assert meta["name"] == "demo"
        assert isinstance(meta["parameters"], dict)
        assert meta["parameters"]["min_coverage"]["type"] == "int"
        assert meta["parameters"]["min_coverage"]["default"] == 80
        assert meta["parameters"]["framework"]["choices"] == ["pytest", "jest", "vitest"]
        assert "{{ min_coverage }}" in body

    def test_parses_nested_block_parameters(self) -> None:
        meta, _ = parse_frontmatter(
            """\
---
name: demo
description: Nested parameter block form
parameters:
  strict:
    type: boolean
    default: true
    help: Fail on warnings
---
"""
        )
        assert meta["parameters"]["strict"]["type"] == "boolean"
        assert meta["parameters"]["strict"]["default"] is True


class TestParamSchema:
    def test_valid_specs(self) -> None:
        specs = parse_param_specs(
            {
                "min_coverage": {"type": "int", "default": 80},
                "framework": {"type": "string", "choices": ["pytest", "jest"]},
                "verbose": {"type": "boolean", "default": False},
                "mode": {"type": "choice", "choices": ["fast", "full"], "default": "fast"},
            }
        )
        assert specs["min_coverage"].type == "int"
        assert specs["framework"].type == "choice"
        assert specs["verbose"].default is False
        assert specs["mode"].choices == ("fast", "full")

    def test_unknown_type_errors(self) -> None:
        with pytest.raises(CinchError, match="unknown type"):
            parse_param_specs({"x": {"type": "float"}})

    def test_invalid_default_errors(self) -> None:
        with pytest.raises(CinchError, match="Invalid default"):
            parse_param_specs({"n": {"type": "int", "default": "abc"}})

    def test_choice_requires_choices(self) -> None:
        with pytest.raises(CinchError, match="requires choices"):
            parse_param_specs({"mode": {"type": "choice"}})

    def test_bool_alias(self) -> None:
        specs = parse_param_specs({"flag": {"type": "bool", "default": True}})
        assert specs["flag"].type == "boolean"

    def test_parameters_allowed_in_strict_schema(self) -> None:
        model, issues = SkillManifestSchema.validate(
            {
                "name": "coverage-gate",
                "description": "A skill with typed parameters declared",
                "parameters": {
                    "min_coverage": {"type": "int", "default": 80},
                },
            }
        )
        assert model is not None
        assert not any(i.rule.startswith("E") for i in issues)


class TestCoerceAndRender:
    def test_coerce_boolean_strings(self) -> None:
        from cinch.params import ParamSpec

        spec = ParamSpec(name="v", type="boolean")
        assert coerce_value(spec, "yes") is True
        assert coerce_value(spec, "off") is False

    def test_render_only_declared_placeholders(self) -> None:
        out = render_template(
            "cover {{ min_coverage }} with $framework and leave {{ other }} and $unknown",
            {"min_coverage": 90, "framework": "pytest"},
        )
        assert out == "cover 90 with pytest and leave {{ other }} and $unknown"


class TestResolveOverrides:
    def test_cli_overrides_env_overrides_default(self) -> None:
        specs = parse_param_specs(
            {
                "min_coverage": {"type": "int", "default": 80},
                "framework": {"type": "choice", "choices": ["pytest", "jest"], "default": "pytest"},
            }
        )
        values = resolve_param_values(
            specs,
            cli_overrides={"min_coverage": "95"},
            environ={"CINCH_PARAM_MIN_COVERAGE": "70", "CINCH_PARAM_FRAMEWORK": "jest"},
            interactive=False,
        )
        assert values == {"min_coverage": 95, "framework": "jest"}

    def test_missing_required_noninteractive(self) -> None:
        specs = parse_param_specs({"framework": {"type": "choice", "choices": ["pytest", "jest"]}})
        with pytest.raises(CinchError, match="Missing required parameter 'framework'"):
            resolve_param_values(specs, interactive=False)

    def test_parse_param_flags(self) -> None:
        assert parse_param_flags(["min_coverage=90", "framework=pytest"]) == {
            "min_coverage": "90",
            "framework": "pytest",
        }
        with pytest.raises(CinchError, match="KEY=VALUE"):
            parse_param_flags(["nope"])


class TestApplyAndWire:
    def test_apply_substitutes_and_strips_parameters(self, tmp_path: Path) -> None:
        skill_dir = _write_param_skill(tmp_path)
        item = Item(kind="skill", name="coverage-gate", source=skill_dir, tags=())
        doc = parse_doc(item)
        assert "parameters" in doc.extra_meta

        applied = apply_parameters_to_doc(
            doc,
            cli_overrides={"framework": "vitest"},
            interactive=False,
        )
        assert "parameters" not in applied.extra_meta
        assert "80" in applied.description
        assert "vitest" in applied.description
        assert "80% coverage with vitest" in applied.body

    def test_resolve_plan_wires_substituted_body(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        project = tmp_path / "project"
        project.mkdir()
        _write_param_skill(skills)

        plan = resolve_plan(
            harness="cursor",
            from_harness="claude",
            project=project,
            home=tmp_path / "home",
            skills=("coverage-gate",),
            extra_roots=(skills,),
            dry_run=True,
            param_overrides={"framework": "pytest", "min_coverage": "90"},
            interactive_params=False,
        )
        skill_files = [f for f in plan.files if f.kind == "skill"]
        assert skill_files
        assert "90% coverage with pytest" in skill_files[0].content
        assert "parameters:" not in skill_files[0].content

    def test_init_cli_param_flag(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        project = tmp_path / "project"
        _write_param_skill(skills)
        code = main(
            [
                "init",
                str(project),
                "--from-harness",
                "claude",
                "--harness",
                "cursor",
                "--skills",
                "coverage-gate",
                "--from",
                str(skills),
                "--yes",
                "--param",
                "framework=jest",
                "--param",
                "min_coverage=85",
            ]
        )
        assert code == 0
        written = (project / ".agents/skills/coverage-gate/SKILL.md").read_text(encoding="utf-8")
        assert "85% coverage with jest" in written
        assert "parameters:" not in written

    def test_init_missing_required_exits_nonzero(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        project = tmp_path / "project"
        skill_dir = skills / "needs-url"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            """\
---
name: needs-url
description: Deploy helper that needs a staging URL parameter
parameters:
  staging_url: { type: string, help: "Staging base URL" }
---

Deploy to {{ staging_url }}.
""",
            encoding="utf-8",
        )
        code = main(
            [
                "init",
                str(project),
                "--from-harness",
                "claude",
                "--harness",
                "cursor",
                "--skills",
                "needs-url",
                "--from",
                str(skills),
                "--yes",
            ]
        )
        assert code == 2

    def test_interactive_prompt_when_required(self, tmp_path: Path) -> None:
        skill_dir = _write_param_skill(tmp_path)
        # Drop default on framework by rewriting
        (skill_dir / "SKILL.md").write_text(
            """\
---
name: coverage-gate
description: Coverage skill
parameters:
  framework: { type: string, choices: [pytest, jest] }
---

Use $framework.
""",
            encoding="utf-8",
        )
        item = Item(kind="skill", name="coverage-gate", source=skill_dir, tags=())
        doc = parse_doc(item)

        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("questionary.select") as mock_select,
        ):
            mock_select.return_value.ask.return_value = "jest"
            applied = apply_parameters_to_doc(doc, interactive=True)

        assert "Use jest." in applied.body
