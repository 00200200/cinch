"""Dialect adapters for cross-harness translation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from cinch.doc import Doc


@dataclass(frozen=True)
class RenderedFile:
    relpath: str  # Relative to project root
    text: str  # Content to write
    mode: str = "create"  # "create" | "merge"
    support_source: Path | None = None  # Directory to copy if pointer/support files exist
    support_dest: str | None = None  # Relpath destination for support dir


class Adapter(Protocol):
    target: str

    def render(self, doc: Doc) -> tuple[RenderedFile, ...]: ...


def _yaml_quote(val: str) -> str:
    escaped = val.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_frontmatter(fields: dict[str, str | list[str] | bool | None]) -> str:
    lines = ["---"]
    for key, val in fields.items():
        if val is None:
            continue
        if isinstance(val, bool):
            lines.append(f"{key}: {'true' if val else 'false'}")
        elif isinstance(val, (list, tuple)):
            if not val:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in val:
                    lines.append(f"  - {_yaml_quote(str(item))}")
        else:
            lines.append(f"{key}: {_yaml_quote(str(val))}")
    lines.append("---")
    return "\n".join(lines)


class ClaudeAdapter:
    target = "claude"

    def render(self, doc: Doc) -> tuple[RenderedFile, ...]:
        name = doc.name
        if doc.kind == "agent":
            relpath = f".claude/agents/{name}.md"
            if doc.extra_meta:
                fm = _format_frontmatter(doc.extra_meta)
                text = f"{fm}\n\n{doc.body}\n" if doc.body else f"{fm}\n"
            else:
                text = doc.body
            return (RenderedFile(relpath=relpath, text=text),)

        if doc.kind == "command":
            relpath = f".claude/commands/{name}.md"
            if doc.extra_meta:
                fm = _format_frontmatter(doc.extra_meta)
                text = f"{fm}\n\n{doc.body}\n" if doc.body else f"{fm}\n"
            else:
                text = doc.body
            return (RenderedFile(relpath=relpath, text=text),)

        # Skill: .claude/skills/<n>/SKILL.md
        relpath = f".claude/skills/{name}/SKILL.md"
        meta: dict[str, str | list[str] | bool | None] = {
            "name": name,
            "description": doc.description,
        }
        if doc.paths:
            meta["paths"] = list(doc.paths)
        for k, v in doc.extra_meta.items():
            if k not in meta:
                meta[k] = v

        fm = _format_frontmatter(meta)
        text = f"{fm}\n\n{doc.body}\n" if doc.body else f"{fm}\n"

        support_source = doc.support if doc.support else None
        support_dest = f".claude/skills/{name}" if doc.support else None
        return (
            RenderedFile(
                relpath=relpath,
                text=text,
                support_source=support_source,
                support_dest=support_dest,
            ),
        )


class CursorCodexAdapter:
    """Unified adapter for Cursor and Codex (.agents/skills standard)."""

    def __init__(self, target: str = "cursor"):
        self.target = target

    def render(self, doc: Doc) -> tuple[RenderedFile, ...]:
        name = doc.name
        relpath = f".agents/skills/{name}/SKILL.md"

        meta: dict[str, str | list[str] | bool | None] = {
            "name": name,
            "description": doc.description,
        }
        if doc.paths:
            meta["paths"] = list(doc.paths)
        if doc.kind == "command":
            meta["disable-model-invocation"] = True

        fm = _format_frontmatter(meta)
        text = f"{fm}\n\n{doc.body}\n" if doc.body else f"{fm}\n"

        support_source = doc.support if doc.support else None
        support_dest = f".agents/skills/{name}" if doc.support else None
        return (
            RenderedFile(
                relpath=relpath,
                text=text,
                support_source=support_source,
                support_dest=support_dest,
            ),
        )


class ZedAdapter:
    """Adapter for Zed's Agent Skills (the cross-vendor `.agents/skills` standard).

    Zed discovers skills from `~/.agents/skills/<name>/SKILL.md` (global) and
    `<worktree>/.agents/skills/<name>/SKILL.md` (project-local). It documents only
    `name`, `description`, and the optional `disable-model-invocation` frontmatter
    fields, so Cinch emits no `paths`/`globs`.
    """

    target = "zed"

    def render(self, doc: Doc) -> tuple[RenderedFile, ...]:
        name = doc.name
        relpath = f".agents/skills/{name}/SKILL.md"

        meta: dict[str, str | list[str] | bool | None] = {
            "name": name,
            "description": doc.description,
        }
        if doc.kind == "command":
            meta["disable-model-invocation"] = True

        fm = _format_frontmatter(meta)
        text = f"{fm}\n\n{doc.body}\n" if doc.body else f"{fm}\n"

        support_source = doc.support if doc.support else None
        support_dest = f".agents/skills/{name}" if doc.support else None
        return (
            RenderedFile(
                relpath=relpath,
                text=text,
                support_source=support_source,
                support_dest=support_dest,
            ),
        )


class CopilotAdapter:
    target = "copilot"

    def render(self, doc: Doc) -> tuple[RenderedFile, ...]:
        name = doc.name
        if doc.kind in ("agent", "command"):
            relpath = f".github/prompts/{name}.prompt.md"
            fm = _format_frontmatter({"description": doc.description})
            text = f"{fm}\n\n{doc.body}\n" if doc.body else f"{fm}\n"
            return (RenderedFile(relpath=relpath, text=text),)

        # Skill -> .github/instructions/<name>.instructions.md
        relpath = f".github/instructions/{name}.instructions.md"
        apply_to = list(doc.paths) if doc.paths else ["**"]
        fm = _format_frontmatter(
            {
                "applyTo": apply_to,
                "description": doc.description,
            }
        )

        body = doc.body
        files: list[RenderedFile] = []
        if doc.support:
            support_dest = f".cinch/skills/{name}"
            body = (
                f"{body}\n\n"
                f"> Supporting scripts and references are available in `{support_dest}/`.\n"
            )
            files.append(
                RenderedFile(
                    relpath=f"{support_dest}/SKILL.md",
                    text=f"{fm}\n\n{doc.body}\n",
                    support_source=doc.support,
                    support_dest=support_dest,
                )
            )

        text = f"{fm}\n\n{body}\n" if body else f"{fm}\n"
        files.insert(0, RenderedFile(relpath=relpath, text=text))
        return tuple(files)


class GeminiAdapter:
    target = "gemini"

    def render(self, doc: Doc) -> tuple[RenderedFile, ...]:
        name = doc.name
        relpath = f".gemini/commands/{name}.toml"
        desc_escaped = doc.description.replace('"', '\\"')

        # Clean TOML prompt
        prompt_text = doc.body.replace('"""', '\\"\\"\\"')
        if doc.support:
            support_dest = f".cinch/skills/{name}"
            prompt_text += f"\n\nNote: Support assets are located in `{support_dest}/`."

        text = f'description = "{desc_escaped}"\nprompt = """\n{prompt_text}\n"""\n'

        files: list[RenderedFile] = []
        if doc.support:
            support_dest = f".cinch/skills/{name}"
            files.append(
                RenderedFile(
                    relpath=f"{support_dest}/SKILL.md",
                    text=f"# {name}\n\n{doc.body}\n",
                    support_source=doc.support,
                    support_dest=support_dest,
                )
            )

        files.insert(0, RenderedFile(relpath=relpath, text=text))
        return tuple(files)


