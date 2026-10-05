from pathlib import Path

from cinch.policy import PolicyConfig, audit_policy_skill, load_policy


def test_load_policy_defaults(tmp_path: Path):
    policy_file = tmp_path / ".cinchpolicy.yml"
    policy_file.write_text(
        """
disallowed_keywords:
  - eval
  - rm -rf
required_fields:
  - version
  - author
require_license: true
max_tokens: 500
disallowed_tools:
  - bash_unrestricted
""",
        encoding="utf-8",
    )

    policy = load_policy(start_dir=tmp_path)
    assert policy is not None
    assert "eval" in policy.disallowed_keywords
    assert "version" in policy.required_fields
    assert policy.require_license is True
    assert policy.max_tokens == 500
    assert "bash_unrestricted" in policy.disallowed_tools


def test_audit_policy_skill_violations(tmp_path: Path):
    policy = PolicyConfig(
        disallowed_keywords=("eval", "rm -rf"),
        required_fields=("author",),
        require_license=True,
        max_tokens=100,
        disallowed_tools=("danger_tool",),
    )

    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        """---
name: bad-skill
description: A test skill with violations
tools:
  - danger_tool
---

Never run eval on user inputs!
"""
        + (" word" * 200),
        encoding="utf-8",
    )

    diagnostics = audit_policy_skill(skill_file, policy)
    rules = [d.rule for d in diagnostics]

    assert "POL001" in rules  # missing author
    assert "POL002" in rules  # missing license
    assert "POL003" in rules  # disallowed keyword 'eval'
    assert "POL004" in rules  # exceeded max tokens
    assert "POL005" in rules  # disallowed tool 'danger_tool'


def test_cli_check_with_policy(tmp_path: Path):
    policy_file = tmp_path / ".cinchpolicy.yml"
    policy_file.write_text(
        """
disallowed_keywords:
  - forbidden_secret
""",
        encoding="utf-8",
    )

    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        """---
name: test-skill
description: Clean skill
---
This contains forbidden_secret!
""",
        encoding="utf-8",
    )

    from cinch.cli import main

    exit_code = main(["check", str(skill_file), "--policy", str(policy_file)])
    assert exit_code == 1
