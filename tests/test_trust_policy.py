"""Tests for cinch trust policy evaluation, provenance audit, and install gating (#24)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from cinch.cli import main
from cinch.errors import CinchError
from cinch.package import install_package
from cinch.policy import (
    PolicyConfig,
    evaluate_trust_policy,
    inspect_target_artifacts,
    is_immutable_ref,
    matches_source_pattern,
)


def test_immutable_ref_recognition():
    # 40-char SHA
    assert is_immutable_ref("a" * 40) is True
    assert is_immutable_ref("d7a8fbb2c4d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3") is True
    # SemVer release tags
    assert is_immutable_ref("v1.0.0") is True
    assert is_immutable_ref("2.14.0") is True
    assert is_immutable_ref("v0.1.0-alpha.1") is True
    assert is_immutable_ref("v1.2.3+build.2026") is True

    # Mutable branches and references
    assert is_immutable_ref("main") is False
    assert is_immutable_ref("master") is False
    assert is_immutable_ref("HEAD") is False
    assert is_immutable_ref("dev") is False
    assert is_immutable_ref("feature/test") is False
    assert is_immutable_ref(None) is False
    assert is_immutable_ref("") is False


def test_source_pattern_matching():
    assert matches_source_pattern("https://github.com/my-org/skills.git", "github.com/my-org/*")
    assert matches_source_pattern("gh:my-org/skills", "my-org/*")
    assert matches_source_pattern("git@github.com:my-org/skills.git", "github.com/my-org/skills")
    assert matches_source_pattern("https://untrusted.com/repo.git", "*untrusted*")
    assert not matches_source_pattern("https://github.com/safe/repo.git", "*untrusted*")


def test_static_inspection_finds_scripts_skills_license_escapes(tmp_path: Path):
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # License file
    (repo_dir / "LICENSE").write_text("MIT License\nCopyright 2026", encoding="utf-8")

    # Skill directory with SKILL.md
    skill_dir = repo_dir / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Test\n---\nBody", encoding="utf-8"
    )

    # Executable script
    scripts_dir = repo_dir / "scripts"
    scripts_dir.mkdir()
    script_file = scripts_dir / "run.sh"
    script_file.write_text("#!/bin/bash\necho 'hello'", encoding="utf-8")
    script_file.chmod(0o755)

    # Symlink escape pointing outside repo_dir
    outside_target = tmp_path / "outside_file.txt"
    outside_target.write_text("outside contents", encoding="utf-8")
    escape_link = repo_dir / "escape_link"
    try:
        os.symlink(outside_target, escape_link)
        has_symlinks = True
    except OSError:
        has_symlinks = False

    artifacts = inspect_target_artifacts(repo_dir)

    assert artifacts["license_found"] is True
    assert artifacts["license_type"] == "MIT"
    assert "my-skill/SKILL.md" in artifacts["skills"]
    assert "scripts/run.sh" in artifacts["scripts"]
    if has_symlinks:
        assert any("escape_link" in esc for esc in artifacts["escapes"])


def test_evaluate_trust_policy_detects_violations(tmp_path: Path):
    repo_dir = tmp_path / "violating_repo"
    repo_dir.mkdir()

    # No license
    # Has a python script inside scripts/
    scripts_dir = repo_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "tool.py").write_text("import sys\n", encoding="utf-8")

    policy = PolicyConfig(
        denied_sources=("*malicious*",),
        allowed_sources=("github.com/trusted/*",),
        require_immutable_ref=True,
        require_review_for_scripts=True,
        require_license=True,
        enforce=True,
    )

    report = evaluate_trust_policy(
        repo_dir,
        policy,
        source="https://github.com/malicious/skills.git",
        ref="main",
        commit="12345678",
        reviewed=False,
    )

    assert report.allowed is False
    assert report.enforce is True
    violation_text = "\n".join(report.violations)
    assert "denied pattern" in violation_text
    assert "mutable" in violation_text
    assert "license" in violation_text
    assert "requiring review" in violation_text


def test_evaluate_trust_policy_advisory_mode(tmp_path: Path):
    repo_dir = tmp_path / "advisory_repo"
    repo_dir.mkdir()
    (repo_dir / "LICENSE").write_text("Apache License 2.0", encoding="utf-8")

    policy = PolicyConfig(
        require_immutable_ref=True,
        enforce=False,  # Advisory mode
    )

    report = evaluate_trust_policy(
        repo_dir,
        policy,
        source="https://github.com/trusted/skills.git",
        ref="main",
        reviewed=True,
    )

    # In advisory mode, allowed tracks whether rule violations exist, but report captures status
    assert len(report.violations) == 1
    assert report.enforce is False

    human = report.format_human()
    assert "advisory" in human
    assert "Policy Violations:" in human

    data = report.to_dict()
    assert data["enforce"] is False
    assert data["license"]["present"] is True
    assert data["license"]["type"] == "Apache-2.0"


def test_cli_audit_local_path(tmp_path: Path, capsys):
    repo_dir = tmp_path / "clean_repo"
    repo_dir.mkdir()
    (repo_dir / "LICENSE").write_text("MIT", encoding="utf-8")
    skill_dir = repo_dir / "demo-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo\n---\nText", encoding="utf-8"
    )

    # Advisory run exits 0
    ret = main(["audit", str(repo_dir)])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Cinch Trust Audit Report: ALLOWED" in out
    assert "demo-skill/SKILL.md" in out

    # JSON output
    ret_json = main(["audit", str(repo_dir), "--json"])
    assert ret_json == 0
    out_json = capsys.readouterr().out
    parsed = json.loads(out_json)
    assert parsed["allowed"] is True
    assert "demo-skill/SKILL.md" in parsed["skills"]


def test_cli_audit_enforce_fails_on_violation(tmp_path: Path, capsys):
    policy_file = tmp_path / ".cinchpolicy.yml"
    policy_file.write_text(
        """
