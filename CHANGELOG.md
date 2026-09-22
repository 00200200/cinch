# Changelog

All notable changes to Cinch are documented in this file.  
Format follows [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- Cursor inventory now scans the shared `~/.agents/skills` layout used with Codex
- Harness detection treats project `.agents/` as a Cursor presence marker
- Source auto-detect (`--from-harness` omitted) considers project markers, not only `$HOME`
- Skill discovery finds nested `**/SKILL.md` packages and single-skill `--from-dir` roots
- Multi-harness machines require `--from-harness` when cross-wiring (same-harness `--harness` still works)
- Respect `NO_COLOR` and `FORCE_COLOR=0`/`false` for plain CLI output. Rich treats any non-empty `FORCE_COLOR` (including `0`) as a TTY, which broke scripted/demo stdout and pytest captures under `FORCE_COLOR=0`.

### Added
- `cinch check [path]` — comprehensive skill linter & validator verifying YAML frontmatter, naming conventions, path globs, and Windsurf size constraints with Rich diagnostics table
- `cinch diff [project]` — workspace drift detector comparing on-disk files against source translations with syntax-highlighted unified diffs
- Bundled starter skills (`--starter`) — 4 curated starter skills (`humanizer`, `security-auditor`, `test-writer`, `git-commit`) shipping directly inside the package
- Interactive starter skills onboarding prompt when no existing local skills are detected
- Standalone benchmark suite (`benchmark/run.py`) demonstrating >500,000 dialects/sec translation throughput
- Direct skill folder scanning support for `--from-dir`
- `cinch-init` entrypoint script alias for zero-config `uvx cinch-init` execution

## [0.1.0] — 2025-09-20

### Added
- **Cross-harness translation engine** — author skills once, wire to 9 harness dialects
- 9 native dialect adapters: Claude Code, Cursor, Codex, GitHub Copilot, Gemini CLI, Windsurf, Cline, OpenCode, Aider
- Canonical `Doc` intermediate representation with frontmatter parser
- `cinch init` — interactive wizard and non-interactive batch wiring
- `cinch harnesses` — list detected harnesses on the local machine
- `cinch inventory` — inspect skills, agents, hooks, and commands per harness
- Multi-target `--harness cursor,copilot,gemini` comma-separated targeting
- `--from-harness` source selection for cross-harness translation
- `--from-dir` support for external skill repositories
- `.cinch.json` execution audit manifest for every init run
- Inline vs. pointer rule: automatic fallback for large skills or support directories
- Aider `.aider.conf.yml` config merge support
- Interactive TUI with `questionary` for harness and skill selection
- Zero telemetry, 100% local-first execution
- CI with multi-Python matrix (3.11, 3.12, 3.13) and ruff linting
- CONTRIBUTING.md, SECURITY.md, MIT License

[Unreleased]: https://github.com/00200200/cinch/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/00200200/cinch/releases/tag/v0.1.0
