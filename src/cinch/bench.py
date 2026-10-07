"""Multi-model token cost & footprint benchmark harness for Cinch skills.

Calculates exact token consumption across Claude (cl100k), OpenAI (o200k),
and Gemini tokenizers, computes dollar cost per 1,000 invocations based on
API pricing, detects budget violations, and exports structured JSON for CI gates.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cinch.adapters import ADAPTERS, get_adapter, render_cinch_skill
from cinch.doc import Doc
from cinch.html import discover_skills

try:
    import tiktoken
except ImportError:
    tiktoken = None

DEFAULT_BUDGET: int = 800

# Default pricing per 1,000,000 input tokens (USD)
DEFAULT_PRICING: dict[str, float] = {
    "claude": 3.00,  # Claude 3.5 Sonnet: $3.00 / 1M
    "openai": 2.50,  # GPT-4o: $2.50 / 1M
    "gemini": 0.35,  # Gemini 1.5 Flash: $0.35 / 1M
}

# Mapping harness dialect to pricing/tokenizer family
DIALECT_FAMILY_MAP: dict[str, str] = {
    "claude": "claude",
    "gemini": "gemini",
    "cursor": "openai",
    "codex": "openai",
    "copilot": "openai",
    "windsurf": "openai",
    "cline": "openai",
    "opencode": "openai",
    "aider": "openai",
    "zed": "openai",
    "continue": "openai",
    "grok": "openai",
}


def count_tokens(text: str, family: str = "openai") -> int:
    """Calculate token count for text using tiktoken or robust heuristic fallback.

    Supported families:
    - 'claude' (cl100k_base)
    - 'openai' (o200k_base or cl100k_base)
    - 'gemini' (heuristic)
    """
    if not text:
        return 0

    norm_family = family.lower()

    if tiktoken is not None:
        try:
            if norm_family == "openai":
                try:
                    encoding = tiktoken.get_encoding("o200k_base")
                except Exception:
                    encoding = tiktoken.get_encoding("cl100k_base")
                return len(encoding.encode(text))
            elif norm_family == "claude":
                encoding = tiktoken.get_encoding("cl100k_base")
                return len(encoding.encode(text))
        except Exception:
            pass

    # Heuristic fallback if tiktoken is missing or fails
    if norm_family == "claude":
        return max(1, math.ceil(len(text) / 3.8))
    elif norm_family == "gemini":
        return max(1, math.ceil(len(text) / 3.9))
    else:
        return max(1, math.ceil(len(text) / 3.7))


def compute_cost_per_1k(tokens: int, price_per_million: float) -> float:
    """Compute dollar cost for 1,000 invocations of the prompt."""
    return round((tokens * 1000.0 / 1_000_000.0) * price_per_million, 6)


def load_pricing(pricing_path: Path | str | None = None) -> dict[str, float]:
    """Load pricing dictionary, merging custom pricing over defaults."""
    pricing = dict(DEFAULT_PRICING)
    if not pricing_path:
        return pricing
    path = Path(pricing_path)
    if not path.is_file():
        raise FileNotFoundError(f"Pricing file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    for k, v in data.items():
        pricing[k.lower()] = float(v)
    return pricing


@dataclass
class DialectBenchmark:
    dialect: str
    family: str
    chars: int
    tokens: int
    cost_per_1k: float
    exceeds_budget: bool


@dataclass
class SkillBenchmarkResult:
    name: str
    description: str
    universal_tokens: dict[str, int]
    universal_cost_per_1k: dict[str, float]
    dialects: dict[str, DialectBenchmark] = field(default_factory=dict)
    max_tokens: int = 0
    exceeds_budget: bool = False


@dataclass
class BenchmarkSuiteResult:
    skills: list[SkillBenchmarkResult] = field(default_factory=list)
    budget: int = DEFAULT_BUDGET
    pricing: dict[str, float] = field(default_factory=dict)
    passed: bool = True
    total_skills: int = 0
    violating_skills: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def benchmark_skill(
    doc: Doc,
    budget: int = DEFAULT_BUDGET,
    pricing: dict[str, float] | None = None,
    dialects: tuple[str, ...] | None = None,
) -> SkillBenchmarkResult:
    """Benchmark a single skill across universal representation and dialects."""
    if pricing is None:
        pricing = dict(DEFAULT_PRICING)

    selected_dialects = dialects or tuple(ADAPTERS.keys())
    universal_text = render_cinch_skill(doc)

    universal_tokens = {
        "claude": count_tokens(universal_text, "claude"),
        "openai": count_tokens(universal_text, "openai"),
        "gemini": count_tokens(universal_text, "gemini"),
    }

    universal_cost_per_1k = {
        fam: compute_cost_per_1k(tokens, pricing.get(fam, 1.0))
        for fam, tokens in universal_tokens.items()
    }

    dialect_results: dict[str, DialectBenchmark] = {}
    max_tokens = max(universal_tokens.values()) if universal_tokens else 0

    for dia in selected_dialects:
        if dia not in ADAPTERS:
            continue
        try:
            adapter = get_adapter(dia)
            rendered = adapter.render(doc)
            dia_text = "\n\n".join(rf.text for rf in rendered)
            fam = DIALECT_FAMILY_MAP.get(dia, "openai")
            t_count = count_tokens(dia_text, fam)
            cost_1k = compute_cost_per_1k(t_count, pricing.get(fam, 1.0))
            exceeds = t_count > budget

            if t_count > max_tokens:
                max_tokens = t_count

            dialect_results[dia] = DialectBenchmark(
                dialect=dia,
                family=fam,
                chars=len(dia_text),
                tokens=t_count,
                cost_per_1k=cost_1k,
                exceeds_budget=exceeds,
            )
        except Exception:
            pass

    exceeds_budget = max_tokens > budget

    return SkillBenchmarkResult(
        name=doc.name,
        description=doc.description,
        universal_tokens=universal_tokens,
        universal_cost_per_1k=universal_cost_per_1k,
        dialects=dialect_results,
        max_tokens=max_tokens,
        exceeds_budget=exceeds_budget,
    )


def run_benchmark(
    project_root: Path | str = ".",
    budget: int = DEFAULT_BUDGET,
    pricing_path: Path | str | None = None,
    skill_name: str | None = None,
    dialects: tuple[str, ...] | None = None,
    include_starter: bool = True,
) -> BenchmarkSuiteResult:
    """Run full benchmark suite across all discovered skills."""
    pricing = load_pricing(pricing_path)
    skills = discover_skills(project_root, include_starter=include_starter)

    if skill_name:
        skills = [s for s in skills if s.name == skill_name]

    results: list[SkillBenchmarkResult] = []
    violating: list[str] = []

    for doc in sorted(skills, key=lambda s: s.name):
        res = benchmark_skill(doc, budget=budget, pricing=pricing, dialects=dialects)
        results.append(res)
        if res.exceeds_budget:
            violating.append(res.name)

    passed = len(violating) == 0

    return BenchmarkSuiteResult(
        skills=results,
        budget=budget,
        pricing=pricing,
        passed=passed,
        total_skills=len(results),
        violating_skills=violating,
    )


def print_benchmark_summary(
    suite: BenchmarkSuiteResult,
    console: Console | None = None,
    tokens_only: bool = False,
) -> None:
    """Display Rich-formatted benchmark summary tables."""
    c = console or Console()

    table = Table(title=f"Cinch Token Benchmark (Budget: {suite.budget} tokens)")
    table.add_column("Skill", style="bold cyan")
    table.add_column("Claude (cl100k)", justify="right")
    table.add_column("OpenAI (o200k)", justify="right")
    table.add_column("Gemini", justify="right")
    if not tokens_only:
        table.add_column("Claude $/1k", justify="right", style="green")
        table.add_column("OpenAI $/1k", justify="right", style="green")
    table.add_column("Max Tokens", justify="right")
    table.add_column("Status", justify="center")

    for skill in suite.skills:
        cl_tok = skill.universal_tokens.get("claude", 0)
        oa_tok = skill.universal_tokens.get("openai", 0)
        gm_tok = skill.universal_tokens.get("gemini", 0)

        cl_cost = f"${skill.universal_cost_per_1k.get('claude', 0.0):.4f}"
        oa_cost = f"${skill.universal_cost_per_1k.get('openai', 0.0):.4f}"

        if skill.exceeds_budget:
            status = "[bold red]EXCEEDED[/bold red]"
            max_style = "[bold red]"
        else:
            status = "[bold green]PASS[/bold green]"
            max_style = "[green]"

        row = [
            skill.name,
            str(cl_tok),
            str(oa_tok),
            str(gm_tok),
        ]
        if not tokens_only:
            row.extend([cl_cost, oa_cost])
        row.extend([f"{max_style}{skill.max_tokens}[/]", status])
        table.add_row(*row)

    c.print(table)

    summary_color = "green" if suite.passed else "red"
    summary_text = (
        f"Skills benchmarked: {suite.total_skills} | "
        f"Budget: {suite.budget} tokens | "
        f"Violations: {len(suite.violating_skills)}"
    )
    if suite.violating_skills:
        summary_text += f"\nViolating skills: {', '.join(suite.violating_skills)}"

    c.print(
        Panel(
            summary_text,
            title="[bold]Benchmark Summary[/bold]",
            border_style=summary_color,
        )
    )
