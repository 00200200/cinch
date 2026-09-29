"""Tests for cinch check --audit-secrets."""

from __future__ import annotations

from pathlib import Path

from cinch.cli import main
from cinch.secrets import audit_skill, scan_text


def _create_skill(path: Path, body: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    skill_file = path / "SKILL.md"
    skill_file.write_text(
        f"""\
---
name: {path.name}
description: A comprehensive description of the skill
---
{body}
""",
        encoding="utf-8",
    )
    return skill_file


def test_detects_openai_style_key(tmp_path: Path) -> None:
    skill = _create_skill(
        tmp_path / "leak-openai",
        "Use key sk-abcdefghijklmnopqrstuvwxyz0123456789ABCDEF when calling the API.",
    )
    findings = scan_text(skill.read_text(encoding="utf-8"), skill)
    assert any(f.rule == "S001" and "OpenAI" in f.kind for f in findings)


def test_detects_github_token(tmp_path: Path) -> None:
    token = "ghp_" + ("A" * 36)
    skill = _create_skill(tmp_path / "leak-gh", f"Authorization with {token}")
    findings = scan_text(skill.read_text(encoding="utf-8"), skill)
    assert any(f.rule == "S001" and "GitHub" in f.kind for f in findings)


def test_detects_aws_key(tmp_path: Path) -> None:
    skill = _create_skill(
        tmp_path / "leak-aws",
        "aws_access_key_id = AKIAIOSFODNN7ABCD012",
    )
    findings = scan_text(skill.read_text(encoding="utf-8"), skill)
    assert any(f.rule == "S001" and "AWS" in f.kind for f in findings)


def test_detects_bearer_token(tmp_path: Path) -> None:
    skill = _create_skill(
        tmp_path / "leak-bearer",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abcdef",
    )
    findings = scan_text(skill.read_text(encoding="utf-8"), skill)
    assert any(f.rule == "S001" and "Bearer" in f.kind for f in findings)


def test_detects_user_paths(tmp_path: Path) -> None:
    skill = _create_skill(
        tmp_path / "leak-path",
        "Read /Users/alice/.ssh/id_rsa and also C:\\Users\\bob\\secrets.env",
    )
    findings = scan_text(skill.read_text(encoding="utf-8"), skill)
    path_hits = [f for f in findings if f.rule == "S003"]
    assert len(path_hits) >= 2


def test_detects_high_entropy_secret(tmp_path: Path) -> None:
    # 48 chars of mixed base64 alphabet → high Shannon entropy.
    secret = "Qk9GVm5xWjJtTDh5UnM0dFUxYkNkRWZoR2hpSmtsbU5v"
    skill = _create_skill(
        tmp_path / "leak-entropy",
        f"session_token={secret}",
    )
    findings = scan_text(skill.read_text(encoding="utf-8"), skill)
    assert any(f.rule == "S002" for f in findings)


def test_no_false_positive_on_placeholders(tmp_path: Path) -> None:
    skill = _create_skill(
        tmp_path / "clean-placeholders",
        """\
# Setup

Export your key as an environment variable:

```bash
export API_KEY=${API_KEY}
export OPENAI_API_KEY=sk-example
curl -H "Authorization: Bearer ${TOKEN}" https://api.example.com
```

Never commit `<YOUR_API_KEY>` or `sk-fake-placeholder-key-here`.
""",
    )
    findings = scan_text(skill.read_text(encoding="utf-8"), skill)
    assert findings == []


def test_no_false_positive_on_ordinary_markdown(tmp_path: Path) -> None:
    skill = _create_skill(
        tmp_path / "clean-md",
        """\
# Deploy skill

Run `cinch init --harness cursor` then commit the wired files.

Short words like apple banana cherry should not trip entropy checks.
Paths such as `./src/cinch/cli.py` are fine.
""",
    )
    findings = scan_text(skill.read_text(encoding="utf-8"), skill)
    assert findings == []


def test_audit_skill_returns_error_diagnostics(tmp_path: Path) -> None:
    skill_dir = tmp_path / "leaky"
    _create_skill(
        skill_dir,
        "token ghp_" + ("B" * 36),
    )
    diags = audit_skill(skill_dir)
    assert diags
    assert all(d.severity == "error" for d in diags)
    assert any(d.rule == "S001" for d in diags)


def test_cli_audit_secrets_exit_codes(tmp_path: Path) -> None:
    clean = tmp_path / "clean-skill"
    _create_skill(
        clean,
        "Use ${API_KEY} from the environment. Example: sk-example",
    )
    leaky = tmp_path / "leaky-skill"
    _create_skill(
        leaky,
        "Hardcoded key sk-abcdefghijklmnopqrstuvwxyz0123456789ABCDEF",
    )

    assert main(["check", "--audit-secrets", str(clean)]) == 0
    assert main(["check", "--audit-secrets", str(leaky)]) == 1
    # Without the flag, a secret alone does not fail check (lint is clean).
    assert main(["check", str(leaky)]) == 0