class WindsurfAdapter:
    target = "windsurf"

    def render(self, doc: Doc) -> tuple[RenderedFile, ...]:
        name = doc.name
        relpath = f".devin/rules/{name}.md"
        meta: dict[str, str | list[str] | bool | None] = {
            "trigger": "manual",
            "description": doc.description,
        }
        if doc.paths:
            meta["globs"] = list(doc.paths)

        fm = _format_frontmatter(meta)

        # 12,000 char limit or support files triggers pointer
        is_large = len(doc.body) > 12000
        if is_large or doc.support:
            support_dest = f".cinch/skills/{name}"
            pointer_body = (
                f"# {name}\n\n"
                f"{doc.description}\n\n"
                f"Full documentation and support files located at `{support_dest}/SKILL.md`.\n"
            )
            files = [
                RenderedFile(relpath=relpath, text=f"{fm}\n\n{pointer_body}"),
                RenderedFile(
                    relpath=f"{support_dest}/SKILL.md",
                    text=f"# {name}\n\n{doc.body}\n",
                    support_source=doc.support,
                    support_dest=support_dest,
                ),
            ]
            return tuple(files)

        text = f"{fm}\n\n{doc.body}\n" if doc.body else f"{fm}\n"
        return (RenderedFile(relpath=relpath, text=text),)


