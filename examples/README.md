# Cinch Example Skills

This directory contains ready-to-use example skills illustrating how Cinch translates authoring formats into native harnesses.

## Directory Structure

```
examples/skills/
├── humanizer/
│   └── SKILL.md                 # Single-file documentation writing skill
├── security-auditor/
│   └── SKILL.md                 # Code security auditor with multi-language glob paths
└── docker-deploy/
    ├── SKILL.md                 # Multi-file skill with script references
    └── scripts/
        └── verify.sh            # Bundled script demonstrating Cinch pointer resolution
```

## Trying It Out

You can point Cinch directly at this directory to attach these skills to any local project:

```bash
# Wire the humanizer skill into Cursor (.agents/skills)
cinch init --from-dir examples/skills --harness cursor --skills humanizer --yes

# Wire the security auditor into Copilot instructions and Gemini commands simultaneously
cinch init --from-dir examples/skills --harness copilot,gemini --skills security-auditor --yes

# Wire the multi-file docker-deploy skill into Copilot
# (Notice how Cinch inlines the instructions and moves scripts into .cinch/skills/docker-deploy/)
cinch init --from-dir examples/skills --harness copilot --skills docker-deploy --yes
```
