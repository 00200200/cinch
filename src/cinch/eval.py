"""Automated skill assertion and prompt regression test runner for Cinch."""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from cinch.doc import parse_doc
from cinch.html import discover_skills
from cinch.inventory import Item

try:
    import yaml
except ImportError:
    yaml = None


@dataclass
class AssertionResult:
    rule: str
    expected: Any
    passed: bool
    detail: str = ""


@dataclass
class TestCaseResult:
    __test__ = False

    name: str
    skill_name: str
    passed: bool
    duration_ms: float
    assertions: list[AssertionResult] = field(default_factory=list)
    error: str | None = None


@dataclass
class EvalSuiteResult:
    results: list[TestCaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)


def load_eval_spec(path: Path) -> dict[str, Any]:
    """Parse an eval spec from JSON or YAML file."""
    content = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".yml", ".yaml"):
        if yaml is None:
            raise ValueError(f"PyYAML is required to parse YAML eval spec: {path}")
        data = yaml.safe_load(content)
    elif suffix == ".json":
        data = json.loads(content)
    else:
        # Try JSON first, then YAML
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            if yaml is not None:
                data = yaml.safe_load(content)
            else:
                raise ValueError(f"Unsupported eval file format: {path}") from None

    if not isinstance(data, dict):
        raise ValueError(f"Eval spec must be a dictionary: {path}")
    return data


def find_eval_files(eval_dir: Path, skill_name: str | None = None) -> list[Path]:
    """Discover eval spec files in the given directory."""
    if not eval_dir.is_dir():
        return []
    candidates = []
    for pattern in ("*.eval.json", "*.eval.yml", "*.eval.yaml", "*.eval"):
        candidates.extend(eval_dir.glob(pattern))

    candidates = sorted(set(candidates))
    if not skill_name:
        return candidates

    filtered = []
    for path in candidates:
        stem = path.name.split(".eval")[0]
        if stem == skill_name:
            filtered.append(path)
            continue
        try:
            data = load_eval_spec(path)
            if data.get("skill") == skill_name:
                filtered.append(path)
        except Exception:
            continue
    return filtered


def load_skill_content(project_root: Path, skill_name: str) -> str | None:
    """Resolve skill text from project inventory, starter skills, or raw file."""
    skills = discover_skills(project_root=project_root, include_starter=True)
    for doc in skills:
        if doc.name == skill_name:
            return doc.body

    for pattern in (
        f"**/{skill_name}/SKILL.md",
        f"**/{skill_name}.md",
        f"skills/{skill_name}/SKILL.md",
    ):
        for match in project_root.glob(pattern):
            if match.is_file():
                item = Item(kind="skill", name=skill_name, source=match, tags=frozenset())
                doc = parse_doc(item)
                return doc.body

    return None


def render_prompt(template: str, vars_dict: dict[str, Any]) -> str:
    """Render prompt template with test variables."""
    rendered = template
    for key, value in vars_dict.items():
        placeholder_curly = f"{{{{ {key} }}}}"
        placeholder_tight = f"{{{{{key}}}}}"
        placeholder_single = f"{{{key}}}"
        rendered = rendered.replace(placeholder_curly, str(value))
        rendered = rendered.replace(placeholder_tight, str(value))
        rendered = rendered.replace(placeholder_single, str(value))
    return rendered


def evaluate_assertion(assertion: dict[str, Any], text: str) -> AssertionResult:
    """Evaluate a single assertion rule against rendered text."""
    if "contains" in assertion:
        expected = str(assertion["contains"])
        passed = expected in text
        detail = f"Substring '{expected}' {'found' if passed else 'NOT found'}"
        return AssertionResult("contains", expected, passed, detail)

    if "not_contains" in assertion:
        expected = str(assertion["not_contains"])
        passed = expected not in text
        detail = f"Substring '{expected}' {'absent' if passed else 'unexpectedly PRESENT'}"
        return AssertionResult("not_contains", expected, passed, detail)

    if "matches" in assertion:
        pattern = str(assertion["matches"])
        passed = bool(re.search(pattern, text))
        detail = f"Pattern /{pattern}/ {'matched' if passed else 'failed to match'}"
        return AssertionResult("matches", pattern, passed, detail)

    if "not_matches" in assertion:
        pattern = str(assertion["not_matches"])
        passed = not bool(re.search(pattern, text))
        detail = f"Pattern /{pattern}/ {'not matched' if passed else 'unexpectedly matched'}"
        return AssertionResult("not_matches", pattern, passed, detail)

    if "max_length" in assertion:
        max_len = int(assertion["max_length"])
        passed = len(text) <= max_len
        detail = f"Length {len(text)} <= {max_len} ({'pass' if passed else 'FAIL'})"
        return AssertionResult("max_length", max_len, passed, detail)

    if "min_length" in assertion:
        min_len = int(assertion["min_length"])
        passed = len(text) >= min_len
        detail = f"Length {len(text)} >= {min_len} ({'pass' if passed else 'FAIL'})"
        return AssertionResult("min_length", min_len, passed, detail)

    if "json_schema" in assertion:
        schema = assertion["json_schema"]
        try:
            parsed = json.loads(text)
            passed = True
            detail = "Valid JSON"
            if isinstance(schema, dict) and "required" in schema:
                for req in schema["required"]:
                    if req not in parsed:
                        passed = False
                        detail = f"Missing required property '{req}' in JSON"
                        break
        except Exception as exc:
            passed = False
            detail = f"Invalid JSON payload: {exc}"
        return AssertionResult("json_schema", schema, passed, detail)

    return AssertionResult("unknown", assertion, False, f"Unknown assertion: {assertion}")


