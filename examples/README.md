# Cinch Example Skills

Ready-to-wire skills that show how Cinch translates one Markdown source into each harness dialect.

## Directory Structure

```
examples/skills/
├── humanizer/
│   └── SKILL.md                 # Single-file writing skill
├── security-auditor/
│   └── SKILL.md                 # Security audit skill with multi-language globs
└── docker-deploy/
    ├── SKILL.md                 # Multi-file skill with script references
    └── scripts/
        └── verify.sh            # Bundled script (pointer / support copy)
```

## Try it: Claude Code + Cursor + Codex

From the repo root (needs [uv](https://docs.astral.sh/uv/) or a local `cinch` install):

```bash
# Fresh project directory — clone cinch once, then wire from its examples:
git clone https://github.com/00200200/cinch.git /tmp/cinch
mkdir /tmp/cinch-demo && cd /tmp/cinch-demo

uvx cinch-init \
  --from-dir /tmp/cinch/examples/skills \
  --harness claude,cursor,codex \
  --skills humanizer \
  --yes
```

Or, from inside this repository:

```bash
uv run cinch init --from-dir examples/skills --harness claude,cursor,codex --skills humanizer --yes
```

Expected layout:

```
.claude/skills/humanizer/SKILL.md   # Claude Code
.agents/skills/humanizer/SKILL.md   # Cursor and Codex (shared path)
.cinch.json                         # audit manifest
```

Cursor and Codex both read `.agents/skills/`. Cinch writes that file once and marks the
second target as `shared` in `.cinch.json` — not a conflict, and not a silent skip of a
pre-existing hand-written rule.

Then in your agent:

- Claude Code / Cursor: `/humanizer`
- Codex: `$humanizer`

## Other harnesses

```bash
# Copilot instructions + Gemini command from the same skill
cinch init --from-dir examples/skills --harness copilot,gemini --skills security-auditor --yes

# Multi-file docker-deploy into Copilot
# (body inlined; scripts land under .cinch/skills/docker-deploy/)
cinch init --from-dir examples/skills --harness copilot --skills docker-deploy --yes
```
