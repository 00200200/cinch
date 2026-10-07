from __future__ import annotations

import json
import time
import unittest

from cinch.adapters import ADAPTERS
from cinch.wasm import (
    compile_all_dialects,
    compile_json,
    compile_skill,
    doc_from_markdown,
    validate_skill,
)

SAMPLE_SKILL = """---
name: code-reviewer
description: Automated pull request code reviewer checking security and style.
paths:
  - "src/**/*.py"
requires:
  - git-tools
---

# Code Reviewer

## Guidelines
1. Review all modified lines.
2. Ensure test coverage.
"""


class WasmCompilationTests(unittest.TestCase):
    def test_doc_from_markdown(self) -> None:
        doc = doc_from_markdown(SAMPLE_SKILL)
        self.assertEqual(doc.name, "code-reviewer")
        self.assertEqual(
            doc.description,
            "Automated pull request code reviewer checking security and style.",
        )
        self.assertEqual(doc.paths, ("src/**/*.py",))
        self.assertEqual(doc.requires, ("git-tools",))
        # H1 matching doc name was stripped from body
        self.assertNotIn("# Code Reviewer", doc.body)
        self.assertIn("## Guidelines", doc.body)

    def test_doc_from_markdown_fallback_description(self) -> None:
        raw = "---\nname: simple-tool\n---\n\nA helpful utility for tasks.\n"
        doc = doc_from_markdown(raw)
        self.assertEqual(doc.name, "simple-tool")
        self.assertEqual(doc.description, "A helpful utility for tasks.")

    def test_compile_skill_single_dialect(self) -> None:
        # 1. Claude Code
        claude_files = compile_skill(SAMPLE_SKILL, "claude")
        self.assertEqual(len(claude_files), 1)
        self.assertEqual(claude_files[0]["relpath"], ".claude/skills/code-reviewer/SKILL.md")
        self.assertIn('name: "code-reviewer"', claude_files[0]["text"])

        # 2. Cursor
        cursor_files = compile_skill(SAMPLE_SKILL, "cursor")
        self.assertEqual(len(cursor_files), 1)
        self.assertEqual(cursor_files[0]["relpath"], ".agents/skills/code-reviewer/SKILL.md")
        self.assertIn('name: "code-reviewer"', cursor_files[0]["text"])
        self.assertIn('"src/**/*.py"', cursor_files[0]["text"])

        # 3. Copilot
        copilot_files = compile_skill(SAMPLE_SKILL, "copilot")
        self.assertEqual(len(copilot_files), 1)
        self.assertTrue(copilot_files[0]["relpath"].startswith(".github/"))

    def test_compile_all_dialects(self) -> None:
        all_res = compile_all_dialects(SAMPLE_SKILL)
        self.assertEqual(len(all_res), len(ADAPTERS))
        for key in ADAPTERS:
            self.assertIn(key, all_res)
            self.assertGreater(len(all_res[key]), 0)
            self.assertIn("relpath", all_res[key][0])
            self.assertIn("text", all_res[key][0])

    def test_compile_speed_under_10ms(self) -> None:
        # Warmup
        compile_all_dialects(SAMPLE_SKILL)

        # Benchmark 50 compilations across all 12 dialects
        iterations = 50
        start = time.perf_counter()
        for _ in range(iterations):
            compile_all_dialects(SAMPLE_SKILL)
        total_time = time.perf_counter() - start
        avg_ms = (total_time / iterations) * 1000

        self.assertLess(avg_ms, 10.0, f"Average compilation took {avg_ms:.2f}ms (expected <10ms)")

    def test_compile_json_interop(self) -> None:
        raw_json = compile_json(SAMPLE_SKILL)
        data = json.loads(raw_json)
        self.assertTrue(data["valid"])
        self.assertIsInstance(data["dialects"], dict)
        self.assertEqual(len(data["dialects"]), len(ADAPTERS))
        self.assertIn("claude", data["dialects"])
        self.assertIn("cursor", data["dialects"])
        self.assertIsInstance(data["elapsed_ms"], (int, float))

    def test_compile_json_single_target(self) -> None:
        raw_json = compile_json(SAMPLE_SKILL, target="cursor")
        data = json.loads(raw_json)
        self.assertTrue(data["valid"])
        self.assertEqual(list(data["dialects"].keys()), ["cursor"])

    def test_validate_skill_diagnostics(self) -> None:
        invalid_skill = "---\nname: Invalid_Name\n\tbad_tab: true\n"
        diags = validate_skill(invalid_skill)
        self.assertGreater(len(diags), 0)
        messages = [d["message"] for d in diags]
        # Should flag unclosed frontmatter and tabs
        self.assertTrue(any("Unclosed YAML frontmatter" in m for m in messages))


if __name__ == "__main__":
    unittest.main()
