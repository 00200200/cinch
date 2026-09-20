"""Conformance test suite verifying all 9 harness adapters against vendor specs."""

from __future__ import annotations

from pathlib import Path

import pytest

from cinch.adapters import get_adapter
from cinch.catalog import HARNESS_ORDER
from cinch.doc import Doc

CONFORMANCE_DIR = Path(__file__).parent / "conformance"


@pytest.fixture
def sample_skill() -> Doc:
    return Doc(
        kind="skill",
        name="humanizer",
        description="Convert robotic AI prose into punchy writing",
        body="# Guidelines\nCut boilerplate openers.\n",
        paths=("**/*.md",),
    )


@pytest.fixture
def sample_agent() -> Doc:
    return Doc(
        kind="agent",
        name="reviewer",
        description="Perform thorough code reviews",
        body="Check diffs carefully for logic flaws.\n",
        paths=(),
    )


class TestVendorConformanceSpecs:
    @pytest.mark.parametrize("harness_id", HARNESS_ORDER)
    def test_vendor_source_documentation_is_documented(self, harness_id: str) -> None:
        source_doc = CONFORMANCE_DIR / harness_id / "SOURCE.md"
        assert source_doc.is_file(), f"Missing SOURCE.md documentation for {harness_id}"
        content = source_doc.read_text(encoding="utf-8")
        assert "http" in content
        assert "Vendor:" in content
        assert "Product:" in content

    @pytest.mark.parametrize("harness_id", HARNESS_ORDER)
    def test_skill_render_is_valid_and_non_empty(self, harness_id: str, sample_skill: Doc) -> None:
        adapter = get_adapter(harness_id)
        rendered = adapter.render(sample_skill)
        assert len(rendered) >= 1
        primary = rendered[0]
        assert primary.relpath
        assert primary.text.strip()
        assert sample_skill.name in primary.relpath or sample_skill.name in primary.text

    @pytest.mark.parametrize("harness_id", HARNESS_ORDER)
    def test_agent_render_is_valid(self, harness_id: str, sample_agent: Doc) -> None:
        adapter = get_adapter(harness_id)
        rendered = adapter.render(sample_agent)
        assert len(rendered) >= 1
        primary = rendered[0]
        assert primary.relpath
        assert primary.text.strip()
