"""Harness layouts, purpose tags, and toolchain markers."""

from __future__ import annotations

from dataclasses import dataclass

HARNESS_ORDER = (
    "claude",
    "cursor",
    "codex",
    "copilot",
    "gemini",
    "windsurf",
    "cline",
    "opencode",
    "aider",
)

PLANNED_HARNESSES = (
    "grok",
    "continue",
)

PURPOSES = ("python", "ml", "data", "web", "docs", "security", "agents")

PURPOSE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "python": ("python", "ruff", "pytest", "humanize", "humanizer"),
    "ml": ("ml", "train", "torch", "repro", "humanize", "humanizer"),
    "data": ("data", "ml", "repro", "notebook"),
    "web": ("web", "frontend", "ux"),
    "docs": (
        "doc",
        "readme",
        "humanize",
        "humanizer",
        "write",
        "source-change",
        "skill-watch",
    ),
    "security": ("security", "secret", "hack", "paranoid"),
    "agents": ("agent", "skill-watch", "harness"),
}

TOOLCHAINS = ("uv", "poetry", "pip", "npm", "pnpm", "yarn", "bun", "cargo", "go", "generic")


@dataclass(frozen=True)
class HarnessSpec:
    id: str
    title: str
    binaries: tuple[str, ...]
    home_markers: tuple[str, ...]
    project_markers: tuple[str, ...]
    skill_sources: tuple[str, ...]
    agent_sources: tuple[str, ...]
    hook_sources: tuple[str, ...]
    command_sources: tuple[str, ...]
    plugin_sources: tuple[str, ...]
    mcp_sources: tuple[str, ...]
    project_dirs: dict[str, str]


def _spec(
    harness_id: str,
    title: str,
    *,
    binaries: tuple[str, ...] = (),
    home_markers: tuple[str, ...] = (),
    project_markers: tuple[str, ...] = (),
    skill_sources: tuple[str, ...] = (),
    agent_sources: tuple[str, ...] = (),
    hook_sources: tuple[str, ...] = (),
    command_sources: tuple[str, ...] = (),
    plugin_sources: tuple[str, ...] = (),
    mcp_sources: tuple[str, ...] = (),
    project_dirs: dict[str, str] | None = None,
) -> HarnessSpec:
    return HarnessSpec(
        id=harness_id,
        title=title,
        binaries=binaries,
        home_markers=home_markers,
        project_markers=project_markers,
        skill_sources=skill_sources,
        agent_sources=agent_sources,
        hook_sources=hook_sources,
        command_sources=command_sources,
        plugin_sources=plugin_sources,
        mcp_sources=mcp_sources,
        project_dirs=project_dirs or {},
    )


