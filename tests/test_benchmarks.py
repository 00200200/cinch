"""Unit and regression tests for Cinch multi-model token benchmarks."""

from __future__ import annotations

import json
from pathlib import Path

from cinch.bench import (
    DEFAULT_PRICING,
    benchmark_skill,
    compute_cost_per_1k,
    count_tokens,
    load_pricing,
    print_benchmark_summary,
    run_benchmark,
)
from cinch.cli import main
from cinch.doc import Doc


def test_count_tokens_standard():
    text = "Hello world! This is a test prompt for benchmarking skills."
    cl_tok = count_tokens(text, "claude")
    oa_tok = count_tokens(text, "openai")
    gm_tok = count_tokens(text, "gemini")

    assert cl_tok > 0
    assert oa_tok > 0
    assert gm_tok > 0
    assert count_tokens("", "openai") == 0


def test_count_tokens_fallback(monkeypatch):
    import cinch.bench as bench_mod

    monkeypatch.setattr(bench_mod, "tiktoken", None)

    text = "A simple sentence to verify fallback heuristics."
    cl_tok = bench_mod.count_tokens(text, "claude")
    oa_tok = bench_mod.count_tokens(text, "openai")
    gm_tok = bench_mod.count_tokens(text, "gemini")

    assert cl_tok > 0
    assert oa_tok > 0
    assert gm_tok > 0


def test_compute_cost_per_1k():
    # 1,000 tokens at $3.00 per 1M:
    # (1,000 * 1,000 / 1,000,000) * 3.00 = 1 * 3.00 = $3.000000 per 1k invocations
    cost = compute_cost_per_1k(1000, 3.00)
    assert cost == 3.0

    # 500 tokens at $2.50 per 1M:
    cost_half = compute_cost_per_1k(500, 2.50)
    assert cost_half == 1.25


def test_load_pricing_default_and_custom(tmp_path: Path):
    defaults = load_pricing(None)
    assert defaults["claude"] == DEFAULT_PRICING["claude"]
    assert defaults["openai"] == DEFAULT_PRICING["openai"]

    custom_file = tmp_path / "pricing.json"
    custom_file.write_text(json.dumps({"claude": 5.0, "custom_model": 1.2}), encoding="utf-8")

    loaded = load_pricing(custom_file)
    assert loaded["claude"] == 5.0
    assert loaded["custom_model"] == 1.2
    assert loaded["openai"] == DEFAULT_PRICING["openai"]


def test_benchmark_skill_and_budget_flagging():
    doc = Doc(
        kind="skill",
        name="test-skill",
        description="A short test skill for benchmarking.",
        body="## Instructions\nPerform a quick operation.",
    )

    # Budget 5000 -> should pass
    res_pass = benchmark_skill(doc, budget=5000)
    assert not res_pass.exceeds_budget
    assert "claude" in res_pass.universal_tokens
    assert "cursor" in res_pass.dialects

    # Budget 5 -> should fail
    res_fail = benchmark_skill(doc, budget=5)
    assert res_fail.exceeds_budget


def test_run_benchmark_suite(tmp_path: Path):
    suite = run_benchmark(".", budget=2000)
    assert suite.passed
    assert suite.total_skills >= 4
    assert len(suite.violating_skills) == 0

    as_dict = suite.to_dict()
    assert as_dict["passed"] is True
    assert "skills" in as_dict

    # Budget violation
    strict_suite = run_benchmark(".", budget=10)
    assert not strict_suite.passed
    assert len(strict_suite.violating_skills) > 0


def test_print_benchmark_summary():
    suite = run_benchmark(".", budget=2000)
    # Should not raise
    print_benchmark_summary(suite, tokens_only=False)
    print_benchmark_summary(suite, tokens_only=True)


def test_cli_bench_basic():
    exit_code = main(["bench"])
    assert exit_code == 0


def test_cli_bench_tokens_flag():
    exit_code = main(["bench", "--tokens"])
    assert exit_code == 0


def test_cli_bench_budget_violation_fails_ci():
    exit_code = main(["bench", "--budget", "10"])
    assert exit_code == 1


def test_cli_bench_json_export(tmp_path: Path):
    out_file = tmp_path / "benchmarks.json"
    exit_code = main(["bench", "--json", str(out_file)])
    assert exit_code == 0
    assert out_file.is_file()

    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert "skills" in data
    assert data["passed"] is True