class ClineAdapter:
    target = "cline"

    def render(self, doc: Doc) -> tuple[RenderedFile, ...]:
        name = doc.name
        relpath = f".clinerules/{name}.md"

        lines: list[str] = []
        if doc.paths:
            fm = _format_frontmatter({"paths": list(doc.paths)})
            lines.append(fm)
            lines.append("")

        body = doc.body
        files: list[RenderedFile] = []
        if doc.support:
            support_dest = f".cinch/skills/{name}"
            body += f"\n\nSupporting files located in `{support_dest}/`."
            files.append(
                RenderedFile(
                    relpath=f"{support_dest}/SKILL.md",
                    text=f"# {name}\n\n{doc.body}\n",
                    support_source=doc.support,
                    support_dest=support_dest,
                )
            )

        lines.append(f"# {name}")
        if doc.description:
            lines.append(f"> {doc.description}")
            lines.append("")
        if body:
            lines.append(body)

        files.insert(0, RenderedFile(relpath=relpath, text="\n".join(lines) + "\n"))
        return tuple(files)


class OpenCodeAdapter:
    target = "opencode"

    def render(self, doc: Doc) -> tuple[RenderedFile, ...]:
        name = doc.name
        if doc.kind == "agent":
            relpath = f".opencode/agents/{name}.md"
        else:
            relpath = f".opencode/commands/{name}.md"

        fm = _format_frontmatter({"description": doc.description})
        text = f"{fm}\n\n{doc.body}\n" if doc.body else f"{fm}\n"

        files: list[RenderedFile] = []
        if doc.support:
            support_dest = f".cinch/skills/{name}"
            files.append(
                RenderedFile(
                    relpath=f"{support_dest}/SKILL.md",
                    text=f"# {name}\n\n{doc.body}\n",
                    support_source=doc.support,
                    support_dest=support_dest,
                )
            )

        files.insert(0, RenderedFile(relpath=relpath, text=text))
        return tuple(files)


class AiderAdapter:
    target = "aider"

    def render(self, doc: Doc) -> tuple[RenderedFile, ...]:
        name = doc.name
        doc_relpath = f".aider/{name}.md"
        body = doc.body
        text = f"# {name}\n\n> {doc.description}\n\n{body}\n"

        files: list[RenderedFile] = []
        if doc.support:
            support_dest = f".cinch/skills/{name}"
            files.append(
                RenderedFile(
                    relpath=f"{support_dest}/SKILL.md",
                    text=f"# {name}\n\n{doc.body}\n",
                    support_source=doc.support,
                    support_dest=support_dest,
                )
            )

        files.insert(0, RenderedFile(relpath=doc_relpath, text=text))

        # Merge entry into .aider.conf.yml
        files.append(
            RenderedFile(
                relpath=".aider.conf.yml",
                text=f'read:\n  - "{doc_relpath}"\n',
                mode="merge",
            )
        )
        return tuple(files)


_DOUBLE_BRACE_VAR = re.compile(r"(?<!\{)\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}(?!\})")


def _continue_variables(doc: Doc) -> list[str]:
    """Pull variable names from Cinch frontmatter without inventing new ones."""
    raw = doc.extra_meta.get("variables")
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [str(key) for key in raw]
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple)):
        names: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                names.extend(str(key) for key in item)
            else:
                names.append(str(item))
        return names
    return []


