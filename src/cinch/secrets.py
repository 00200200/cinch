"""Zero-leak secret & token scanner for skill content (stdlib only)."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from cinch.check import IGNORED_DIRS, Diagnostic

# Placeholder / example markers that must not raise findings.
_PLACEHOLDER_RE = re.compile(
    r"(?i)("
    r"\$\{[^}]+\}"  # ${API_KEY}
    r"|<(?:YOUR_)?(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD)>"
    r"|\b(?:your|my)[_-]?(?:api[_-]?key|token|secret|password)\b"
    r"|\b(?:example|sample|placeholder|dummy|fake|redacted|changeme)\b"
    r"|sk-(?:example|test|fake|dummy|placeholder|xxxx+)"
    r"|ghp_(?:example|test|fake|dummy|placeholder|xxxx+)"
    r"|sk-ant-(?:example|test|fake|dummy|placeholder)"
    r"|AKIA[0]{16}"
    r")"
)

# Known provider token formats (deliberately length-gated to cut noise).
_TOKEN_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "S001",
        re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
        "Anthropic API key",
    ),
    (
        "S001",
        re.compile(r"\bsk-(?!ant-)[A-Za-z0-9]{20,}\b"),
        "OpenAI-style API key",
    ),
    (
        "S001",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
        "GitHub token",
    ),
    (
        "S001",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
        "GitHub fine-grained PAT",
    ),
    (
        "S001",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "AWS access key ID",
    ),
    (
        "S001",
        re.compile(
            r"\b(?:xox[baprs]|xapp)-[0-9A-Za-z-]{10,}\b",
        ),
        "Slack token",
    ),
    (
        "S001",
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b"),
        "Bearer token",
    ),
]

# Absolute local user home directories.
_USER_PATH_RE = re.compile(
    r"(?:"
    r"(?:/Users|/home)/[A-Za-z0-9._-]+(?:/[^\s`\"')>]*)?"
    r"|"
    r"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+(?:\\[^\s`\"')>]*)?"
    r")"
)

# Candidate high-entropy tokens (base64-ish / hex), excluding short words.
# Allow matches after assignment punctuation (=, :, etc.).
_ENTROPY_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9_/+.-])"
    r"(?:"
    r"[A-Za-z0-9+/]{32,}={0,2}"  # base64
    r"|"
    r"[A-Fa-f0-9]{40,}"  # hex (sha1+)
    r")"
    r"(?![A-Za-z0-9_/+.-])"
)

_MIN_ENTROPY = 4.5
_MIN_ENTROPY_HEX = 3.9


@dataclass(frozen=True)
class SecretFinding:
    path: Path
    line: int
    rule: str
    kind: str
    message: str


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def _is_placeholder(text: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(text))


def _is_benign_match(value: str) -> bool:
    """True when the matched span itself is a documented placeholder."""
    stripped = value.strip("`'\"")
    if _is_placeholder(stripped) or _is_placeholder(value):
        return True
    if stripped.startswith("${") and stripped.endswith("}"):
        return True
    if stripped.startswith("<") and stripped.endswith(">"):
        return True
    # Common fake suffixes after a real-looking prefix.
    lower = stripped.lower()
    for fake in ("example", "sample", "placeholder", "dummy", "fake", "test", "xxxx"):
        if fake in lower:
            return True
    return False


def _redact(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-4:]}"


def _line_number(content: str, index: int) -> int:
    return content.count("\n", 0, index) + 1


def scan_text(content: str, path: Path) -> list[SecretFinding]:
    """Scan raw text for secrets; return findings (no Diagnostics conversion)."""
    findings: list[SecretFinding] = []
    seen: set[tuple[int, str, str]] = set()

    def add(line: int, rule: str, kind: str, message: str) -> None:
        key = (line, rule, message)
        if key in seen:
            return
        seen.add(key)
        findings.append(SecretFinding(path=path, line=line, rule=rule, kind=kind, message=message))

    lines = content.splitlines()
    for line_no, line in enumerate(lines, start=1):
        for rule, pattern, kind in _TOKEN_PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(0)
                if _is_benign_match(value):
                    continue
                add(
                    line_no,
                    rule,
                    kind,
                    f"Possible {kind} '{_redact(value)}'",
                )

        for match in _USER_PATH_RE.finditer(line):
            add(
                line_no,
                "S003",
                "user-path",
                f"Hardcoded user path '{match.group(0)}'",
            )

    # Entropy pass over the full text (line-aware).
    for match in _ENTROPY_CANDIDATE_RE.finditer(content):
        value = match.group(0)
        if _is_benign_match(value):
            continue
        # Skip values already caught as known token formats.
        if any(p.search(value) for _, p, _ in _TOKEN_PATTERNS):
            continue
        # Skip pure dictionary-looking lowercase words glued together (low diversity).
        if value.isalpha() and value.islower():
            continue
        is_hex = bool(re.fullmatch(r"[A-Fa-f0-9]+", value))
        entropy = _shannon_entropy(value)
        threshold = _MIN_ENTROPY_HEX if is_hex else _MIN_ENTROPY
        if entropy < threshold:
            continue
        line_no = _line_number(content, match.start())
        add(
            line_no,
            "S002",
            "high-entropy",
            (f"High-entropy string (entropy={entropy:.2f}) '{_redact(value)}' may be a secret"),
        )

    findings.sort(key=lambda f: (str(f.path), f.line, f.rule, f.message))
    return findings


def findings_to_diagnostics(findings: list[SecretFinding]) -> list[Diagnostic]:
    return [
        Diagnostic(
            path=f.path,
            line=f.line,
            severity="error",
            rule=f.rule,
            message=f.message,
        )
        for f in findings
    ]


def audit_skill(skill_dir_or_file: Path) -> list[Diagnostic]:
    """Audit a single SKILL.md file or skill directory for leaked secrets."""
    path = Path(skill_dir_or_file)
    skill_file = path / "SKILL.md" if path.is_dir() else path
    if not skill_file.is_file():
        return [
            Diagnostic(
                path=skill_file,
                line=None,
                severity="error",
                rule="E001",
                message=f"SKILL.md does not exist at {skill_file}",
            )
        ]
    try:
        content = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [
            Diagnostic(
                path=skill_file,
                line=None,
                severity="error",
                rule="E001",
                message=f"Cannot read SKILL.md at {skill_file}: {exc}",
            )
        ]
    return findings_to_diagnostics(scan_text(content, skill_file))


def audit_directory(root: Path) -> list[Diagnostic]:
    """Recursively audit all SKILL.md files under root for leaked secrets."""
    root = Path(root)
    if not root.exists():
        return [
            Diagnostic(
                path=root / "SKILL.md",
                line=None,
                severity="error",
                rule="E001",
                message=f"Path does not exist: {root}",
            )
        ]
    if root.is_file():
        return audit_skill(root)

    skill_files: list[Path] = []
    for skill_file in sorted(root.rglob("SKILL.md")):
        try:
            rel = skill_file.relative_to(root)
        except ValueError:
            rel = skill_file
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        skill_files.append(skill_file)

    if not skill_files:
        return [
            Diagnostic(
                path=root / "SKILL.md",
                line=None,
                severity="error",
                rule="E001",
                message=f"SKILL.md does not exist in skill directory {root}",
            )
        ]

    diagnostics: list[Diagnostic] = []
    for sf in skill_files:
        diagnostics.extend(audit_skill(sf))
    return diagnostics
