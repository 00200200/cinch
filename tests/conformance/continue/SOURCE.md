# Continue.dev Conformance Source

- Vendor: Continue Dev, Inc.
- Product: Continue
- Documentation: https://docs.continue.dev/customize/deep-dives/prompts
- Prompt Destination: `.continue/prompts/<name>.prompt`
- Optional Config Merge: `.continue/config.json` → `customCommands` (only when the file already exists)
- Schema: YAML frontmatter with `name`, `description`, and `invokable: true`. Body may include Handlebars context variables such as `{{{ input }}}` and `{{{ current_file }}}`.
- Notes: Prompt files become slash commands in Chat / Plan / Agent. Cinch maps Cinch `paths` to an HTML comment and upgrades bare `{{ var }}` tokens to `{{{ var }}}` without rewriting existing triple-brace expressions.
