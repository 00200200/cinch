"""Tests for git-native remote skill package manager."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cinch.cli import main
from cinch.errors import CinchError
from cinch.inventory import collect_inventory
from cinch.package import (
    compute_directory_checksum,
    install_package,
    load_lockfile,
    parse_package_source,
    save_lockfile,
    uninstall_package,
    update_package,
)


def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with user and email set for testing."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )


def test_parse_package_source():
    assert parse_package_source("gh:acme/skills@v1.2.0") == (
        "https://github.com/acme/skills.git",
        "v1.2.0",
    )
    assert parse_package_source("gh:acme/skills") == (
        "https://github.com/acme/skills.git",
        None,
    )
    assert parse_package_source("github.com/acme/skills@v1") == (
        "https://github.com/acme/skills.git",
        "v1",
    )
    assert parse_package_source("https://github.com/acme/skills.git@v2") == (
        "https://github.com/acme/skills.git",
        "v2",
    )
    assert parse_package_source("https://github.com/acme/skills@main") == (
        "https://github.com/acme/skills.git",
        "main",
    )
    assert parse_package_source("git@github.com:acme/skills.git@v1.0") == (
        "git@github.com:acme/skills.git",
        "v1.0",
    )
    assert parse_package_source("file:///tmp/repo@v1") == (
        "file:///tmp/repo",
        "v1",
    )
    assert parse_package_source("acme/skills@v1") == (
        "https://github.com/acme/skills.git",
        "v1",
    )

    with pytest.raises(CinchError):
        parse_package_source("")


def test_compute_directory_checksum(tmp_path: Path):
    d = tmp_path / "skill"
    d.mkdir()
    (d / "SKILL.md").write_text("# Skill", encoding="utf-8")
    (d / "helper.py").write_text("print('hello')", encoding="utf-8")

    c1 = compute_directory_checksum(d)
    assert c1.startswith("sha256:")

    c2 = compute_directory_checksum(d)
    assert c1 == c2

    (d / "helper.py").write_text("print('world')", encoding="utf-8")
    c3 = compute_directory_checksum(d)
    assert c1 != c3


def test_lockfile_roundtrip(tmp_path: Path):
    lock_path = tmp_path / "cinch.lock"
    initial = load_lockfile(lock_path)
    assert initial == {"version": 1, "packages": {}}

    initial["packages"]["test"] = {"ref": "v1.0", "commit": "12345678"}
    save_lockfile(lock_path, initial)

    loaded = load_lockfile(lock_path)
    assert loaded["packages"]["test"]["commit"] == "12345678"


def test_install_and_uninstall_single_skill(tmp_path: Path):
    remote_repo = tmp_path / "remote_repo"
    _init_git_repo(remote_repo)

    skill_md = remote_repo / "SKILL.md"
    skill_md.write_text(
        "---\nname: security-scan\ndescription: Corporate security scanner\n---\n# Scan\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(remote_repo), check=True)
    subprocess.run(["git", "commit", "-m", "v1.0.0"], cwd=str(remote_repo), check=True)
    subprocess.run(["git", "tag", "v1.0.0"], cwd=str(remote_repo), check=True)

    project = tmp_path / "my_project"
    project.mkdir()
    cache_dir = tmp_path / "cache"

    results = install_package(
        f"{remote_repo}@v1.0.0",
        project=project,
        cache_dir=cache_dir,
    )

    assert len(results) == 1
    res = results[0]
    assert res.name == "security-scan"
    assert res.ref == "v1.0.0"
    assert len(res.commit) == 40
    assert (project / ".skills" / "vendor" / "security-scan" / "SKILL.md").is_file()

    lock = load_lockfile(project / "cinch.lock")
    assert "security-scan" in lock["packages"]
    assert lock["packages"]["security-scan"]["ref"] == "v1.0.0"
    assert lock["packages"]["security-scan"]["checksum"] == res.checksum

    # Inventory detects vendored skill
    items = collect_inventory(harness="claude", project=project, home=tmp_path / "home")
    assert any(item.name == "security-scan" for item in items)

    # Uninstall
    assert uninstall_package("security-scan", project=project)
    assert not (project / ".skills" / "vendor" / "security-scan").exists()
    lock_after = load_lockfile(project / "cinch.lock")
    assert "security-scan" not in lock_after["packages"]


def test_install_multi_skill_repo(tmp_path: Path):
    remote_repo = tmp_path / "multi_repo"
    _init_git_repo(remote_repo)

    (remote_repo / "skills" / "foo").mkdir(parents=True)
    (remote_repo / "skills" / "foo" / "SKILL.md").write_text(
        "---\nname: foo-skill\n---\n# Foo", encoding="utf-8"
    )

    (remote_repo / "skills" / "bar").mkdir(parents=True)
    (remote_repo / "skills" / "bar" / "SKILL.md").write_text(
        "---\nname: bar-skill\n---\n# Bar", encoding="utf-8"
    )

    subprocess.run(["git", "add", "."], cwd=str(remote_repo), check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(remote_repo), check=True)

    project = tmp_path / "project2"
    project.mkdir()
    cache_dir = tmp_path / "cache"

    # Install specific skill
    results = install_package(
        str(remote_repo),
        project=project,
        skill_name="foo-skill",
        cache_dir=cache_dir,
    )
    assert len(results) == 1
    assert results[0].name == "foo-skill"
    assert (project / ".skills" / "vendor" / "foo-skill" / "SKILL.md").is_file()
    assert not (project / ".skills" / "vendor" / "bar-skill").exists()

    # Install all remaining
    results_all = install_package(
        str(remote_repo),
        project=project,
        cache_dir=cache_dir,
    )
    assert {r.name for r in results_all} == {"foo-skill", "bar-skill"}
    assert (project / ".skills" / "vendor" / "bar-skill" / "SKILL.md").is_file()


def test_update_package(tmp_path: Path):
    remote_repo = tmp_path / "update_repo"
    _init_git_repo(remote_repo)

    (remote_repo / "SKILL.md").write_text("---\nname: my-skill\n---\n# v1", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(remote_repo), check=True)
    subprocess.run(["git", "commit", "-m", "v1"], cwd=str(remote_repo), check=True)

    project = tmp_path / "project3"
    project.mkdir()
    cache_dir = tmp_path / "cache"

    install_package(str(remote_repo), project=project, cache_dir=cache_dir)
    lock1 = load_lockfile(project / "cinch.lock")
    checksum1 = lock1["packages"]["my-skill"]["checksum"]

    # Make change in remote repo
    (remote_repo / "SKILL.md").write_text("---\nname: my-skill\n---\n# v2", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(remote_repo), check=True)
    subprocess.run(["git", "commit", "-m", "v2"], cwd=str(remote_repo), check=True)

    updated = update_package("my-skill", project=project, cache_dir=cache_dir)
    assert len(updated) == 1
    lock2 = load_lockfile(project / "cinch.lock")
    checksum2 = lock2["packages"]["my-skill"]["checksum"]
    assert checksum1 != checksum2


def test_cli_package_workflow(tmp_path: Path, monkeypatch):
    remote_repo = tmp_path / "cli_repo"
    _init_git_repo(remote_repo)
    (remote_repo / "SKILL.md").write_text("---\nname: cli-tool\n---\n# CLI", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(remote_repo), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(remote_repo), check=True)

    project = tmp_path / "cli_project"
    project.mkdir()
    monkeypatch.setenv("CINCH_CACHE_DIR", str(tmp_path / "cli_cache"))

    # CLI install
    ret = main(["install", str(remote_repo), "--project", str(project)])
    assert ret == 0
    assert (project / ".skills" / "vendor" / "cli-tool" / "SKILL.md").is_file()

    # CLI update
    ret = main(["update", "--project", str(project)])
    assert ret == 0

    # CLI uninstall
    ret = main(["uninstall", "cli-tool", "--project", str(project)])
    assert ret == 0
    assert not (project / ".skills" / "vendor" / "cli-tool").exists()
