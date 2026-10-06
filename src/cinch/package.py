"""Git-native remote skill package manager for Cinch.

Supports installing, updating, and uninstalling skills from Git repositories
(e.g., gh:owner/repo@v1, full git URLs, local paths) with version pinning
in cinch.lock and offline caching in ~/.cache/cinch/.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from cinch.errors import CinchError


def get_cache_dir() -> Path:
    """Return the root directory for remote git repositories cache."""
    override = os.environ.get("CINCH_CACHE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".cache" / "cinch"


def parse_package_source(source: str) -> tuple[str, str | None]:
    """Parse a package source string into (git_url, ref).

    Examples:
        gh:org/skills@v1.2.0 -> ('https://github.com/org/skills.git', 'v1.2.0')
        gh:org/skills -> ('https://github.com/org/skills.git', None)
        github.com/org/skills@v1 -> ('https://github.com/org/skills.git', 'v1')
        git@github.com:org/skills.git@v1 -> ('git@github.com:org/skills.git', 'v1')
        https://github.com/org/skills.git@v1 -> ('https://github.com/org/skills.git', 'v1')
        /path/to/repo@v1 -> ('/path/to/repo', 'v1')
        owner/repo@v1 -> ('https://github.com/owner/repo.git', 'v1')
    """
    raw_source = source.strip()
    if not raw_source:
        raise CinchError("Package source cannot be empty")

    ref: str | None = None
    if "@" in raw_source:
        if raw_source.startswith("git@"):
            parts = raw_source.split("@")
            if len(parts) >= 3:
                raw_url = "@".join(parts[:-1])
                ref = parts[-1]
            else:
                raw_url = raw_source
        else:
            raw_url, ref = raw_source.rsplit("@", 1)
    else:
        raw_url = raw_source

    if not ref:
        ref = None

    # Resolve URL format
    if raw_url.startswith("gh:"):
        slug = raw_url[3:].strip("/")
        return f"https://github.com/{slug}.git", ref

    if raw_url.startswith("github.com/"):
        slug = raw_url[11:].strip("/")
        return f"https://github.com/{slug}.git", ref

    if raw_url.startswith(("http://", "https://")):
        url = raw_url if raw_url.endswith(".git") else f"{raw_url}.git"
        return url, ref

    if raw_url.startswith(("git@", "ssh://", "file://")):
        return raw_url, ref

    # Check if it looks like a local filesystem directory or path
    local_path = Path(raw_url).expanduser()
    if local_path.exists() or raw_url.startswith(("/", "./", "../", "~")):
        return str(local_path.resolve()), ref

    # Shorthand owner/repo pattern
    if re.match(r"^[\w.-]+/[\w.-]+$", raw_url):
        return f"https://github.com/{raw_url}.git", ref

    return raw_url, ref


def _run_git(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a git command using subprocess."""
    git_bin = shutil.which("git")
    if not git_bin:
        raise CinchError("Git executable 'git' not found in PATH")

    try:
        return subprocess.run(
            [git_bin, *cmd],
            cwd=str(cwd) if cwd else None,
            check=check,
            capture_output=capture_output,
            text=True,
        )
    except subprocess.CalledProcessError as err:
        stderr_msg = err.stderr.strip() if err.stderr else str(err)
        raise CinchError(f"Git command failed ({' '.join(cmd)}): {stderr_msg}") from err


def compute_directory_checksum(dir_path: Path) -> str:
    """Compute a deterministic SHA-256 integrity hash of a directory tree."""
    hasher = hashlib.sha256()
    if not dir_path.is_dir():
        return f"sha256:{hasher.hexdigest()}"

    for root, _, files in os.walk(dir_path):
        for fname in sorted(files):
            fpath = Path(root) / fname
            rel_path = fpath.relative_to(dir_path).as_posix()
            hasher.update(rel_path.encode("utf-8"))
            try:
                hasher.update(fpath.read_bytes())
            except OSError:
                pass
    return f"sha256:{hasher.hexdigest()}"


def resolve_git_repository(
    url: str,
    *,
    cache_dir: Path | None = None,
) -> Path:
    """Ensure the remote or local git repository is cached locally.

    Returns the path to the cached local clone.
    """
    cache_root = cache_dir or get_cache_dir()
    remotes_root = cache_root / "remotes"
    remotes_root.mkdir(parents=True, exist_ok=True)

    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    repo_cache_dir = remotes_root / url_hash

    if repo_cache_dir.is_dir() and (repo_cache_dir / ".git").is_dir():
        # Repository cached: try updating
        try:
            _run_git(["fetch", "--all", "--tags", "--prune", "--quiet"], cwd=repo_cache_dir)
        except Exception:
            # Network issue or offline mode: proceed with existing cache
            pass
    else:
        # Initial clone
        if repo_cache_dir.exists():
            shutil.rmtree(repo_cache_dir, ignore_errors=True)
        try:
            _run_git(["clone", "--quiet", url, str(repo_cache_dir)])
        except Exception as exc:
            raise CinchError(f"Failed to clone repository '{url}': {exc}") from exc

    return repo_cache_dir


