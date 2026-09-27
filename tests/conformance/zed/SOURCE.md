# Zed Conformance Source

- Vendor: Zed Industries
- Product: Zed
- Documentation: https://zed.dev/docs/ai/skills
- Project Skill Destination: `.agents/skills/<name>/SKILL.md`
- Global Skills Root: `~/.agents/skills/<name>/SKILL.md`
- Schema: YAML frontmatter with `name`, `description`, optional `disable-model-invocation`.
- Notes: Slash commands and `@skill` mentions are derived from installed skills. Nested folders are not discovered.
