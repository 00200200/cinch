<p align="center">
  <img src="assets/banner.svg" alt="cinch — Universal agents for every harness. Init once. Pick Claude Code, Cursor, Codex, Grok, or OpenCode, then pick its skills and agents." width="100%">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2ee6d6" alt="MIT license"></a>
  <a href="https://github.com/00200200/cinch/actions/workflows/ci.yml"><img src="https://github.com/00200200/cinch/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/harnesses-Claude%20Code%20·%20Cursor%20·%20Codex%20·%20Grok%20·%20OpenCode-a371f7" alt="Claude Code, Cursor, Codex, Grok, OpenCode">
  <a href="https://github.com/00200200/cinch/stargazers"><img src="https://img.shields.io/github/stars/00200200/cinch?style=social" alt="GitHub stars"></a>
</p>

# cinch

**Universal agents for every harness.**

One `init`. Pick Claude Code, Cursor, Codex, Grok, OpenCode — or another real
harness on the machine. Cinch lists **that harness’s** skills, agents, hooks,
and commands. You attach the ones you want.

```sh
uvx --from git+https://github.com/00200200/cinch cinch init
```

<p align="center">
  <img src="assets/harnesses.svg" alt="Claude Code, Cursor, Codex, Grok, OpenCode, plus Continue, Aider, Windsurf, Cline, Gemini CLI, GitHub Copilot" width="100%">
</p>

<p align="center">
  <img src="assets/demo.svg" alt="Recorded cinch stdout: cinch harnesses, cinch inventory --harness claude, cinch init attaching humanizer and reviewer" width="860">
</p>

The terminal above is **recorded stdout** from this CLI (`cinch harnesses`,
`cinch inventory --harness claude`, `cinch init --harness claude --skills humanizer --agents reviewer --yes`).

## Install

```sh
uvx --from git+https://github.com/00200200/cinch cinch init
```

```sh
pipx run --spec git+https://github.com/00200200/cinch cinch init
```

PyPI name is `cinch-init` (`cinch` is taken). The command is `cinch`.

## The whole product

```text
cinch init
  → pick a harness
  → pick skills / agents / hooks that harness already has
  → Cinch writes the files that harness expects
```

| Command | What it does |
| --- | --- |
| `cinch harnesses` | Which harnesses Cinch knows, and which are on **this machine** |
| `cinch inventory --harness claude` | Skills, agents, hooks, commands, plugins, MCP **in that harness** |
| `cinch init --harness cursor --skills … --yes` | Attach the selection into this repo |

Non-interactive:

```sh
uvx --from git+https://github.com/00200200/cinch cinch init \
  --harness claude --skills humanizer --agents reviewer --yes
```

`--purpose python|ml|data|web|docs|security|agents` only **filters** that
inventory. It does not replace it.

## How inventory is discovered

Cinch does not scrape a storefront. It looks at binaries on `PATH` and the
directories each product actually uses:

| id | Product | On-disk scan | Project wiring |
| --- | --- | --- | --- |
| `claude` | Claude Code | `~/.claude/{skills,agents,hooks,commands}` | `.claude/…` |
| `cursor` | Cursor | `~/.cursor/{skills,agents,hooks}` | `.cursor/…` |
| `codex` | Codex | `~/.codex/skills`, `~/.codex/agents` | `.agents/skills`, `.codex/agents` |
| `grok` | Grok | `~/.grok/` | `grok-bot/…` |
| `opencode` | OpenCode | `~/.config/opencode`, `~/.opencode` | `.opencode/…` |
| `continue` | Continue | `~/.continue/` | `.continue/…` |
| `aider` | Aider | `~/.aider/` | `.aider/…` |
| `windsurf` | Windsurf | `~/.windsurf/` | `.windsurf/…` |
| `cline` | Cline | `~/.cline/` | `.cline/…`, `.clinerules` |
| `gemini` | Gemini CLI | `~/.gemini/` | `.gemini/…` |
| `copilot` | GitHub Copilot | `~/.copilot/` | `.github/agents`, `prompts` |

A skill is a folder with `SKILL.md`. Agents/commands are markdown (or toml).
MCP servers are keys in the harness JSON. Codex `.system` skills are ignored.
`--from /path/to/checkout` adds another local root; Cinch does not vendor a
second skill library.

`cinch harnesses` on the machine that recorded the demo:

```text
claude      Claude Code       on disk
cursor      Cursor            on disk
codex       Codex             on disk
grok        Grok              —
opencode    OpenCode          on disk
```

`on disk` means the binary or the config dir was found. It is not a live login.

## Limits

- Cinch copies what it can see. It does not start Claude, Cursor, or Codex,
  and it does not grade whether a skill is any good.
- No fake star counts, no telemetry, no CLA.

## License

MIT
