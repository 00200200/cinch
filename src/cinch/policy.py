"""Corporate skill compliance & safety policy enforcement (.cinchpolicy.yml)."""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cinch.check import Diagnostic, _parse_frontmatter


@dataclass(frozen=True)
class PolicyConfig:
    disallowed_keywords: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    max_tokens: int | None = None
    require_license: bool = False
    disallowed_tools: tuple[str, ...] = ()
    allowed_sources: tuple[str, ...] = ()
    denied_sources: tuple[str, ...] = ()
    require_immutable_ref: bool = False
    require_review_for_scripts: bool = False
    enforce: bool = False


def _parse_policy_text(text: str) -> dict[str, Any]:
    """Parse simple YAML policy without external dependencies."""
    data: dict[str, Any] = {}
    current_list_key: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- ") and current_list_key:
            val = stripped[2:].strip().strip('"').strip("'")
            data.setdefault(current_list_key, []).append(val)
            continue

        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if not val:
                current_list_key = key
                data[key] = []
            else:
                current_list_key = None
                if val.lower() == "true":
                    data[key] = True
                elif val.lower() == "false":
                    data[key] = False
                elif val.isdigit():
                    data[key] = int(val)
                else:
                    data[key] = val

    return data


def load_policy(path: Path | None = None, start_dir: Path | None = None) -> PolicyConfig | None:
    """Load policy configuration from specified path or searching upward for .cinchpolicy.yml."""
    if path is not None:
        policy_file = Path(path)
        if not policy_file.exists():
            return None
    else:
        current = (start_dir or Path.cwd()).resolve()
        policy_file = None
        for parent in [current, *current.parents]:
            candidate = parent / ".cinchpolicy.yml"
            if candidate.is_file():
                policy_file = candidate
                break
            candidate_yaml = parent / ".cinchpolicy.yaml"
            if candidate_yaml.is_file():
                policy_file = candidate_yaml
                break
        if policy_file is None:
            return None

    try:
        data = _parse_policy_text(policy_file.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    return PolicyConfig(
        disallowed_keywords=tuple(str(k).lower() for k in data.get("disallowed_keywords", ())),
        required_fields=tuple(str(f).lower() for f in data.get("required_fields", ())),
        max_tokens=int(data["max_tokens"]) if "max_tokens" in data else None,
        require_license=bool(data.get("require_license", False)),
        disallowed_tools=tuple(str(t).lower() for t in data.get("disallowed_tools", ())),
        allowed_sources=tuple(str(s) for s in data.get("allowed_sources", ())),
        denied_sources=tuple(str(s) for s in data.get("denied_sources", ())),
        require_immutable_ref=bool(data.get("require_immutable_ref", False)),
        require_review_for_scripts=bool(data.get("require_review_for_scripts", False)),
        enforce=bool(data.get("enforce", False)),
    )


def audit_policy_skill(skill_file: Path, policy: PolicyConfig) -> list[Diagnostic]:
    """Check a single SKILL.md file against corporate policy."""
    try:
        content = skill_file.read_text(encoding="utf-8")
    except Exception:
        return []

    diagnostics: list[Diagnostic] = []
    meta, field_lines, fm_errors, body, body_start_line = _parse_frontmatter(content, skill_file)

    # 1. Required fields
    for req_field in policy.required_fields:
        if req_field not in meta:
            diagnostics.append(
                Diagnostic(
                    path=skill_file,
                    line=1,
                    severity="error",
                    rule="POL001",
                    message=f"Policy violation: missing required field '{req_field}'",
                )
            )

    # 2. License check
    if policy.require_license and "license" not in meta:
        diagnostics.append(
            Diagnostic(
                path=skill_file,
                line=1,
                severity="error",
                rule="POL002",
                message="Policy violation: 'license' field is mandatory under policy",
            )
        )

    # 3. Disallowed keywords in prompt/body
    content_lower = content.lower()
    for kw in policy.disallowed_keywords:
        if kw in content_lower:
            # find line number
            found_line = 1
            for idx, line in enumerate(content.splitlines(), 1):
                if kw in line.lower():
                    found_line = idx
                    break
            diagnostics.append(
                Diagnostic(
                    path=skill_file,
                    line=found_line,
                    severity="error",
                    rule="POL003",
                    message=f"Policy violation: disallowed keyword '{kw}' detected",
                )
            )

    # 4. Token limit budget
    if policy.max_tokens is not None:
        approx_tokens = len(content.split()) * 4 // 3
        if approx_tokens > policy.max_tokens:
            diagnostics.append(
                Diagnostic(
                    path=skill_file,
                    line=1,
                    severity="error",
                    rule="POL004",
                    message=(
                        f"Policy violation: token count ({approx_tokens}) exceeds maximum "
                        f"budget ({policy.max_tokens})"
                    ),
                )
            )

    # 5. Disallowed tools
    tools = meta.get("tools", [])
    if isinstance(tools, str):
        tools = [tools]
    if isinstance(tools, list):
        for tool in tools:
            tool_str = str(tool).lower()
            if tool_str in policy.disallowed_tools:
                diagnostics.append(
                    Diagnostic(
                        path=skill_file,
                        line=field_lines.get("tools", 1),
                        severity="error",
                        rule="POL005",
                        message=f"Policy violation: disallowed tool '{tool_str}' specified",
                    )
                )

    return diagnostics


def audit_policy_directory(root: Path, policy: PolicyConfig) -> list[Diagnostic]:
    """Scan all SKILL.md files under directory against corporate policy."""
    root = Path(root)
    if not root.exists():
        return []

    if root.is_file():
        return audit_policy_skill(root, policy)

    from cinch.check import IGNORED_DIRS

    diagnostics: list[Diagnostic] = []
    for sf in sorted(root.rglob("SKILL.md")):
        try:
            rel = sf.relative_to(root)
        except ValueError:
            rel = sf
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        diagnostics.extend(audit_policy_skill(sf, policy))
    return diagnostics


def is_immutable_ref(ref: str | None) -> bool:
    """Return True if ref is an immutable commit SHA or strict SemVer release tag."""
    if not ref:
        return False
    ref = ref.strip()
    # 40-char or 64-char hex commit hash
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", ref):
        return True
    # SemVer-style release tag (e.g. v1.0.0, 2.1.3, v0.4.0-rc1)
    if re.fullmatch(r"v?\d+(\.\d+)+([a-zA-Z0-9._+-]*)", ref):
        return True
    return False


def _normalize_source_pattern(val: str) -> str:
    cleaned = val.strip().lower()
    for prefix in ("https://", "http://", "git@", "ssh://", "file://", "gh:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    cleaned = cleaned.replace(":", "/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    return cleaned.strip("/")


def matches_source_pattern(source: str, pattern: str) -> bool:
    """Check whether a repository source matches an allow/deny pattern."""
    norm_source = _normalize_source_pattern(source)
    norm_pattern = _normalize_source_pattern(pattern)

    if fnmatch.fnmatchcase(norm_source, norm_pattern):
        return True
    if norm_source.startswith(norm_pattern.rstrip("*").rstrip("/")):
        return True
    return False


def inspect_target_artifacts(target_dir: Path) -> dict[str, Any]:
    """Inspect repository or skill folder statically without executing any code."""
    target_dir = Path(target_dir).resolve()
    license_found = False
    license_type: str | None = None
    skills: list[str] = []
    scripts: list[str] = []
    escapes: list[str] = []

    # Check top-level license files
    for lic_name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "COPYING.md"):
        candidate = target_dir / lic_name
        if candidate.is_file():
            license_found = True
            try:
                first_lines = candidate.read_text(encoding="utf-8", errors="ignore").splitlines()[
                    :5
                ]
                header = " ".join(first_lines).strip()
                if "Apache" in header:
                    license_type = "Apache-2.0"
                elif "MIT" in header:
                    license_type = "MIT"
                elif "BSD" in header:
                    license_type = "BSD"
                elif "GPL" in header:
                    license_type = "GPL"
                else:
                    license_type = "Present"
            except Exception:
                license_type = "Present"
            break

    # Scan directory tree statically without following symlinks
    if target_dir.is_dir():
        for root_str, dirs, files in os.walk(target_dir, followlinks=False):
            root = Path(root_str)
            for item in dirs + files:
                item_path = root / item
                try:
                    rel = item_path.relative_to(target_dir).as_posix()
                except ValueError:
                    rel = str(item_path)

                # 1. Path and symlink escape checks
                if item_path.is_symlink():
                    try:
                        raw_link = os.readlink(item_path)
                        resolved = (item_path.parent / raw_link).resolve()
                        if not str(resolved).startswith(str(target_dir)):
                            escapes.append(
                                f"Symlink '{rel}' points outside target tree: {raw_link}"
                            )
                    except Exception as err:
                        escapes.append(f"Invalid or broken symlink '{rel}': {err}")

                # 2. Executable scripts checks (regular files only)
                if not item_path.is_dir() and not item_path.is_symlink():
                    is_exec_bit = os.access(item_path, os.X_OK)
                    is_script_ext = item_path.suffix.lower() in {
                        ".sh",
                        ".bash",
                        ".py",
                        ".rb",
                        ".js",
                        ".ts",
                        ".zsh",
                    }
                    is_script_dir = any(
                        part in {"scripts", "bin"}
                        for part in item_path.relative_to(target_dir).parts
                    )
                    has_shebang = False
                    if item_path.suffix.lower() not in {
                        ".md",
                        ".json",
                        ".yml",
                        ".yaml",
                        ".toml",
                        ".txt",
                    }:
                        try:
                            with open(item_path, "rb") as f:
                                has_shebang = f.read(2) == b"#!"
                        except Exception:
                            pass

                    non_code_exts = {
                        ".md",
                        ".json",
                        ".yml",
                        ".yaml",
                        ".toml",
                        ".txt",
                        ".lock",
                    }
                    if (is_exec_bit or is_script_ext or is_script_dir or has_shebang) and (
                        item_path.suffix.lower() not in non_code_exts
                    ):
                        scripts.append(rel)

                # 3. Discover skills
                if item == "SKILL.md":
                    skills.append(rel)
                    if not license_found:
                        try:
                            meta, _, _, _, _ = _parse_frontmatter(
                                item_path.read_text(encoding="utf-8", errors="ignore"),
                                item_path,
                            )
                            if "license" in meta:
                                license_found = True
                                license_type = str(meta["license"])
                        except Exception:
                            pass
    elif target_dir.is_file() and target_dir.name == "SKILL.md":
        skills.append(target_dir.name)
        try:
            meta, _, _, _, _ = _parse_frontmatter(
                target_dir.read_text(encoding="utf-8", errors="ignore"), target_dir
            )
            if "license" in meta:
                license_found = True
                license_type = str(meta["license"])
        except Exception:
            pass

    return {
        "license_found": license_found,
        "license_type": license_type,
        "skills": sorted(skills),
        "scripts": sorted(scripts),
        "escapes": sorted(escapes),
    }


@dataclass
class TrustReport:
    target: str
    source: str
    ref: str | None
    commit: str | None
    license_found: bool
    license_type: str | None
    skills: list[str]
    scripts: list[str]
    escapes: list[str]
    is_immutable_ref: bool
    requires_review: bool
    reviewed: bool
    violations: list[str]
    warnings: list[str]
    allowed: bool
    enforce: bool
    locked_commit: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "source": self.source,
            "ref": self.ref,
            "commit": self.commit,
            "locked_commit": self.locked_commit,
            "status": "allowed" if self.allowed else "denied",
            "allowed": self.allowed,
            "enforce": self.enforce,
            "violations": self.violations,
            "warnings": self.warnings,
            "license": {
                "present": self.license_found,
                "type": self.license_type,
            },
            "skills": self.skills,
            "scripts": self.scripts,
            "escapes": self.escapes,
            "is_immutable_ref": self.is_immutable_ref,
            "requires_review": self.requires_review,
            "reviewed": self.reviewed,
        }

    def format_human(self) -> str:
        status_str = "ALLOWED" if self.allowed else "DENIED"
        mode_str = "enforced" if self.enforce else "advisory"
        header = f"Cinch Trust Audit Report: {status_str} ({mode_str})"
        lines = [
            header,
            "=" * len(header),
            f"Source:        {self.source or '(local directory)'}",
            f"Requested ref: {self.ref or '(none)'}",
            f"Commit:        {self.commit or '(none)'}",
        ]
        if self.locked_commit:
            lines.append(f"Locked commit: {self.locked_commit}")
        skills_summary = ", ".join(self.skills) if self.skills else "none"
        scripts_summary = ", ".join(self.scripts) if self.scripts else "none"
        lines.extend(
            [
                f"License:       {self.license_type if self.license_found else 'None found'}",
                f"Skills:        {len(self.skills)} ({skills_summary})",
                f"Scripts:       {len(self.scripts)} ({scripts_summary})",
                f"Escapes:       {len(self.escapes)} detected",
            ]
        )
        if self.violations:
            lines.append("\nPolicy Violations:")
            for v in self.violations:
                lines.append(f"  [X] {v}")
        if self.warnings:
            lines.append("\nAdvisory Warnings:")
            for w in self.warnings:
                lines.append(f"  [!] {w}")
        return "\n".join(lines)


