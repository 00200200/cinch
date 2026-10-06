# Trust-Aware Policy Checks and Provenance Audit

Cinch provides a configurable, provenance-oriented trust policy framework shared between `cinch audit` and remote skill installation (`cinch install`).

> [!IMPORTANT]
> **Provenance Signal, Not a Sandbox**
> Trust policy checks verify repository origin, git ref immutability, license presence, and static filesystem artifacts (scripts, path traversals, symlink escapes) without executing repository code. They serve as provenance verification and review gating signals.
>
> **Trust policy checks do not sandbox installed skills or guarantee that natural-language instructions or underlying tools are safe.** Always perform code review on third-party skills and maintain least-privilege tool execution permissions.

---

## Policy Configuration (`.cinchpolicy.yml`)

You can define corporate or repository compliance policies in `.cinchpolicy.yml` at the root of your project:

```yaml
# Source allow/deny patterns (globs or URL prefixes)
allowed_sources:
  - "https://github.com/my-org/*"
  - "github.com/trusted-partner/*"
denied_sources:
  - "*untrusted-domain*"

# Require immutable references (commit SHA or strict SemVer release tag, not mutable branches)
require_immutable_ref: true

# Require explicit human review flag (--reviewed) when a package includes executable scripts
require_review_for_scripts: true

# Require presence of an open-source license file (LICENSE, COPYING) or frontmatter license
require_license: true

# Enforcement mode: true to reject installation and exit non-zero on violations; false for advisory
enforce: false
```

---

## Static Audit Inspection (`cinch audit`)

The `cinch audit` command inspects local workspaces, skill directories, or remote Git repositories statically without running repository code.

### Inspecting Local Workspace or Skill
```bash
cinch audit ./my-skills
```

Output:
```text
Cinch Trust Audit Report: ALLOWED (advisory)
============================================
Source:        /path/to/my-skills
Requested ref: (none)
Commit:        (none)
License:       MIT
Skills:        2 (data-analyst/SKILL.md, git-commit/SKILL.md)
Scripts:       1 (scripts/prepare.sh)
Escapes:       0 detected
```

### CI-Friendly JSON Output
```bash
cinch audit gh:my-org/skills@v1.0.0 --json
```

```json
{
  "target": "/Users/user/.cache/cinch/remotes/...",
  "source": "https://github.com/my-org/skills.git",
  "ref": "v1.0.0",
  "commit": "a1b2c3d4e5f678901234567890abcdef12345678",
  "status": "allowed",
  "allowed": true,
  "enforce": false,
  "violations": [],
  "warnings": [],
  "license": {
    "present": true,
    "type": "MIT"
  },
  "skills": ["git-commit/SKILL.md"],
  "scripts": [],
  "escapes": [],
  "is_immutable_ref": true,
  "requires_review": false,
  "reviewed": false
}
```

### Strict Enforcement Mode
To fail CI with a non-zero exit code if violations occur:
```bash
cinch audit . --enforce
```

---

## Installation Gating (`cinch install`)

When installing remote skill packages, Cinch automatically evaluates your project's `.cinchpolicy.yml`:

- **Advisory Mode (Default)**: Cinch displays policy warnings if non-compliant elements are discovered (such as unpinned mutable branches or missing licenses), but continues installation.
- **Enforced Mode (`--enforce-policy` or `enforce: true` in policy)**: If any violation is found (e.g., untrusted source, path escape, unreviewed script), Cinch halts immediately and explains the decision. **Zero files are written to disk.**

```bash
# Gated install requiring review for scripts
cinch install gh:org/skills@v1.0.0 --enforce-policy

# Once scripts in the skill have been inspected and approved:
cinch install gh:org/skills@v1.0.0 --enforce-policy --reviewed
```