def resolve_commit_sha(repo_dir: Path, ref: str | None) -> str:
    """Resolve a git ref (tag, branch, commit) to a 40-character commit SHA."""
    target_ref = ref or "HEAD"
    if not ref or ref in ("HEAD", "origin/HEAD"):
        candidates = [
            "origin/HEAD^{commit}",
            "origin/HEAD",
            "origin/main^{commit}",
            "origin/main",
            "origin/master^{commit}",
            "origin/master",
            "HEAD^{commit}",
            "HEAD",
        ]
    else:
        candidates = [
            f"refs/tags/{ref}^{{commit}}",
            f"refs/tags/{ref}",
            f"origin/{ref}^{{commit}}",
            f"origin/{ref}",
            f"{ref}^{{commit}}",
            ref,
        ]
    for candidate in candidates:
        proc = _run_git(["rev-parse", "--verify", candidate], cwd=repo_dir, check=False)
        if proc.returncode == 0:
            sha = proc.stdout.strip()
            if len(sha) == 40:
                return sha
    raise CinchError(f"Could not resolve git ref '{target_ref}' in {repo_dir}")


def extract_skill_frontmatter_name(skill_md: Path) -> str | None:
    """Extract skill name from YAML frontmatter if present."""
    if not skill_md.is_file():
        return None
    try:
        content = skill_md.read_text(encoding="utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].splitlines():
                    if line.startswith("name:"):
                        return line.split(":", 1)[1].strip().strip("\"'")
    except Exception:
        pass
    return None


class DiscoveredSkill:
    """A skill candidate discovered in a git repository checkout."""

    def __init__(self, name: str, relative_path: Path, source_dir: Path):
        self.name = name
        self.relative_path = relative_path
        self.source_dir = source_dir


def find_skills_in_checkout(root: Path) -> list[DiscoveredSkill]:
    """Discover all skill packages within an extracted repository tree."""
    skills: list[DiscoveredSkill] = []

    # Check root SKILL.md
    root_skill = root / "SKILL.md"
    if root_skill.is_file():
        fm_name = extract_skill_frontmatter_name(root_skill)
        skill_name = fm_name or root.name
        skills.append(DiscoveredSkill(skill_name, Path("."), root))
        return skills

    # Check nested directories
    for skill_md in sorted(root.rglob("SKILL.md")):
        rel = skill_md.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        skill_folder = skill_md.parent
        fm_name = extract_skill_frontmatter_name(skill_md)
        skill_name = fm_name or skill_folder.name
        skills.append(DiscoveredSkill(skill_name, skill_folder.relative_to(root), skill_folder))

    return skills


def load_lockfile(lockfile_path: Path) -> dict[str, Any]:
    """Load cinch.lock content, initializing empty schema if non-existent."""
    if not lockfile_path.is_file():
        return {"version": 1, "packages": {}}
    try:
        data = json.loads(lockfile_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": 1, "packages": {}}
        data.setdefault("version", 1)
        data.setdefault("packages", {})
        return data
    except Exception:
        return {"version": 1, "packages": {}}


def save_lockfile(lockfile_path: Path, data: dict[str, Any]) -> None:
    """Save formatted lockfile with deterministic indentation and key ordering."""
    content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    lockfile_path.write_text(content, encoding="utf-8")


class PackageResult:
    """Result of an install, update, or uninstall operation."""

    def __init__(
        self,
        name: str,
        source: str,
        ref: str | None,
        commit: str,
        checksum: str,
        vendor_path: Path,
    ):
        self.name = name
        self.source = source
        self.ref = ref
        self.commit = commit
        self.checksum = checksum
        self.vendor_path = vendor_path


def install_package(
    source: str,
    *,
    project: Path | str = ".",
    skill_name: str | None = None,
    force: bool = False,
    cache_dir: Path | None = None,
) -> list[PackageResult]:
    """Install remote skills from git repository into .skills/vendor/<name>/."""
    project_root = Path(project).resolve()
    url, ref = parse_package_source(source)
    repo_cache = resolve_git_repository(url, cache_dir=cache_dir)
    commit_sha = resolve_commit_sha(repo_cache, ref)

    # Export commit to a temporary directory using git archive or checkout
    work_dir = repo_cache / ".cinch_export" / commit_sha
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Use git archive to extract deterministic snapshot
        _run_git(["archive", commit_sha], cwd=repo_cache, capture_output=False)
        # Fallback to direct checkout if archive fails
    except Exception:
        pass

    # Alternative standard approach: checkout tree to work_dir
    try:
        _run_git(
            ["--work-tree", str(work_dir), "checkout", commit_sha, "--", "."],
            cwd=repo_cache,
        )
    except Exception:
        # Archive piped to tar
        tar_pipe = subprocess.Popen(
            ["git", "archive", commit_sha],
            cwd=str(repo_cache),
            stdout=subprocess.PIPE,
        )
        untar_proc = subprocess.Popen(
            ["tar", "-x", "-C", str(work_dir)],
            stdin=tar_pipe.stdout,
        )
        if tar_pipe.stdout:
            tar_pipe.stdout.close()
        untar_proc.wait()

    discovered = find_skills_in_checkout(work_dir)
    if not discovered:
        raise CinchError(f"No valid SKILL.md found in repository '{url}' at {commit_sha[:8]}")

    if skill_name:
        selected = [s for s in discovered if s.name == skill_name]
        if not selected:
            available = ", ".join(s.name for s in discovered)
            raise CinchError(
                f"Skill '{skill_name}' not found in '{url}'. Available skills: {available}"
            )
    else:
        selected = discovered

    vendor_root = project_root / ".skills" / "vendor"
    vendor_root.mkdir(parents=True, exist_ok=True)

    lockfile_path = project_root / "cinch.lock"
    lock_data = load_lockfile(lockfile_path)

    results: list[PackageResult] = []

    for skill in selected:
        target_dir = vendor_root / skill.name
        if target_dir.exists() and not force:
            shutil.rmtree(target_dir)

        target_dir.mkdir(parents=True, exist_ok=True)

        # Copy skill files
        if skill.relative_path == Path("."):
            # Root skill: copy all files except .git and .cinch_export
            for item in work_dir.iterdir():
                if item.name.startswith((".", "_")):
                    continue
                if item.is_dir():
                    shutil.copytree(item, target_dir / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target_dir / item.name)
        else:
            # Subdirectory skill: copy directory contents
            for item in skill.source_dir.iterdir():
                if item.name.startswith("."):
                    continue
                if item.is_dir():
                    shutil.copytree(item, target_dir / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target_dir / item.name)

        checksum = compute_directory_checksum(target_dir)
        lock_data["packages"][skill.name] = {
            "checksum": checksum,
            "commit": commit_sha,
            "installed_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "path": skill.relative_path.as_posix(),
            "ref": ref or "HEAD",
            "source": source,
            "url": url,
        }

        results.append(
            PackageResult(
                name=skill.name,
                source=source,
                ref=ref,
                commit=commit_sha,
                checksum=checksum,
                vendor_path=target_dir,
            )
        )

    save_lockfile(lockfile_path, lock_data)

    # Clean up work dir
    shutil.rmtree(work_dir, ignore_errors=True)

    return results


def uninstall_package(
    name: str,
    *,
    project: Path | str = ".",
) -> bool:
    """Uninstall a vendored skill package and remove from cinch.lock."""
    project_root = Path(project).resolve()
    vendor_dir = project_root / ".skills" / "vendor" / name
    lockfile_path = project_root / "cinch.lock"
    lock_data = load_lockfile(lockfile_path)

    removed = False
    if vendor_dir.is_dir():
        shutil.rmtree(vendor_dir)
        removed = True

    if name in lock_data.get("packages", {}):
        del lock_data["packages"][name]
        save_lockfile(lockfile_path, lock_data)
        removed = True

    if not removed:
        raise CinchError(f"Package '{name}' is not installed in {project_root}")

    return True


def update_package(
    name: str | None = None,
    *,
    project: Path | str = ".",
    cache_dir: Path | None = None,
) -> list[PackageResult]:
    """Update one or all vendored skills from their tracked sources."""
    project_root = Path(project).resolve()
    lockfile_path = project_root / "cinch.lock"
    lock_data = load_lockfile(lockfile_path)
    packages = lock_data.get("packages", {})

    if not packages:
        raise CinchError(f"No packages found in {lockfile_path}")

    if name:
        if name not in packages:
            raise CinchError(f"Package '{name}' is not registered in {lockfile_path}")
        targets = {name: packages[name]}
    else:
        targets = packages

    updated: list[PackageResult] = []
    for pkg_name, meta in targets.items():
        source = meta.get("source") or meta.get("url")
        if not source:
            continue
        results = install_package(
            source,
            project=project_root,
            skill_name=pkg_name,
            force=True,
            cache_dir=cache_dir,
        )
        updated.extend(results)

    return updated
