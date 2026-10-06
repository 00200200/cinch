"""Unit tests for cinch.eval automated skill assertion test runner."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from cinch.cli import main
from cinch.eval import (
    AssertionResult,
    EvalSuiteResult,
    TestCaseResult,
    evaluate_assertion,
    generate_junit_xml,
    load_eval_spec,
    render_prompt,
    run_evals,
    run_single_test,
)


def test_evaluate_assertions_contains_and_not_contains():
    text = "Run pytest -v to verify the fix. Never execute sudo rm -rf."

    res1 = evaluate_assertion({"contains": "pytest -v"}, text)
    assert res1.passed is True
    assert res1.rule == "contains"

    res2 = evaluate_assertion({"contains": "npm test"}, text)
    assert res2.passed is False

    res3 = evaluate_assertion({"not_contains": "sudo rm -rf"}, text)
    assert res3.passed is False

    res4 = evaluate_assertion({"not_contains": "format C:"}, text)
    assert res4.passed is True


def test_evaluate_assertions_regex_matches():
    text = "Command: pytest -q --tb=short tests/test_core.py"

    res1 = evaluate_assertion({"matches": r"pytest\s+-[a-z]"}, text)
    assert res1.passed is True

    res2 = evaluate_assertion({"matches": r"^unittest"}, text)
    assert res2.passed is False

    res3 = evaluate_assertion({"not_matches": r"error|fatal"}, text)
    assert res3.passed is True

    res4 = evaluate_assertion({"not_matches": r"pytest"}, text)
    assert res4.passed is False


def test_evaluate_assertions_length():
    text = "Hello world"

    res1 = evaluate_assertion({"max_length": 20}, text)
    assert res1.passed is True

    res2 = evaluate_assertion({"max_length": 5}, text)
    assert res2.passed is False

    res3 = evaluate_assertion({"min_length": 5}, text)
    assert res3.passed is True

    res4 = evaluate_assertion({"min_length": 50}, text)
    assert res4.passed is False


def test_evaluate_assertions_json_schema():
    valid_json = '{"name": "test-run", "status": "ok", "count": 42}'
    invalid_json = "not json at all"

    res1 = evaluate_assertion({"json_schema": {"required": ["name", "status"]}}, valid_json)
    assert res1.passed is True

    res2 = evaluate_assertion({"json_schema": {"required": ["missing_prop"]}}, valid_json)
    assert res2.passed is False

    res3 = evaluate_assertion({"json_schema": {}}, invalid_json)
    assert res3.passed is False


def test_render_prompt_variable_substitution():
    tmpl = "Review task: {{ input }}. Mode: {mode}."
    rendered = render_prompt(tmpl, {"input": "fix crash in main()", "mode": "strict"})
    assert rendered == "Review task: fix crash in main(). Mode: strict."


def test_load_eval_spec_json_and_yaml(tmp_path: Path):
    json_spec = tmp_path / "skill_a.eval.json"
    json_spec.write_text(
        json.dumps(
            {
                "skill": "skill_a",
                "tests": [{"name": "test1", "assert": [{"contains": "pass"}]}],
            }
        ),
        encoding="utf-8",
    )
    loaded_json = load_eval_spec(json_spec)
    assert loaded_json["skill"] == "skill_a"
    assert len(loaded_json["tests"]) == 1

    yaml_spec = tmp_path / "skill_b.eval.yml"
    yaml_spec.write_text(
        "skill: skill_b\ntests:\n  - name: test2\n    assert:\n      - not_contains: fail\n",
        encoding="utf-8",
    )
    loaded_yaml = load_eval_spec(yaml_spec)
    assert loaded_yaml["skill"] == "skill_b"
    assert loaded_yaml["tests"][0]["name"] == "test2"


def test_run_single_test_execution():
    content = "Always run pytest -v when editing tests."
    case_pass = {
        "name": "Verify pytest instruction",
        "assert": [{"contains": "pytest -v"}, {"max_length": 100}],
    }
    res_pass = run_single_test(case_pass, "tester", content)
    assert res_pass.passed is True
    assert len(res_pass.assertions) == 2

    case_fail = {
        "name": "Verify forbidden commands",
        "assert": [{"not_contains": "pytest"}],
    }
    res_fail = run_single_test(case_fail, "tester", content)
    assert res_fail.passed is False


def test_generate_junit_xml():
    suite = EvalSuiteResult(
        results=[
            TestCaseResult(
                name="test_pass",
                skill_name="skill1",
                passed=True,
                duration_ms=12.5,
                assertions=[AssertionResult("contains", "abc", True)],
            ),
            TestCaseResult(
                name="test_fail",
                skill_name="skill1",
                passed=False,
                duration_ms=8.0,
                assertions=[AssertionResult("contains", "xyz", False, "Missing xyz")],
            ),
        ]
    )
    xml_str = generate_junit_xml(suite)
    root = ET.fromstring(xml_str)
    assert root.tag == "testsuites"
    assert root.attrib["tests"] == "2"
    assert root.attrib["failures"] == "1"

    testsuite_el = root.find("testsuite")
    assert testsuite_el is not None
    assert testsuite_el.attrib["name"] == "cinch.eval.skill1"

    testcases = testsuite_el.findall("testcase")
    assert len(testcases) == 2
    assert testcases[1].find("failure") is not None


def test_run_evals_end_to_end_with_fixtures(tmp_path: Path):
    eval_dir = tmp_path / "evals"
    eval_dir.mkdir()
    skills_dir = tmp_path / "skills" / "math-helper"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        "---\nname: math-helper\ndescription: Math assistant\n---\n"
        "Solve equations using numpy and sympy.\nNever use eval().\n",
        encoding="utf-8",
    )

    spec_path = eval_dir / "math-helper.eval.json"
    spec_path.write_text(
        json.dumps(
            {
                "skill": "math-helper",
                "tests": [
                    {
                        "name": "Check allowed packages",
                        "assert": [{"contains": "numpy"}, {"contains": "sympy"}],
                    },
                    {
                        "name": "Check unsafe functions prohibited",
                        "assert": [{"not_contains": "os.system"}],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    suite = run_evals(tmp_path, eval_dir)
    assert suite.total == 2
    assert suite.passed == 2
    assert suite.failed == 0


def test_cli_eval_command(tmp_path: Path, monkeypatch):
    eval_dir = tmp_path / "evals"
    eval_dir.mkdir()
    junit_file = tmp_path / "report.xml"

    spec_path = eval_dir / "starter-test.eval.json"
    # mkl-review-pr or similar starter skill or bundled skill
    spec_path.write_text(
        json.dumps(
            {
                "skill": "security-auditor",
                "tests": [
                    {
                        "name": "Valid starter evaluation",
                        "assert": [{"min_length": 10}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    # Run CLI cinch eval
    exit_code = main(
        [
            "eval",
            "--project",
            str(tmp_path),
            "--eval-dir",
            "evals",
            "--output-junit",
            str(junit_file),
        ]
    )
    assert exit_code == 0
    assert junit_file.is_file()
    xml_content = junit_file.read_text(encoding="utf-8")
    assert "<testsuites" in xml_content