HARNESSES: dict[str, HarnessSpec] = {
    "claude": _spec(
        "claude",
        "Claude Code",
        binaries=("claude",),
        home_markers=(".claude",),
        project_markers=(".claude",),
        skill_sources=("{home}/.claude/skills",),
        agent_sources=("{home}/.claude/agents",),
        hook_sources=("{home}/.claude/hooks",),
        command_sources=("{home}/.claude/commands",),
        plugin_sources=("{home}/.claude/plugins",),
        mcp_sources=("{home}/.claude/settings.json", "{home}/.claude/settings.local.json"),
        project_dirs={
            "skill": ".claude/skills",
            "agent": ".claude/agents",
            "hook": ".claude/hooks",
            "command": ".claude/commands",
            "plugin": ".claude-plugin",
        },
    ),
    "cursor": _spec(
        "cursor",
        "Cursor",
        binaries=("cursor",),
        home_markers=(".cursor",),
        project_markers=(".cursor", ".agents"),
        skill_sources=("{home}/.cursor/skills", "{home}/.agents/skills"),
        agent_sources=("{home}/.cursor/agents",),
        hook_sources=("{home}/.cursor/hooks.json", "{home}/.cursor/hooks"),
        command_sources=("{home}/.cursor/commands", "{home}/.cursor/rules"),
        plugin_sources=("{home}/.cursor/plugins",),
        mcp_sources=("{home}/.cursor/mcp.json",),
        project_dirs={
            "skill": ".agents/skills",
            "agent": ".agents/skills",
            "hook": ".cursor/hooks",
            "command": ".cursor/rules",
            "plugin": ".cursor/plugins",
        },
    ),
    "codex": _spec(
        "codex",
        "Codex",
        binaries=("codex",),
        home_markers=(".codex",),
        project_markers=(".codex", ".agents"),
        skill_sources=("{home}/.codex/skills", "{home}/.agents/skills"),
        agent_sources=("{home}/.codex/agents",),
        hook_sources=("{home}/.codex/hooks",),
        command_sources=("{home}/.codex/prompts",),
        plugin_sources=("{home}/.codex/plugins",),
        mcp_sources=("{home}/.codex/config.toml",),
        project_dirs={
            "skill": ".agents/skills",
            "agent": ".agents/skills",
            "hook": ".codex/hooks",
            "command": ".agents/skills",
            "plugin": ".codex/plugins",
        },
    ),
    "copilot": _spec(
        "copilot",
        "GitHub Copilot",
        binaries=("copilot",),
        home_markers=(".copilot",),
        project_markers=(".github/copilot-instructions.md", ".github/instructions"),
        skill_sources=("{home}/.copilot/skills",),
        agent_sources=("{home}/.copilot/agents",),
        command_sources=("{home}/.copilot/prompts",),
        project_dirs={
            "skill": ".github/instructions",
            "agent": ".github/prompts",
            "command": ".github/prompts",
        },
    ),
    "gemini": _spec(
        "gemini",
        "Gemini CLI",
        binaries=("gemini",),
        home_markers=(".gemini",),
        project_markers=(".gemini", "GEMINI.md"),
        skill_sources=("{home}/.gemini/skills",),
        agent_sources=("{home}/.gemini/agents",),
        command_sources=("{home}/.gemini/commands",),
        mcp_sources=("{home}/.gemini/settings.json",),
        project_dirs={
            "skill": ".gemini/commands",
            "agent": ".gemini/commands",
            "command": ".gemini/commands",
        },
    ),
    "windsurf": _spec(
        "windsurf",
        "Windsurf",
        binaries=("windsurf",),
        home_markers=(".codeium/windsurf", ".windsurf"),
        project_markers=(".windsurf", ".devin/rules", ".windsurfrules"),
        skill_sources=("{home}/.codeium/windsurf/skills", "{home}/.windsurf/skills"),
        agent_sources=("{home}/.codeium/windsurf/agents",),
        command_sources=("{home}/.codeium/windsurf/rules", "{home}/.windsurf/rules"),
        project_dirs={
            "skill": ".devin/rules",
            "agent": ".devin/rules",
            "command": ".devin/rules",
        },
    ),
    "cline": _spec(
        "cline",
        "Cline",
        binaries=("cline",),
        home_markers=(".cline",),
        project_markers=(".cline", ".clinerules"),
        skill_sources=("{home}/.cline/skills",),
        agent_sources=("{home}/.cline/agents",),
        command_sources=("{home}/.cline/rules",),
        project_dirs={
            "skill": ".clinerules",
            "agent": ".clinerules",
            "command": ".clinerules",
        },
    ),
    "opencode": _spec(
        "opencode",
        "OpenCode",
        binaries=("opencode",),
        home_markers=(".config/opencode", ".opencode"),
        project_markers=(".opencode",),
        skill_sources=("{home}/.config/opencode/skills", "{home}/.opencode/skills"),
        agent_sources=("{home}/.config/opencode/agents", "{home}/.opencode/agents"),
        hook_sources=("{home}/.config/opencode/hooks", "{home}/.opencode/hooks"),
        command_sources=("{home}/.config/opencode/commands", "{home}/.opencode/commands"),
        mcp_sources=("{home}/.config/opencode/mcp.json", "{home}/.opencode/mcp.json"),
        project_dirs={
            "skill": ".opencode/commands",
            "agent": ".opencode/agents",
            "hook": ".opencode/hooks",
            "command": ".opencode/commands",
        },
    ),
    "aider": _spec(
        "aider",
        "Aider",
        binaries=("aider",),
        home_markers=(".aider",),
        project_markers=(".aider.conf.yml", "CONVENTIONS.md"),
        skill_sources=("{home}/.aider/skills",),
        command_sources=("{home}/.aider/conventions",),
        project_dirs={
            "skill": ".aider",
            "command": ".aider",
        },
    ),
    # Planned / Experimental harnesses (spec unverified)
    "grok": _spec(
        "grok",
        "Grok",
        binaries=("grok",),
        home_markers=(".grok",),
        project_markers=("grok-bot", ".grok"),
        skill_sources=("{home}/.grok/skills",),
        agent_sources=("{home}/.grok/agents",),
        hook_sources=("{home}/.grok/hooks",),
        command_sources=("{home}/.grok/prompts",),
        project_dirs={
            "skill": "grok-bot/skills",
            "agent": "grok-bot/agents",
            "hook": "grok-bot/hooks",
            "command": "grok-bot/prompts",
        },
    ),
    "continue": _spec(
        "continue",
        "Continue",
        binaries=("continue",),
        home_markers=(".continue",),
        project_markers=(".continue",),
        skill_sources=("{home}/.continue/skills",),
        agent_sources=("{home}/.continue/agents",),
        hook_sources=("{home}/.continue/hooks",),
        command_sources=("{home}/.continue/prompts", "{home}/.continue/rules"),
        mcp_sources=("{home}/.continue/config.json",),
        project_dirs={
            "skill": ".continue/skills",
            "agent": ".continue/agents",
            "hook": ".continue/hooks",
            "command": ".continue/rules",
        },
    ),
}


def tags_for(name: str) -> frozenset[str]:
    lowered = name.lower()
    return frozenset(
        purpose for purpose, keys in PURPOSE_KEYWORDS.items() if any(key in lowered for key in keys)
    )
