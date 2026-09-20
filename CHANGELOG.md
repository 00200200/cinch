# Changelog

All notable changes to Cinch are documented in this file.  
Format follows [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `cinch preview <skill> --target <harness>` — render a skill in any dialect without writing files
- `cinch status` — verify wired file integrity and sync state from `.cinch.json` manifest
- Conformance test suite with vendor documentation citations for all 9 harness adapters
- Rich terminal output with colored tables, panels, and status indicators
- GitHub Actions release workflow for PyPI trusted publishing on tag push
- Issue templates (bug report, new dialect request) and PR template
- Three example skills: `humanizer`, `security-auditor`, `docker-deploy`

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
