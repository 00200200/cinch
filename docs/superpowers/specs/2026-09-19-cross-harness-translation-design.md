# Cross-harness translation

Status: approved design
Date: 2026-09-19

## Problem

Cinch advertises "universal agents for every harness — init once, deploy anywhere."
It does not do that. Three defects, all verified by running the tool:

1. **It only ever copies within a single harness.** `resolve_plan()` uses one
   `HarnessSpec` for both "where to read" and "where to write", so the source and
   target harness are always the same. Wiring a Claude skill into Cursor is
   impossible.

2. **It offers another vendor's private files.** `~/.cursor/skills-cursor` is in
   `cursor.skill_sources`. That directory holds Cursor's 28 shipped built-ins, and
   Cursor's own `create-skill` skill states it is reserved. Observed:
   `cinch inventory --harness cursor` lists all 28; `cinch init --harness cursor
   --skills review --yes` writes a copy of Cursor's built-in into the user's repo.

3. **Nine destination paths do not exist in any product.** `.windsurf/skills`,
   `.windsurf/agents`, `.cline/skills`, `.cline/agents`, `.github/skills`,
   `.github/agents`, `.gemini/skills`, `.gemini/agents`, `.aider/skills`. Two more
   use the wrong extension: Cursor reads only `.mdc` under `rules/`, Gemini reads
   only `.toml` under `commands/`. In every case the copy succeeds, `.cinch.json`
   reports `copied`, and the harness never loads the file.

Defect 3 is the worst failure mode for this product: it is indistinguishable from
success. `apply_plan()` builds its `copied` list from intent, not from effect.

## Goals

- A skill authored once can be wired into any supported harness in its native format.
- Every supported harness mapping is backed by vendor documentation and a test.
- The manifest reports what was actually written, not what was attempted.
- The README demonstrates the above and every claim on it survives checking.

## Non-goals

- Translating hooks. A hook is an executable plus a harness-specific JSON schema;
  there is no shared abstraction. Hooks copy verbatim only when source == target,
  otherwise they are skipped with a stated reason.
- Translating MCP server definitions. Same reasoning.
- `cinch sync` / `cinch status` / drift detection. Separate concern, later cycle.
- Grok CLI and Continue support. Their formats could not be verified against vendor
  documentation; they move to a "planned" list rather than shipping as guesses.

## Architecture

A three-stage pipeline replaces direct source-to-destination copying:

    Item (on disk)  ->  Doc (canonical)  ->  Adapter[target]  ->  RenderedFile

### `cinch/doc.py`

Parses a source item into a canonical `Doc`:

    @dataclass(frozen=True)
    class Doc:
        kind: str                 # skill | agent | command
        name: str
        description: str
        body: str                 # markdown, frontmatter stripped
        paths: tuple[str, ...]    # globs the item declares, may be empty
        support: Path | None      # source dir, when it holds more than SKILL.md

Pure except for reading the source file. Knows three input shapes: a skill
directory containing `SKILL.md`, a single-file agent, a single-file command.
Unknown frontmatter keys are preserved on the `Doc` but only emitted by adapters
that accept them.

### `cinch/adapters.py`

One adapter per target dialect. Contract:

    class Adapter(Protocol):
        target: str
        def render(self, doc: Doc) -> tuple[RenderedFile, ...]: ...

    @dataclass(frozen=True)
    class RenderedFile:
        relpath: str              # relative to project root
        text: str
        mode: str                 # "create" | "merge"

All format knowledge lives here. The `if dest_root.endswith(("hooks.json",))` and
`dest_root in {".", ".clinerules"}` special cases currently in `plan.py` are
deleted; they are the same knowledge in the wrong place.

`mode="merge"` covers the one case that cannot be a plain write: Aider's
`.aider.conf.yml`, where a `read:` entry must be appended to an existing list.

A `create` file is never overwritten. If the destination exists, the outcome is
`exists` and the file is left untouched, matching how `_copy` behaves today. An
overwrite flag is out of scope; a tool that silently rewrites hand-edited rule
files would be worse than one that refuses. A `merge` file is rewritten only when
the entry it needs is absent, and is otherwise `unchanged`.

### The inline/pointer rule

A single rule governs output shape, applied per rendered file:

**Inline by default.** The `Doc` body is written into the target's native file with
translated frontmatter.

**Pointer when the target cannot hold it.** Two triggers:
- the rendered text would exceed a documented per-file limit (Windsurf: 12,000
  characters for a workspace rule)
- `doc.support` is set, i.e. the skill ships scripts or `references/`

In either case the full source directory is copied verbatim to
`.cinch/skills/<name>/`, and the native file carries the description plus a
relative pointer to it. Relative links inside an inlined body are rewritten to
`.cinch/skills/<name>/...` when support files were copied.

Most skills are a single `SKILL.md` under the limit, so the common case is one
clean native file and no `.cinch/` directory.

## Harness matrix

Nine harnesses, each entry traceable to vendor documentation. The doc URL is stored
in the conformance fixture for that harness.

