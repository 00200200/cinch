# GitHub Copilot Conformance Source

- Vendor: GitHub / Microsoft
- Product: GitHub Copilot
- Instructions Documentation: https://docs.github.com/en/copilot/customizing-copilot/adding-custom-instructions-for-github-copilot
- Prompts Documentation: https://docs.github.com/en/copilot/customizing-copilot/creating-prompt-files-for-copilot-chat
- Skill Destination: `.github/instructions/<name>.instructions.md`
- Agent / Command Destination: `.github/prompts/<name>.prompt.md`
- Schema: YAML frontmatter requiring `applyTo` (defaults to `'**'`) and `description`.
