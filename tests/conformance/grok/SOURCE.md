# Grok Conformance Source

- Vendor: xAI
- Product: Grok Build / Grok CLI
- Documentation: https://docs.x.ai/build/features/skills-plugins-marketplaces
- Project Skill Destination: `.grok/skills/<name>/SKILL.md`
- Global Skills Root: `~/.grok/skills/<name>/SKILL.md`
- Schema: YAML frontmatter with `name`, `description`, optional `when-to-use`,
  `paths`, `allowed-tools`, `argument-hint`, `user-invocable`,
  `disable-model-invocation`. Extra keys are ignored by Grok; Cinch strips
  unsupported source frontmatter on emit.
- Notes: Skills are folders (not flat `.md` files). User-invocable skills appear
  as slash commands. Agents and commands compile onto the same skill layout.