def evaluate_trust_policy(
    target_dir: Path,
    policy: PolicyConfig,
    *,
    source: str = "",
    ref: str | None = None,
    commit: str | None = None,
    locked_commit: str | None = None,
    reviewed: bool = False,
    enforce: bool | None = None,
) -> TrustReport:
    """Evaluate target folder or remote package against trust policy."""
    artifacts = inspect_target_artifacts(target_dir)
    violations: list[str] = []
    warnings: list[str] = []

    # 1. Source allow/deny list
    if source:
        for denied in policy.denied_sources:
            if matches_source_pattern(source, denied):
                violations.append(f"Source '{source}' matches denied pattern '{denied}' in policy.")
                break
        if policy.allowed_sources:
            if not any(
                matches_source_pattern(source, allowed) for allowed in policy.allowed_sources
            ):
                violations.append(f"Source '{source}' is not in allowed sources list.")

    # 2. Path and symlink escapes
    for escape in artifacts["escapes"]:
        violations.append(f"Path escape detected: {escape}")

    # 3. Immutable ref
    immutable = is_immutable_ref(ref)
    if policy.require_immutable_ref:
        if not immutable:
            violations.append(
                f"Ref '{ref or 'unspecified'}' is mutable; "
                "policy requires an immutable commit SHA or SemVer tag."
            )
    elif ref and not immutable:
        warnings.append(f"Ref '{ref}' is a mutable branch/tag; consider pinning to a commit SHA.")

    # 4. Changed upstream commit against locked version
    if locked_commit and commit and locked_commit != commit:
        warnings.append(
            "Upstream commit changed from approved lockfile: "
            f"was {locked_commit[:8]}, now {commit[:8]}"
        )

    # 5. Executable script review
    scripts = artifacts["scripts"]
    requires_review = bool(policy.require_review_for_scripts and scripts)
    if requires_review and not reviewed:
        summary_scripts = ", ".join(scripts[:3]) + ("..." if len(scripts) > 3 else "")
        violations.append(
            f"Package contains {len(scripts)} executable script(s) requiring review "
            f"({summary_scripts}). Pass --reviewed to approve."
        )

    # 6. Mandatory license
    if policy.require_license and not artifacts["license_found"]:
        violations.append("Repository or skill lacks mandatory license metadata.")

    is_enforced = policy.enforce if enforce is None else enforce
    allowed = len(violations) == 0

    return TrustReport(
        target=str(target_dir),
        source=source,
        ref=ref,
        commit=commit,
        locked_commit=locked_commit,
        license_found=artifacts["license_found"],
        license_type=artifacts["license_type"],
        skills=artifacts["skills"],
        scripts=artifacts["scripts"],
        escapes=artifacts["escapes"],
        is_immutable_ref=immutable,
        requires_review=requires_review,
        reviewed=reviewed,
        violations=violations,
        warnings=warnings,
        allowed=allowed,
        enforce=is_enforced,
    )