def run_single_test(
    test_case: dict[str, Any], skill_name: str, skill_content: str
) -> TestCaseResult:
    """Execute a single test case with its assertions."""
    start_time = time.monotonic()
    name = test_case.get("name") or f"test_{int(start_time * 1000)}"
    vars_dict = test_case.get("vars", {})

    rendered = render_prompt(skill_content, vars_dict)
    raw_assertions = test_case.get("assert", [])
    if isinstance(raw_assertions, dict):
        raw_assertions = [raw_assertions]

    assertion_results: list[AssertionResult] = []
    all_passed = True

    for a in raw_assertions:
        res = evaluate_assertion(a, rendered)
        assertion_results.append(res)
        if not res.passed:
            all_passed = False

    duration_ms = round((time.monotonic() - start_time) * 1000, 2)
    return TestCaseResult(
        name=name,
        skill_name=skill_name,
        passed=all_passed,
        duration_ms=duration_ms,
        assertions=assertion_results,
    )


def run_evals(
    project_root: Path,
    eval_dir: Path,
    skill_name: str | None = None,
) -> EvalSuiteResult:
    """Discover and execute all applicable eval suites."""
    suite = EvalSuiteResult()
    eval_files = find_eval_files(eval_dir, skill_name)

    for path in eval_files:
        try:
            spec = load_eval_spec(path)
        except Exception as exc:
            suite.results.append(
                TestCaseResult(
                    name=path.name,
                    skill_name=skill_name or path.stem,
                    passed=False,
                    duration_ms=0.0,
                    error=f"Failed to load spec {path}: {exc}",
                )
            )
            continue

        target_skill = spec.get("skill") or path.name.split(".eval")[0]
        content = load_skill_content(project_root, target_skill)
        if content is None:
            suite.results.append(
                TestCaseResult(
                    name=f"load_{target_skill}",
                    skill_name=target_skill,
                    passed=False,
                    duration_ms=0.0,
                    error=f"Skill '{target_skill}' not found in project or starters",
                )
            )
            continue

        tests = spec.get("tests", [])
        for t in tests:
            result = run_single_test(t, target_skill, content)
            suite.results.append(result)

    return suite


def generate_junit_xml(suite: EvalSuiteResult) -> str:
    """Generate JUnit XML report string from test results."""
    testsuites_el = ET.Element(
        "testsuites",
        name="cinch.eval",
        tests=str(suite.total),
        failures=str(suite.failed),
        errors="0",
    )

    by_skill: dict[str, list[TestCaseResult]] = {}
    for r in suite.results:
        by_skill.setdefault(r.skill_name, []).append(r)

    for s_name, results in by_skill.items():
        s_failures = sum(1 for r in results if not r.passed)
        s_time = sum(r.duration_ms for r in results) / 1000.0
        suite_el = ET.SubElement(
            testsuites_el,
            "testsuite",
            name=f"cinch.eval.{s_name}",
            tests=str(len(results)),
            failures=str(s_failures),
            errors="0",
            time=f"{s_time:.3f}",
        )

        for r in results:
            case_el = ET.SubElement(
                suite_el,
                "testcase",
                classname=f"cinch.eval.{s_name}",
                name=r.name,
                time=f"{(r.duration_ms / 1000.0):.3f}",
            )
            if not r.passed:
                failure_msgs = []
                if r.error:
                    failure_msgs.append(r.error)
                for a in r.assertions:
                    if not a.passed:
                        failure_msgs.append(f"Assertion [{a.rule}] failed: {a.detail}")
                fail_el = ET.SubElement(case_el, "failure", message="; ".join(failure_msgs))
                fail_el.text = "\n".join(failure_msgs)

    return ET.tostring(testsuites_el, encoding="unicode", xml_declaration=True)


def print_eval_summary(suite: EvalSuiteResult, console: Console | None = None) -> None:
    """Render Rich summary table for eval results."""
    console = console or Console()
    table = Table(title="Cinch Skill Evaluation Results", show_lines=True)
    table.add_column("Skill", style="cyan")
    table.add_column("Test Case")
    table.add_column("Status", justify="center")
    table.add_column("Duration", justify="right")
    table.add_column("Details")

    for r in suite.results:
        status_text = "[bold green]PASS[/]" if r.passed else "[bold red]FAIL[/]"
        details = []
        if r.error:
            details.append(f"[red]{r.error}[/]")
        for a in r.assertions:
            if not a.passed:
                details.append(f"[red]{a.detail}[/]")
            elif not r.error and r.passed:
                details.append(f"[dim]{a.detail}[/dim]")

        table.add_row(
            r.skill_name,
            r.name,
            status_text,
            f"{r.duration_ms:.1f}ms",
            "\n".join(details) or "All assertions passed",
        )

    console.print(table)
    summary_color = "green" if suite.failed == 0 else "red"
    console.print(
        f"[{summary_color}]Evaluation finished: {suite.passed}/{suite.total} passed, "
        f"{suite.failed} failed.[/{summary_color}]"
    )
