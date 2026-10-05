"""Corporate skill compliance & safety policy enforcement (.cinchpolicy.yml)."""

from __future__ import annotations

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
