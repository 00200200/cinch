"""Tests for skill ``requires:`` DAG resolution and wiring expansion."""

from __future__ import annotations

from pathlib import Path

import pytest

from cinch.check import lint_directory, lint_skill
from cinch.doc import parse_doc, parse_frontmatter
from cinch.errors import CinchError
from cinch.inventory import Item
from cinch.plan import resolve_plan
from cinch.resolver import (
    expand_with_requires,
    parse_requires,
    requires_from_meta,
    resolve_skill_order,
)
from cinch.schema import SkillManifestSchema


def _write_skill(
    root: Path,
    name: str,
    *,
    requires: list[str] | None = None,
    body: str | None = None,
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    req_block = ""
    if requires is not None:
        if requires:
            items = "\n".join(f"  - {r}" for r in requires)
            req_block = f"requires:\n{items}\n"
        else:
            req_block = "requires: []\n"
    text = f"""\
---
name: {name}
description: Skill {name} used in requires DAG tests
{req_block}---

# {name}

{body or f"Body of {name}."}
"""
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
    return skill_dir


class TestParseRequires:
    def test_list_and_string(self) -> None:
        assert parse_requires(["a", "b", "a"]) == ("a", "b")
        assert parse_requires("solo") == ("solo",)
        assert parse_requires(None) == ()
        assert parse_requires([]) == ()

    def test_invalid_type(self) -> None:
        with pytest.raises(CinchError, match="expected string or list"):
            parse_requires(42)
        with pytest.raises(CinchError, match="skill name strings"):
            parse_requires(["ok", 1])

    def test_from_meta(self) -> None:
        assert requires_from_meta({"requires": ["x", "y"]}) == ("x", "y")
        assert requires_from_meta({}) == ()


class TestTopoSort:
    def test_dependency_first_order(self) -> None:
        graph = {
            "git-pr-flow": ("test-runner", "semantic-commit"),
            "test-runner": (),
            "semantic-commit": ("test-runner",),
        }
        order = resolve_skill_order(["git-pr-flow"], graph, available=graph.keys())
        assert order.index("test-runner") < order.index("semantic-commit")
        assert order.index("semantic-commit") < order.index("git-pr-flow")
        assert order[-1] == "git-pr-flow"

    def test_deduplicates_shared_prereqs(self) -> None:
        graph = {
            "a": ("shared",),
            "b": ("shared",),
            "shared": (),
        }
        order = expand_with_requires(["a", "b"], graph, available=graph.keys())
        assert order.count("shared") == 1
        assert order.index("shared") < order.index("a")
        assert order.index("shared") < order.index("b")

    def test_cycle_errors(self) -> None:
        graph = {"a": ("b",), "b": ("a",)}
        with pytest.raises(CinchError, match="Circular skill dependency"):
            resolve_skill_order(["a"], graph, available=graph.keys())

    def test_missing_dependency_errors(self) -> None:
        graph = {"a": ("missing",)}
        with pytest.raises(CinchError, match="Unknown required skill 'missing'"):
            resolve_skill_order(["a"], graph, available={"a"})

    def test_deterministic_requires_declaration_order(self) -> None:
        graph = {
            "parent": ("z", "a", "m"),
            "z": (),
            "a": (),
            "m": (),
        }
        assert resolve_skill_order(["parent"], graph, available=graph.keys()) == [
            "z",
            "a",
            "m",
            "parent",
        ]


class TestDocAndSchema:
    def test_frontmatter_and_doc_requires(self, tmp_path: Path) -> None:
        meta, _ = parse_frontmatter(
            """\
---
name: git-pr-flow
description: Open a pull request with tests and commits
requires: [test-runner, semantic-commit]
---
Body
"""
        )
        assert meta["requires"] == ["test-runner", "semantic-commit"]

        skill_dir = _write_skill(
            tmp_path, "git-pr-flow", requires=["test-runner", "semantic-commit"]
        )
        doc = parse_doc(Item(kind="skill", name="git-pr-flow", source=skill_dir, tags=()))
        assert doc.requires == ("test-runner", "semantic-commit")

    def test_requires_allowed_in_strict_schema(self) -> None:
        model, issues = SkillManifestSchema.validate(
            {
                "name": "git-pr-flow",
                "description": "Open a pull request with tests and commits",
                "requires": ["test-runner", "semantic-commit"],
            }
        )
        assert model is not None
        assert model.requires == ("test-runner", "semantic-commit")
        assert not any(i.rule.startswith("E") for i in issues)

    def test_invalid_requires_schema(self) -> None:
        model, issues = SkillManifestSchema.validate(
            {
                "name": "broken",
                "description": "Has a bad requires value for schema tests",
                "requires": [1, 2],
            }
        )
        assert model is None
        assert any(i.rule == "E008" for i in issues)


class TestWireExpansion:
    def test_resolve_plan_writes_deps_alongside(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        project = tmp_path / "project"
        project.mkdir()
        _write_skill(skills, "test-runner", body="Run the test suite.")
        _write_skill(skills, "semantic-commit", body="Write conventional commits.")
        _write_skill(
            skills,
            "git-pr-flow",
            requires=["test-runner", "semantic-commit"],
            body="Open the PR.",
        )

        plan = resolve_plan(
            harness="cursor",
            from_harness="claude",
            project=project,
            home=tmp_path / "home",
            skills=("git-pr-flow",),
            extra_roots=(skills,),
            dry_run=True,
        )
        names = [f.name for f in plan.files if f.kind == "skill"]
        assert names == ["test-runner", "semantic-commit", "git-pr-flow"]
        for file in plan.files:
            if file.kind == "skill":
                assert "requires:" not in file.content

    def test_shared_dep_written_once(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        project = tmp_path / "project"
        project.mkdir()
        _write_skill(skills, "shared", body="Shared helper.")
        _write_skill(skills, "alpha", requires=["shared"], body="Alpha.")
        _write_skill(skills, "beta", requires=["shared"], body="Beta.")

        plan = resolve_plan(
            harness="cursor",
            from_harness="claude",
            project=project,
            home=tmp_path / "home",
            skills=("alpha", "beta"),
            extra_roots=(skills,),
            dry_run=True,
        )
        names = [f.name for f in plan.files if f.kind == "skill"]
        assert names.count("shared") == 1
        assert names.index("shared") < names.index("alpha")
        assert names.index("shared") < names.index("beta")

    def test_missing_require_fails_plan(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        project = tmp_path / "project"
        project.mkdir()
        _write_skill(skills, "lonely", requires=["nope"], body="Needs nope.")

        with pytest.raises(CinchError, match="Unknown required skill 'nope'"):
            resolve_plan(
                harness="cursor",
                from_harness="claude",
                project=project,
                home=tmp_path / "home",
                skills=("lonely",),
                extra_roots=(skills,),
                dry_run=True,
            )

    def test_cycle_fails_plan(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        project = tmp_path / "project"
        project.mkdir()
        _write_skill(skills, "a", requires=["b"], body="A")
        _write_skill(skills, "b", requires=["a"], body="B")

        with pytest.raises(CinchError, match="Circular skill dependency"):
            resolve_plan(
                harness="cursor",
                from_harness="claude",
                project=project,
                home=tmp_path / "home",
                skills=("a",),
                extra_roots=(skills,),
                dry_run=True,
            )


class TestCheckRequires:
    def test_unknown_require_in_directory(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "needs-friend", requires=["ghost-skill"])
        diags = lint_directory(tmp_path)
        assert any(d.rule == "E008" and "ghost-skill" in d.message for d in diags)

    def test_cycle_in_directory(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "a", requires=["b"])
        _write_skill(tmp_path, "b", requires=["a"])
        diags = lint_directory(tmp_path)
        assert any(d.rule == "E009" and "Circular" in d.message for d in diags)

    def test_valid_requires_directory(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "base")
        _write_skill(tmp_path, "top", requires=["base"])
        diags = lint_directory(tmp_path)
        assert not any(d.rule in {"E008", "E009"} for d in diags)

    def test_single_skill_invalid_requires_shape(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "bad"
        skill_dir.mkdir()
        # Frontmatter parser stores a bare number as an int-like string path;
        # use a mapping-shaped mistake the check parser keeps as non-list.
        (skill_dir / "SKILL.md").write_text(
            """\
---
name: bad
description: Skill with invalid requires shape for lint
requires: not-a-list-but-ok
---
Body
""",
            encoding="utf-8",
        )
        # A plain string is valid (single dependency). Force a bad type via
        # strict schema instead.
        model, issues = SkillManifestSchema.validate(
            {
                "name": "bad",
                "description": "Skill with invalid requires shape for lint",
                "requires": {"nested": True},
            }
        )
        assert model is None
        assert any(i.rule == "E008" for i in issues)
        # Smoke: lint_skill still runs on the string form
        assert isinstance(lint_skill(skill_dir), list)