| harness | skill destination | frontmatter emitted |
| --- | --- | --- |
| claude | `.claude/skills/<n>/SKILL.md` | verbatim passthrough |
| cursor | `.agents/skills/<n>/SKILL.md` | verbatim passthrough |
| codex | `.agents/skills/<n>/SKILL.md` | verbatim passthrough |
| copilot | `.github/instructions/<n>.instructions.md` | `applyTo`, `description` |
| gemini | `.gemini/commands/<n>.toml` | `description`, `prompt` (TOML) |
| windsurf | `.devin/rules/<n>.md` | `trigger`, `description`, `globs` |
| cline | `.clinerules/<n>.md` | `paths` (only when declared) |
| opencode | `.opencode/commands/<n>.md` | `description` |
| aider | `.aider/<n>.md` + `.aider.conf.yml` merge | none; `read:` entry added |

Notes carried from format verification:

- `.agents/skills/` is read by both Cursor and Codex, so one write serves two
  targets. This is the emerging cross-vendor location and the product's centre of
  gravity.
- Cursor ignores `.md` under `.cursor/rules/`; only `.mdc` is loaded.
- Gemini parses only `.toml` under `.gemini/commands/`; `prompt` is required.
- Windsurf docs redirect to Devin docs; `.devin/rules/` is preferred with
  `.windsurf/rules/` as fallback. Cinch writes the preferred path.
- Cline evaluates only `paths`. Other keys are inert, so cinch emits none.
- Copilot prompt files use `agent`, not the legacy `mode`.
- Aider auto-loads nothing. A file on disk without a `read:` entry is dead weight,
  so the config merge is mandatory for this target, not optional polish.
- `applyTo` is required by Copilot. When a `Doc` declares no paths, cinch emits
  `applyTo: '**'` and says so in the run output, because that makes the
  instruction always-on and the user should know.

### Agents and commands

The matrix above gives skill destinations. Most targets have no separate concept of
an agent or a command, so all three kinds collapse onto that target's single
instruction surface. Only two targets distinguish them:

| harness | agent destination | command destination |
| --- | --- | --- |
| claude | `.claude/agents/<n>.md` | `.claude/commands/<n>.md` |
| copilot | `.github/prompts/<n>.prompt.md` | `.github/prompts/<n>.prompt.md` |
| cursor, codex | `.agents/skills/<n>/SKILL.md` | same, `disable-model-invocation: true` |
| all others | same path as a skill | same path as a skill |

Cursor documents that user- and workspace-level commands are converted to skills
with `disable-model-invocation: true`, so cinch emits that directly rather than
writing to the undocumented `.cursor/commands/`.

### Source cleanup

- `~/.cursor/skills-cursor` is removed from `cursor.skill_sources`.
- Destination paths listed under Problem item 3 are removed.
- `grok` and `continue` are removed from `HARNESS_ORDER` and moved to a documented
  "planned" list.

## Verification

`wire.py` stops reporting intent. `_copy` and the rendered-file writer both return
an outcome:

    Outcome = Literal["written", "unchanged", "exists", "skipped"]

`apply_plan()` collects outcomes and confirms each destination exists after
writing. `.cinch.json` gains a `results` array of `{kind, name, path, outcome}`
and a `skipped` array of `{kind, name, reason}`. "Attached" in the CLI output is
printed only for `written` and `unchanged`.

## CLI

- `--from-harness <id>` selects the source harness. When omitted, cinch resolves it
  from home markers: exactly one harness present means that one is used; more than
  one present is an error naming the candidates. It never guesses, because guessing
  wrong here silently wires the wrong inventory.
- `--harness` accepts a comma-separated list, so one invocation wires several
  targets. This is the demo.
- `--from` keeps its current meaning (extra inventory root) and gains `--from-dir`
  as a clearer alias. It is deliberately not repurposed: silently flipping the
  meaning of an existing flag would break working invocations.

## Testing

Conformance fixtures, one directory per harness under `tests/conformance/<id>/`:

- `source/` — the input, shared across harnesses
- `expected/` — the exact rendered tree
- `SOURCE.md` — the vendor documentation URL the expected output is derived from

A test renders `source/` for each target and compares the whole tree. The diff on
failure reads as format documentation, and a vendor format change breaks exactly
one fixture.

Additional cases: a skill with support files (pointer path), a skill exceeding the
Windsurf limit (pointer path), a `Doc` with no declared paths (Copilot `applyTo`
fallback), and an existing `.aider.conf.yml` with a populated `read:` list (merge).

`tests/test_cinch.py` is split by module as the suite grows past its current 350
lines.

## README and distribution

- The demo image is a 404 today
  (`raw.githubusercontent.com/asciinema/asciicast-explorer/.../placeholder.gif`).
  It is replaced with an animated SVG terminal cast committed to `assets/`, since
  GitHub does not execute embedded players.
- A "one skill, every harness" section shows the same skill rendered side by side
  for four targets, generated from the conformance fixtures so it cannot drift from
  what the tool emits.
- The supported-harness list matches `HARNESS_ORDER` exactly; planned harnesses are
  listed separately as planned.
- Published to PyPI as `cinch-init`, via GitHub Actions trusted publishing. The name
  `cinch` is taken by an unrelated package ("Cinch continuous integration setup",
  v1.4.0); `cinch-init` is free and already set in `pyproject.toml`. The install
  line becomes `uvx cinch-init`.

## Risks

**Vendor formats drift.** Mitigated by fixtures that name their source document, so
a break points at the page to re-read.

**`.agents/skills/` adoption could stall or fragment.** If it does, cursor and codex
each fall back to their own adapter; nothing else in the design depends on the
shared location.

**Removing harnesses reduces the advertised number from 11 to 9.** Accepted: an
unverifiable entry costs more than it earns on a public repo, because the first
person to test it is the person deciding whether to star it.