def _hb(name: str) -> str:
    """Continue Handlebars triple-brace token, e.g. {{{ input }}}."""
    return "{{{ " + name + " }}}"


def _continue_prompt_body(doc: Doc) -> str:
    """Body for Continue .prompt files: preserve Handlebars, map {{var}} → {{{ var }}}."""
    body = doc.body or ""
    # Upgrade bare Mustache double-braces to Continue's triple-brace form without
    # touching already-valid {{{ name }}} expressions.
    body = _DOUBLE_BRACE_VAR.sub(lambda m: _hb(m.group(1)), body)

    for name in _continue_variables(doc):
        if name == "input":
            continue
        token = _hb(name)
        compact = "{{{" + name + "}}}"
        if token not in body and compact not in body:
            body = f"{token}\n{body}" if body else f"{token}\n"

    # Classic Continue slash-command context: user text after `/name` lands in {{{ input }}}.
    if _hb("input") not in body and "{{{input}}}" not in body:
        body = f"{_hb('input')}\n\n{body}" if body else f"{_hb('input')}\n"

    if doc.paths:
        globs = ", ".join(doc.paths)
        note = f"<!-- cinch paths: {globs} -->"
        if note not in body:
            body = f"{body.rstrip()}\n\n{note}\n"

    if doc.support:
        support_dest = f".cinch/skills/{doc.name}"
        note = f"Supporting files located in `{support_dest}/`."
        if note not in body:
            body = f"{body.rstrip()}\n\n{note}\n"

    return body if body.endswith("\n") else f"{body}\n"


class ContinueAdapter:
    """Adapter for Continue.dev prompt files and slash commands.

    Skills, agents, and commands compile to `.continue/prompts/<name>.prompt` with
    Continue's prompt frontmatter (`name`, `description`, `invokable`). The body keeps
    Handlebars context variables (`{{{ input }}}`, `{{{ current_file }}}`, …). When a
    project already has `.continue/config.json`, Cinch merges a matching
    `customCommands` shortcut so older Continue installs still expose `/<name>`.
    """

    target = "continue"

    def render(self, doc: Doc) -> tuple[RenderedFile, ...]:
        name = doc.name
        relpath = f".continue/prompts/{name}.prompt"
        prompt_body = _continue_prompt_body(doc)

        meta: dict[str, str | list[str] | bool | None] = {
            "name": name,
            "description": doc.description,
            "invokable": True,
        }
        fm = _format_frontmatter(meta)
        text = f"{fm}\n\n{prompt_body}" if prompt_body.strip() else f"{fm}\n"

        files: list[RenderedFile] = [
            RenderedFile(relpath=relpath, text=text),
        ]

        if doc.support:
            support_dest = f".cinch/skills/{name}"
            files.append(
                RenderedFile(
                    relpath=f"{support_dest}/SKILL.md",
                    text=f"# {name}\n\n{doc.body}\n",
                    support_source=doc.support,
                    support_dest=support_dest,
                )
            )

        # Register slash-command shortcut when config.json already exists (wire skips create).
        command: dict[str, Any] = {
            "name": name,
            "description": doc.description,
            "prompt": prompt_body.rstrip("\n"),
        }
        files.append(
            RenderedFile(
                relpath=".continue/config.json",
                text=json.dumps({"customCommands": [command]}, indent=2) + "\n",
                mode="merge",
            )
        )
        return tuple(files)


ADAPTERS: dict[str, Adapter] = {
    "claude": ClaudeAdapter(),
    "cursor": CursorCodexAdapter("cursor"),
    "codex": CursorCodexAdapter("codex"),
    "copilot": CopilotAdapter(),
    "gemini": GeminiAdapter(),
    "windsurf": WindsurfAdapter(),
    "cline": ClineAdapter(),
    "opencode": OpenCodeAdapter(),
    "aider": AiderAdapter(),
    "zed": ZedAdapter(),
    "continue": ContinueAdapter(),
}


def get_adapter(target: str) -> Adapter:
    if target not in ADAPTERS:
        raise KeyError(f"No adapter available for target harness: {target}")
    return ADAPTERS[target]
