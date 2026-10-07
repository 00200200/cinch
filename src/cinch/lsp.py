"""Language Server Protocol (LSP) for skill frontmatter autocompletion, hover, and diagnostics.

Implements JSON-RPC 2.0 over STDIO with standard Content-Length framing.
Zero external runtime dependencies (stdlib only).
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from typing import Any

from cinch.adapters import ADAPTERS
from cinch.schema import (
    ALLOWED_KEYS,
    KEBAB_CASE_PATTERN,
    MAX_DESCRIPTION_LENGTH,
    MIN_DESCRIPTION_LENGTH,
    REQUIRED_KEYS,
    suggest_key,
)

SERVER_NAME = "cinch-lsp"
SERVER_VERSION = "0.1.0"

# Diagnostic severities (LSP specification)
SEVERITY_ERROR = 1
SEVERITY_WARNING = 2
SEVERITY_INFO = 3
SEVERITY_HINT = 4

# Completion item kinds (LSP specification)
COMPLETION_PROPERTY = 10
COMPLETION_VALUE = 12
COMPLETION_SNIPPET = 15

# Schema documentation for frontmatter fields
SCHEMA_DOCS: dict[str, dict[str, str]] = {
    "name": {
        "detail": "Skill name (required, kebab-case)",
        "doc": (
            "### `name` (required)\n\n"
            "Unique identifier for the skill in kebab-case (e.g. `code-reviewer`).\n\n"
            "- Required by all harnesses.\n"
            "- Validated against pattern: `^[a-z0-9]+(-[a-z0-9]+)*$`.\n"
            "- Claude Code uses this as the skill folder name (`.claude/skills/<name>/SKILL.md`).\n"
            "- Cursor uses this as rule slug (`.cursor/rules/<name>.mdc`).\n"
            "- Zed uses this for slash command (`.zed/prompts/<name>.md`)."
        ),
        "insert": "name: ",
    },
    "description": {
        "detail": "Skill description and invocation triggers (required)",
        "doc": (
            "### `description` (required)\n\n"
            "Human and model-readable summary of what the skill does and when to use it.\n\n"
            f"- Minimum length: {MIN_DESCRIPTION_LENGTH} characters.\n"
            f"- Maximum length: {MAX_DESCRIPTION_LENGTH} characters (Cursor/Windsurf UI limit).\n"
            "- Claude Code: The model inspects this description to choose when to invoke it.\n"
            "- Cursor/Windsurf: Displayed in the rule selection and activation popover."
        ),
        "insert": "description: ",
    },
    "paths": {
        "detail": "File glob patterns that activate this skill",
        "doc": (
            "### `paths`\n\n"
            "List or string of file glob patterns (e.g. `['src/**/*.py']`).\n\n"
            "- Automatically activates the skill when files matching the globs are opened.\n"
            "- Must use forward slashes `/`, never backslashes `\\`.\n"
            "- Supported natively by Cursor (`globs`), Windsurf, and Copilot."
        ),
        "insert": "paths:\n  - ",
    },
    "globs": {
        "detail": "Alias for paths (Cursor MDC / Copilot convention)",
        "doc": (
            "### `globs`\n\n"
            "Cursor MDC / Copilot-style alias for `paths`.\n\n"
            "- Cinch normalizes `globs` and `paths` across all target harnesses.\n"
            "- Must use forward slashes `/`, never backslashes `\\`."
        ),
        "insert": "globs:\n  - ",
    },
    "applyTo": {
        "detail": "Filter by target harness or file pattern",
        "doc": (
            "### `applyTo`\n\n"
            "Restricts this skill to specific target harnesses or file patterns.\n\n"
            "- Supported harnesses: `claude`, `cursor`, `codex`, `copilot`, `gemini`,\n"
            "  `windsurf`, `cline`, `opencode`, `aider`, `zed`, `continue`, `grok`.\n"
            "- If omitted, the skill is universal and wires to all target harnesses."
        ),
        "insert": "applyTo: ",
    },
    "trigger": {
        "detail": "Activation hook event",
        "doc": (
            "### `trigger`\n\n"
            "Event triggering the skill, such as `always`, `manual`, `file-save`, "
            "or `pre-commit`."
        ),
        "insert": "trigger: ",
    },
    "disable-model-invocation": {
        "detail": "Prevent autonomous agent invocation (Claude Code)",
        "doc": (
            "### `disable-model-invocation` (boolean)\n\n"
            "Anthropic Claude Code specification flag.\n\n"
            "- When `true`, prevents the model from autonomously invoking this skill.\n"
            "- The skill can only be invoked by explicit user slash-command request."
        ),
        "insert": "disable-model-invocation: true",
    },
    "parameters": {
        "detail": "Configurable parameters for template substitution",
        "doc": (
            "### `parameters`\n\n"
            "Defines configurable parameters for template substitution.\n\n"
            "Example:\n"
            "```yaml\n"
            "parameters:\n"
            "  target_env:\n"
            "    type: string\n"
            "    default: staging\n"
            "    help: Target deployment environment\n"
            "```"
        ),
        "insert": "parameters:\n  ",
    },
    "requires": {
        "detail": "Skill dependencies",
        "doc": (
            "### `requires`\n\n"
            "List of prerequisite skill names that must be present or wired alongside this skill."
        ),
        "insert": "requires:\n  - ",
    },
    "version": {
        "detail": "Semantic version string",
        "doc": "### `version`\n\nSemantic version of the skill (e.g. `1.0.0`).",
        "insert": "version: 0.1.0",
    },
    "author": {
        "detail": "Skill author or maintainer",
        "doc": "### `author`\n\nAuthor name or email.",
        "insert": "author: ",
    },
    "license": {
        "detail": "SPDX license identifier",
        "doc": "### `license`\n\nSPDX license identifier (e.g. `MIT`, `Apache-2.0`).",
        "insert": "license: MIT",
    },
}

DIALECT_DOCS: dict[str, str] = {
    "claude": (
        "**Anthropic Claude Code**\n\n"
        "Wired into `.claude/skills/<name>/SKILL.md`.\n"
        "Supports autonomous tool invocation and slash commands."
    ),
    "cursor": (
        "**Cursor IDE**\n\n"
        "Wired into `.cursor/rules/<name>.mdc`.\n"
        "Supports glob matching and rule UI activation."
    ),
    "codex": (
        "**Codex**\n\nWired into `.codex/skills/<name>/SKILL.md`.\nSupports agent instruction sets."
    ),
    "copilot": (
        "**GitHub Copilot**\n\n"
        "Wired into `.github/copilot-instructions.md`.\n"
        "Supports repo-level workspace instructions."
    ),
    "gemini": (
        "**Google Gemini CLI**\n\n"
        "Wired into `.gemini/skills/<name>/SKILL.md`.\n"
        "Supports Gemini CLI agent skills."
    ),
    "windsurf": (
        "**Windsurf Cascade**\n\n"
        "Wired into `.windsurf/rules/<name>.md`.\n"
        "Bodies exceeding 12,000 characters require pointer files."
    ),
    "cline": (
        "**Cline**\n\n"
        "Wired into `.cline/skills/<name>/SKILL.md`.\n"
        "Supports Cline memory bank and skills."
    ),
    "opencode": (
        "**OpenCode**\n\n"
        "Wired into `.opencode/skills/<name>/SKILL.md`.\n"
        "Supports OpenCode agent tools."
    ),
    "aider": (
        "**Aider**\n\nWired into `.aider.conventions.md`.\nSupports Aider coding conventions."
    ),
    "zed": (
        "**Zed Editor**\n\n"
        "Wired into `.zed/prompts/<name>.md`.\n"
        "Supports slash-command prompt templates."
    ),
    "continue": (
        "**Continue.dev**\n\n"
        "Wired into `.continue/prompts/<name>.prompt`.\n"
        "Supports Continue prompt shortcuts."
    ),
    "grok": (
        "**Grok**\n\nWired into `.grok/skills/<name>/SKILL.md`.\nSupports Grok AI agent skills."
    ),
}

DIALECT_NAMES = tuple(sorted(ADAPTERS.keys()))

_WORD_PATTERN = re.compile(r"[a-zA-Z0-9_\-]+")


def _unquote(val: str) -> str:
    s = val.strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1]
    return s


def parse_diagnostics(content: str, *, strict: bool = False) -> list[dict[str, Any]]:
    """Parse skill document content and return LSP Diagnostic objects."""
    lines = content.splitlines()
    if not lines:
        return []

    if lines[0].strip() != "---":
        return [
            {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": len(lines[0])},
                },
                "severity": SEVERITY_ERROR,
                "code": "E002",
                "source": "cinch",
                "message": "Missing YAML frontmatter (file must start with '---')",
            }
        ]

    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx == -1:
        return [
            {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 3},
                },
                "severity": SEVERITY_ERROR,
                "code": "E002",
                "source": "cinch",
                "message": "Unclosed YAML frontmatter (missing closing '---')",
            }
        ]

    diagnostics: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    current_key: str | None = None

    for idx in range(1, end_idx):
        raw_line = lines[idx]
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if "\t" in raw_line:
            col = raw_line.index("\t")
            diagnostics.append(
                {
                    "range": {
                        "start": {"line": idx, "character": col},
                        "end": {"line": idx, "character": col + 1},
                    },
                    "severity": SEVERITY_ERROR,
                    "code": "E002",
                    "source": "cinch",
                    "message": "Tabs are not allowed for indentation in YAML frontmatter",
                }
            )
            continue

        if stripped.startswith("-"):
            # List item
            if not stripped.startswith("- "):
                diagnostics.append(
                    {
                        "range": {
                            "start": {"line": idx, "character": 0},
                            "end": {"line": idx, "character": len(raw_line)},
                        },
                        "severity": SEVERITY_ERROR,
                        "code": "E002",
                        "source": "cinch",
                        "message": "Missing space after '-' in list item",
                    }
                )
                continue

            item_val = _unquote(stripped[2:].strip())
            if current_key in ("paths", "globs"):
                if "\\" in item_val:
                    diagnostics.append(
                        {
                            "range": {
                                "start": {"line": idx, "character": 0},
                                "end": {"line": idx, "character": len(raw_line)},
                            },
                            "severity": SEVERITY_WARNING,
                            "code": "W004",
                            "source": "cinch",
                            "message": (
                                f"Invalid path glob pattern '{item_val}': "
                                "contains backslashes (use forward slashes)"
                            ),
                        }
                    )
                else:
                    try:
                        fnmatch.translate(item_val)
                    except Exception as exc:
                        diagnostics.append(
                            {
                                "range": {
                                    "start": {"line": idx, "character": 0},
                                    "end": {"line": idx, "character": len(raw_line)},
                                },
                                "severity": SEVERITY_WARNING,
                                "code": "W004",
                                "source": "cinch",
                                "message": f"Invalid path glob pattern '{item_val}': {exc}",
                            }
                        )
            continue

        if ":" not in stripped:
            diagnostics.append(
                {
                    "range": {
                        "start": {"line": idx, "character": 0},
                        "end": {"line": idx, "character": len(raw_line)},
                    },
                    "severity": SEVERITY_ERROR,
                    "code": "E002",
                    "source": "cinch",
                    "message": (
                        f"Invalid YAML frontmatter syntax: expected 'key: value', got '{stripped}'"
                    ),
                }
            )
            continue

        key_part, _, val_part = stripped.partition(":")
        key = key_part.strip()
        val = val_part.strip()
        current_key = key
        seen_keys.add(key)

        key_start = raw_line.find(key)
        key_end = key_start + len(key)

        # Check for unrecognized frontmatter keys
        if key not in ALLOWED_KEYS:
            suggestion = suggest_key(key)
            hint_str = f" Did you mean '{suggestion}'?" if suggestion else ""
            diagnostics.append(
                {
                    "range": {
                        "start": {"line": idx, "character": key_start},
                        "end": {"line": idx, "character": key_end},
                    },
                    "severity": SEVERITY_ERROR if strict else SEVERITY_WARNING,
                    "code": "E005",
                    "source": "cinch",
                    "message": f"Unrecognized frontmatter key '{key}'.{hint_str}",
                }
            )

        # Check name field
        if key == "name":
            name_val = _unquote(val)
            if not name_val:
                diagnostics.append(
                    {
                        "range": {
                            "start": {"line": idx, "character": key_start},
                            "end": {"line": idx, "character": len(raw_line)},
                        },
                        "severity": SEVERITY_ERROR,
                        "code": "E003",
                        "source": "cinch",
                        "message": "Missing 'name' in frontmatter or empty name",
                    }
                )
            elif not KEBAB_CASE_PATTERN.match(name_val):
                diagnostics.append(
                    {
                        "range": {
                            "start": {"line": idx, "character": key_start},
                            "end": {"line": idx, "character": len(raw_line)},
                        },
                        "severity": SEVERITY_WARNING,
                        "code": "W001",
                        "source": "cinch",
                        "message": (
                            f"Skill name '{name_val}' is not valid kebab-case "
                            "(expected ^[a-z0-9]+(-[a-z0-9]+)*$)"
                        ),
                    }
                )

        # Check description field
        if key == "description":
            desc_val = _unquote(val)
            if not desc_val or len(desc_val) < MIN_DESCRIPTION_LENGTH:
                diagnostics.append(
                    {
                        "range": {
                            "start": {"line": idx, "character": key_start},
                            "end": {"line": idx, "character": len(raw_line)},
                        },
                        "severity": SEVERITY_ERROR if strict else SEVERITY_WARNING,
                        "code": "W002" if not strict else "E004",
                        "source": "cinch",
                        "message": (
                            "Description missing or shorter than "
                            f"{MIN_DESCRIPTION_LENGTH} characters"
                        ),
                    }
                )
            elif len(desc_val) > MAX_DESCRIPTION_LENGTH:
                diagnostics.append(
                    {
                        "range": {
                            "start": {"line": idx, "character": key_start},
                            "end": {"line": idx, "character": len(raw_line)},
                        },
                        "severity": SEVERITY_ERROR,
                        "code": "E007",
                        "source": "cinch",
                        "message": (
                            f"Description exceeds {MAX_DESCRIPTION_LENGTH} characters "
                            "(Cursor/Windsurf dialect limit)"
                        ),
                    }
                )

        # Check inline glob patterns
        if key in ("paths", "globs") and val:
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1]
                patterns = [_unquote(p.strip()) for p in inner.split(",") if p.strip()]
            else:
                patterns = [_unquote(val)]
            for pat in patterns:
                if "\\" in pat:
                    diagnostics.append(
                        {
                            "range": {
                                "start": {"line": idx, "character": key_start},
                                "end": {"line": idx, "character": len(raw_line)},
                            },
                            "severity": SEVERITY_WARNING,
                            "code": "W004",
                            "source": "cinch",
                            "message": (
                                f"Invalid path glob pattern '{pat}': "
                                "contains backslashes (use forward slashes)"
                            ),
                        }
                    )

    # Check for missing required keys
    for req in REQUIRED_KEYS:
        if req not in seen_keys:
            code = "E003" if req == "name" else ("E004" if strict else "W002")
            diagnostics.append(
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 3},
                    },
                    "severity": SEVERITY_ERROR if code.startswith("E") else SEVERITY_WARNING,
                    "code": code,
                    "source": "cinch",
                    "message": f"Missing required frontmatter key '{req}'",
                }
            )

    return diagnostics


class LspServer:
    """Lightweight stdio Language Server Protocol (LSP) server for skill files."""

    def __init__(self, *, strict: bool = False) -> None:
        self.strict = strict
        self.documents: dict[str, str] = {}
        self.is_shutdown: bool = False

    def handle_message(
        self, msg: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Handle a single LSP request or notification.

        Returns (response_or_None, outgoing_notifications).
        """
        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}

        # 1. Lifecycle: initialize
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "capabilities": {
                        "textDocumentSync": {
                            "openClose": True,
                            "change": 1,  # TextDocumentSyncKind.Full
                        },
                        "completionProvider": {
                            "resolveProvider": False,
                            "triggerCharacters": [":", " ", "\n", "-", '"', "'"],
                        },
                        "hoverProvider": True,
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                },
            }, []

        # 2. Lifecycle: initialized (notification)
        if method == "initialized":
            return None, []

        # 3. Lifecycle: shutdown
        if method == "shutdown":
            self.is_shutdown = True
            return {"jsonrpc": "2.0", "id": req_id, "result": None}, []

        # 4. Lifecycle: exit (notification)
        if method == "exit":
            return None, []

        # 5. Document sync: didOpen
        if method == "textDocument/didOpen":
            doc_item = params.get("textDocument") or {}
            uri = doc_item.get("uri", "")
            text = doc_item.get("text", "")
            self.documents[uri] = text
            diags = parse_diagnostics(text, strict=self.strict)
            return None, [
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/publishDiagnostics",
                    "params": {"uri": uri, "diagnostics": diags},
                }
            ]

        # 6. Document sync: didChange
        if method == "textDocument/didChange":
            doc_item = params.get("textDocument") or {}
            uri = doc_item.get("uri", "")
            changes = params.get("contentChanges") or []
            if changes:
                text = changes[-1].get("text", "")
                self.documents[uri] = text
                diags = parse_diagnostics(text, strict=self.strict)
                return None, [
                    {
                        "jsonrpc": "2.0",
                        "method": "textDocument/publishDiagnostics",
                        "params": {"uri": uri, "diagnostics": diags},
                    }
                ]
            return None, []

        # 7. Document sync: didClose
        if method == "textDocument/didClose":
            doc_item = params.get("textDocument") or {}
            uri = doc_item.get("uri", "")
            self.documents.pop(uri, None)
            return None, [
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/publishDiagnostics",
                    "params": {"uri": uri, "diagnostics": []},
                }
            ]

        # 8. Feature: completion
        if method == "textDocument/completion":
            doc_item = params.get("textDocument") or {}
            uri = doc_item.get("uri", "")
            pos = params.get("position") or {"line": 0, "character": 0}
            items = self._get_completions(uri, pos)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"isIncomplete": False, "items": items},
            }, []

        # 9. Feature: hover
        if method == "textDocument/hover":
            doc_item = params.get("textDocument") or {}
            uri = doc_item.get("uri", "")
            pos = params.get("position") or {"line": 0, "character": 0}
            hover_res = self._get_hover(uri, pos)
            return {"jsonrpc": "2.0", "id": req_id, "result": hover_res}, []

        # Unhandled request
        if req_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }, []

        return None, []

    def _get_completions(self, uri: str, pos: dict[str, Any]) -> list[dict[str, Any]]:
        content = self.documents.get(uri, "")
        lines = content.splitlines() if content else []
        line_idx = pos.get("line", 0)
        char_idx = pos.get("character", 0)
        curr_line = lines[line_idx] if line_idx < len(lines) else ""
        prefix = curr_line[:char_idx]

        # 1. Empty doc or line 0 without frontmatter: snippet completion
        if not lines or (line_idx == 0 and not curr_line.startswith("---")):
            return [
                {
                    "label": "frontmatter",
                    "kind": COMPLETION_SNIPPET,
                    "detail": "Insert SKILL.md frontmatter template",
                    "documentation": {
                        "kind": "markdown",
                        "value": (
                            "Inserts standard `name` and `description` YAML frontmatter block."
                        ),
                    },
                    "insertText": (
                        "---\nname: ${1:skill-name}\ndescription: ${2:Skill description}\n---\n\n$0"
                    ),
                }
            ]

        # Check frontmatter range
        end_idx = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break

        # Outside frontmatter: no frontmatter completions
        if end_idx != -1 and line_idx > end_idx:
            return []

        # Inside frontmatter: value completion vs key completion
        stripped_prefix = prefix.strip()

        # Value completion for applyTo:
        if prefix.lstrip().startswith("applyTo:") or (
            curr_line.lstrip().startswith("applyTo:") and ":" in prefix
        ):
            return [
                {
                    "label": name,
                    "kind": COMPLETION_VALUE,
                    "detail": f"Target harness: {name}",
                    "documentation": {"kind": "markdown", "value": DIALECT_DOCS.get(name, "")},
                    "insertText": name,
                }
                for name in DIALECT_NAMES
            ]

        # Value completion for disable-model-invocation:
        if prefix.lstrip().startswith("disable-model-invocation:") or (
            curr_line.lstrip().startswith("disable-model-invocation:") and ":" in prefix
        ):
            return [
                {
                    "label": "true",
                    "kind": COMPLETION_VALUE,
                    "detail": "Disable autonomous model invocation",
                    "insertText": "true",
                },
                {
                    "label": "false",
                    "kind": COMPLETION_VALUE,
                    "detail": "Allow autonomous model invocation",
                    "insertText": "false",
                },
            ]

        # Value completion for trigger:
        if prefix.lstrip().startswith("trigger:") or (
            curr_line.lstrip().startswith("trigger:") and ":" in prefix
        ):
            triggers = ["always", "manual", "file-save", "pre-commit"]
            return [
                {
                    "label": tr,
                    "kind": COMPLETION_VALUE,
                    "detail": f"Activation trigger: {tr}",
                    "insertText": tr,
                }
                for tr in triggers
            ]

        # List item completion under paths / globs
        if stripped_prefix == "-" or stripped_prefix.startswith("- "):
            # Find parent key scanning upwards
            parent_key = None
            for prev_idx in range(line_idx - 1, 0, -1):
                prev_line = lines[prev_idx].strip()
                if ":" in prev_line and not prev_line.startswith("-"):
                    parent_key = prev_line.split(":", 1)[0].strip()
                    break

            if parent_key in ("paths", "globs"):
                sample_globs = [
                    '"**/*.py"',
                    '"**/*.ts"',
                    '"**/*.js"',
                    '"**/*.go"',
                    '"**/*.rs"',
                    '"**/*"',
                ]
                return [
                    {
                        "label": g,
                        "kind": COMPLETION_VALUE,
                        "detail": f"Glob pattern: {g}",
                        "insertText": g,
                    }
                    for g in sample_globs
                ]
            if parent_key == "applyTo":
                return [
                    {
                        "label": name,
                        "kind": COMPLETION_VALUE,
                        "detail": f"Target harness: {name}",
                        "documentation": {"kind": "markdown", "value": DIALECT_DOCS.get(name, "")},
                        "insertText": name,
                    }
                    for name in DIALECT_NAMES
                ]

        # Key completion: show all allowed frontmatter keys
        items: list[dict[str, Any]] = []
        ordered_keys = [
            "name",
            "description",
            "paths",
            "globs",
            "applyTo",
            "trigger",
            "disable-model-invocation",
            "parameters",
            "requires",
            "version",
            "author",
            "license",
        ]
        for key in ordered_keys:
            meta = SCHEMA_DOCS.get(key, {})
            items.append(
                {
                    "label": key,
                    "kind": COMPLETION_PROPERTY,
                    "detail": meta.get("detail", key),
                    "documentation": {"kind": "markdown", "value": meta.get("doc", "")},
                    "insertText": meta.get("insert", f"{key}: "),
                }
            )
        return items

    def _get_hover(self, uri: str, pos: dict[str, Any]) -> dict[str, Any] | None:
        content = self.documents.get(uri, "")
        lines = content.splitlines() if content else []
        line_idx = pos.get("line", 0)
        char_idx = pos.get("character", 0)
        if line_idx >= len(lines):
            return None

        line = lines[line_idx]
        if not line:
            return None

        # Find word under cursor
        target_word: str | None = None
        for m in _WORD_PATTERN.finditer(line):
            if m.start() <= char_idx <= m.end():
                target_word = m.group(0)
                break

        if not target_word:
            return None

        # 1. Frontmatter key hover
        if target_word in SCHEMA_DOCS:
            doc_text = SCHEMA_DOCS[target_word]["doc"]
            return {"contents": {"kind": "markdown", "value": doc_text}}

        # 2. Dialect name hover
        if target_word in DIALECT_DOCS:
            doc_text = DIALECT_DOCS[target_word]
            return {"contents": {"kind": "markdown", "value": doc_text}}

        # 3. Known alias suggestion hover
        suggested = suggest_key(target_word)
        if suggested and suggested in SCHEMA_DOCS:
            msg = (
                f"### `{target_word}` (unrecognized key)\n\n"
                f"Did you mean **`{suggested}`**?\n\n"
                f"{SCHEMA_DOCS[suggested]['doc']}"
            )
            return {"contents": {"kind": "markdown", "value": msg}}

        return None

    def run_stdio(self, in_stream: Any = None, out_stream: Any = None) -> int:
        """Run standard Content-Length or NDJSON framed JSON-RPC loop over stdio."""
        if in_stream is None:
            stream_in = getattr(sys.stdin, "buffer", sys.stdin)
        else:
            stream_in = in_stream

        if out_stream is None:
            stream_out = getattr(sys.stdout, "buffer", sys.stdout)
        else:
            stream_out = out_stream

        while not self.is_shutdown:
            raw_line = stream_in.readline()
            if not raw_line:
                break

            line_str = (
                raw_line.decode("utf-8", errors="replace")
                if isinstance(raw_line, bytes)
                else raw_line
            )
            stripped = line_str.strip()
            if not stripped:
                continue

            # Standard LSP Content-Length framing
            if stripped.lower().startswith("content-length:"):
                try:
                    length = int(stripped.split(":", 1)[1].strip())
                    # Consume remaining headers until empty line
                    while True:
                        hdr = stream_in.readline()
                        hdr_str = (
                            hdr.decode("utf-8", errors="replace") if isinstance(hdr, bytes) else hdr
                        )
                        if not hdr_str or not hdr_str.strip():
                            break
                    body_raw = stream_in.read(length)
                    body_str = (
                        body_raw.decode("utf-8", errors="replace")
                        if isinstance(body_raw, bytes)
                        else body_raw
                    )
                    req = json.loads(body_str)
                except Exception:
                    continue
            else:
                try:
                    req = json.loads(stripped)
                except json.JSONDecodeError:
                    continue

            resp, notifications = self.handle_message(req)
            to_send = list(notifications)
            if resp is not None:
                to_send.insert(0, resp)

            for payload in to_send:
                body_bytes = json.dumps(payload, separators=(",", ":")).encode()
                header_bytes = f"Content-Length: {len(body_bytes)}\r\n\r\n".encode()
                packet = header_bytes + body_bytes
                try:
                    stream_out.write(packet)
                except TypeError:
                    stream_out.write(packet.decode("utf-8"))
                stream_out.flush()

        return 0