require_license: true
require_immutable_ref: true
""",
        encoding="utf-8",
    )

    repo_dir = tmp_path / "unlicensed_repo"
    repo_dir.mkdir()

    # Advisory mode exits 0
    ret_advisory = main(["audit", str(repo_dir), "--policy", str(policy_file), "--ref", "main"])
    assert ret_advisory == 0

    # Enforce mode exits 1
    ret_enforce = main(
        ["audit", str(repo_dir), "--policy", str(policy_file), "--ref", "main", "--enforce"]
    )
    assert ret_enforce == 1
    out = capsys.readouterr().out
    assert "DENIED (enforced)" in out


def test_install_package_blocked_by_enforced_policy(tmp_path: Path):
    # Setup dummy git repo
    git_repo = tmp_path / "git_upstream"
    git_repo.mkdir()
    subprocess.run(["git", "init"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=git_repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    skill_folder = git_repo / "forbidden-skill"
    skill_folder.mkdir()
    (skill_folder / "SKILL.md").write_text(
        "---\nname: forbidden-skill\ndescription: Test\n---\nInstructions", encoding="utf-8"
    )
    # Add a script
    scripts_dir = git_repo / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "evil.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"], cwd=git_repo, check=True, capture_output=True
    )

    project_dir = tmp_path / "my_project"
    project_dir.mkdir()

    policy = PolicyConfig(
        require_review_for_scripts=True,
        enforce=True,
    )

    # Install without --reviewed should fail under enforce mode
    with pytest.raises(CinchError) as exc_info:
        install_package(
            str(git_repo),
            project=project_dir,
            policy=policy,
            enforce_policy=True,
            reviewed=False,
        )
    assert "Installation rejected by trust policy" in str(exc_info.value)
    # Verify no vendor files written
    assert not (project_dir / ".skills" / "vendor" / "forbidden-skill").exists()

    # Install WITH reviewed=True should succeed
    results = install_package(
        str(git_repo),
        project=project_dir,
        policy=policy,
        enforce_policy=True,
        reviewed=True,
    )
    assert len(results) == 1
    assert (project_dir / ".skills" / "vendor" / "forbidden-skill" / "SKILL.md").is_file()
