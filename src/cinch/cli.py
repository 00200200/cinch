"""Cinch CLI: universal agents and skills for every harness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cinch.catalog import HARNESS_ORDER, HARNESSES, PURPOSES
from cinch.detect import detect_harnesses
from cinch.plan import CinchError, parse_csv, resolve_plan
from cinch.wire import apply_plan

HOOK = "Universal agents for every harness."
HELP = """\
Universal agents for every harness.

Init once. Translate and wire skills between Claude Code, Cursor, Codex,
GitHub Copilot, Gemini CLI, Windsurf, Cline, OpenCode, and Aider.
"""


def build_parser() -> argparse.ArgumentParser:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--home", type=Path, default=None, help="Home to scan instead of ~")
    parser = argparse.ArgumentParser(prog="cinch", description=HELP)
    commands = parser.add_subparsers(dest="command")

    init = commands.add_parser(
        "init",
        help="Wire skills and agents into target harnesses",
        parents=[shared],
        description=(
            "1. Detect or choose source harness (where your skills live). "
            "2. Select target harness(es) (Claude, Cursor, Copilot, Gemini, Windsurf, …). "
            "3. Cinch translates and attaches them into your repo in native formats."
        ),
    )
    init.add_argument("project", nargs="?", default=".", help="Project directory (default: cwd)")
    init.add_argument(
        "--from-harness",
        choices=HARNESS_ORDER,
        help="Source harness to read inventory from (auto-detected if omitted)",
    )
    init.add_argument(
        "--harness",
        help="Target harness(es) to wire (comma-separated, e.g. cursor,copilot,gemini)",
    )
    init.add_argument("--purpose", choices=PURPOSES, help="Filter inventory by purpose catalog")
    init.add_argument("--skills", help="Comma-separated skill names to wire")
    init.add_argument("--agents", help="Comma-separated agent names to wire")
    init.add_argument("--hooks", help="Comma-separated hook names")
    init.add_argument("--commands", help="Comma-separated command/prompt names")
    init.add_argument(
        "--from",
        "--from-dir",
        dest="extra_roots",
        action="append",
        default=[],
        metavar="DIR",
        help="Extra inventory root (local checkout of skills)",
    )
    init.add_argument("--yes", action="store_true", help="Non-interactive; do not prompt")
    init.add_argument("--dry-run", action="store_true", help="Print the plan without writing")

    inventory = commands.add_parser(
        "inventory",
        help="List skills, agents, hooks, and commands a harness already has",
        parents=[shared],
    )
    inventory.add_argument("--harness", choices=HARNESS_ORDER, required=True)
    inventory.add_argument("--purpose", choices=PURPOSES)
    inventory.add_argument(
        "--from",
        "--from-dir",
        dest="extra_roots",
        action="append",
        default=[],
        metavar="DIR",
    )

    commands.add_parser(
        "harnesses",
        help="List harnesses and which are on this machine",
        parents=[shared],
    )

    status = commands.add_parser(
        "status",
        help="Show wired harnesses and skill sync status in a project",
        parents=[shared],
    )
    status.add_argument("project", nargs="?", default=".", help="Project directory (default: cwd)")

    preview = commands.add_parser(
        "preview",
        help="Preview how a skill renders in a target harness without writing files",
        parents=[shared],
    )
    preview.add_argument("skill", help="Name of the skill, agent, or command to preview")
    preview.add_argument(
        "--target",
        "--harness",
        dest="target",
        choices=HARNESS_ORDER,
        default="cursor",
        help="Target harness dialect to render (default: cursor)",
    )
    preview.add_argument(
        "--from-harness",
        choices=HARNESS_ORDER,
        help="Source harness to look for the skill (auto-detected if omitted)",
    )
    preview.add_argument(
        "--from",
        "--from-dir",
        dest="extra_roots",
        action="append",
        default=[],
        metavar="DIR",
        help="Extra directory to search for skills",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if not args.command:
        parser.print_help()
        return 0
    try:
        if args.command == "harnesses":
            return _list_harnesses(args)
        if args.command == "inventory":
            return _inventory(args)
        if args.command == "status":
            return _status(args)
        if args.command == "preview":
            return _preview(args)
        return _init(args)
    except CinchError as exc:
        print(f"cinch: {exc}", file=sys.stderr)
        return 2


def _home(args: argparse.Namespace) -> Path:
    return Path(args.home).expanduser() if args.home else Path.home()


def _list_harnesses(args: argparse.Namespace) -> int:
    rows = detect_harnesses(home=_home(args))
    print("cinch  " + HOOK)
    print(f"{'id':<12}{'harness':<18}this machine")
    for row in rows:
        mark = "on disk" if row.present else "—"
        print(f"{row.id:<12}{row.title:<18}{mark}")
    return 0


def _inventory(args: argparse.Namespace) -> int:
    from cinch.inventory import collect_inventory

    extra = tuple(Path(root).expanduser().resolve() for root in args.extra_roots)
    items = collect_inventory(
        harness=args.harness,
        home=_home(args),
        project=Path.cwd(),
        purpose=args.purpose,
        extra_roots=extra,
    )
    spec = HARNESSES[args.harness]
    print(f"cinch  {spec.title}")
    if not items:
        print("  (empty inventory)")
        return 0
    print(f"{'kind':<10}name")
    for item in items:
        print(f"{item.kind:<10}{item.name}")
    return 0


def _init(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    home = _home(args)
    extra = tuple(Path(root).expanduser().resolve() for root in args.extra_roots)
    from_harness = args.from_harness
    harness = args.harness

    if harness is None and from_harness is None:
        if args.yes or not sys.stdin.isatty():
            raise CinchError("Pass --harness for non-interactive init")
        harness = _prompt_harness(home=home, project=project)

    skills = parse_csv(args.skills)
    agents = parse_csv(args.agents)
    hooks = parse_csv(args.hooks)
    commands = parse_csv(args.commands)

    if not args.yes and sys.stdin.isatty() and skills is None and agents is None and hooks is None:
        source_for_prompt = from_harness or harness or "claude"
        skills, agents, hooks, commands = _prompt_inventory(
            harness=source_for_prompt,
            home=home,
            project=project,
            purpose=args.purpose,
            extra_roots=extra,
        )

    plan = resolve_plan(
        harness=harness,
        from_harness=from_harness,
        project=project,
        home=home,
        purpose=args.purpose,
        skills=skills,
        agents=agents,
        hooks=hooks,
        commands=commands,
        extra_roots=extra,
        dry_run=args.dry_run,
    )
    result = apply_plan(plan)
    print(_render_init(result))
    return 0


def _render_init(result: dict) -> str:
    lines = ["cinch  " + HOOK]

    targets = result.get("targets", [result.get("harness")])
    if len(targets) == 1:
        lines.append(f"  harness   {result['title']} ({result['harness']})")
    else:
        lines.append(f"  targets   {result['title']}")
        if result.get("source_harness"):
            lines.append(f"  source    {result['source_harness']}")

    if result["copied"]:
        lines.append("  attached  " + ", ".join(result["copied"]))
    else:
        lines.append("  attached  (none)")

    lines.append(f"  project   {result['project']}")

    if result.get("skipped"):
        for skip_msg in result["skipped"]:
            lines.append(f"  skipped   {skip_msg}")

    if result["dry_run"]:
        lines.append("  dry-run   no files written")

    return "\n".join(lines)


def _prompt_harness(*, home: Path, project: Path) -> str:
    import questionary

    rows = detect_harnesses(home=home, project=project)
    choices = []
    for row in rows:
        mark = "on disk" if row.present else "layout known"
        choices.append(questionary.Choice(f"{row.title} ({row.id}) — {mark}", value=row.id))
    selected = questionary.select("Which harness to target?", choices=choices).ask()
    if not selected:
        raise CinchError("No harness selected")
    return selected


def _prompt_inventory(
    *,
    harness: str,
    home: Path,
    project: Path,
    purpose: str | None,
    extra_roots: tuple[Path, ...],
) -> tuple[
    tuple[str, ...] | None,
    tuple[str, ...] | None,
    tuple[str, ...] | None,
    tuple[str, ...] | None,
]:
    import questionary

    from cinch.inventory import collect_inventory

    items = collect_inventory(
        harness=harness,
        home=home,
        project=project,
        purpose=purpose,
        extra_roots=extra_roots,
    )
    if not items:
        print(f"No {HARNESSES[harness].title} skills/agents/hooks found on disk.", file=sys.stderr)
        return None, None, None, None

    def pick(kind: str) -> tuple[str, ...] | None:
        options = [item.name for item in items if item.kind == kind]
        if not options:
            return None
        selected = questionary.checkbox(
            f"{HARNESSES[harness].title} {kind}s — attach which?",
            choices=options,
        ).ask()
        if selected is None:
            raise CinchError("Cancelled")
        return tuple(selected)

    return pick("skill"), pick("agent"), pick("hook"), pick("command")


def _status(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    manifest_path = project / ".cinch.json"
    if not manifest_path.is_file():
        print(f"cinch: No .cinch.json manifest found in {project}")
        print("Run 'cinch init' to wire skills and agents into this project.")
        return 1
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CinchError(f"Corrupt manifest: {exc}")

    source = manifest.get("source_harness", manifest.get("harness", "unknown"))
    targets = manifest.get("targets", [manifest.get("harness", "unknown")])
    results = manifest.get("results", [])

    print("cinch  " + HOOK)
    print(f"  project   {project}")
    print(f"  source    {source}")
    print(f"  targets   {', '.join(targets)}")
    if not results:
        print("  status    no items recorded in manifest")
        return 0

    print("\nwired files:")
    missing = 0
    for item in results:
        rel = item.get("path", "")
        target = item.get("target", "")
        kind = item.get("kind", "skill")
        name = item.get("name", "")
        file_on_disk = project / rel
        if file_on_disk.exists():
            status_label = "synced"
        else:
            status_label = "missing"
            missing += 1
        print(f"  [{target:<8}] {kind}:{name:<16} {rel:<40} ({status_label})")

    if missing > 0:
        print(f"\nwarning: {missing} wired file(s) missing on disk. Run 'cinch init' to repair.")
    else:
        print("\nall wired files are verified and present on disk.")
    return 0


def _preview(args: argparse.Namespace) -> int:
    from cinch.adapters import get_adapter
    from cinch.doc import parse_doc
    from cinch.inventory import collect_inventory

    home = _home(args)
    extra = tuple(Path(root).expanduser().resolve() for root in args.extra_roots)
    source = args.from_harness or ("claude" if extra else None)

    if source is None:
        detected = detect_harnesses(home=home)
        present = [h.id for h in detected if h.present]
        if len(present) == 1:
            source = present[0]
        elif len(present) == 0:
            source = "claude"
        else:
            source = present[0]

    items = collect_inventory(
        harness=source,
        home=home,
        project=Path.cwd(),
        extra_roots=extra,
    )
    matching = [item for item in items if item.name == args.skill]
    if not matching:
        raise CinchError(f"Skill or item '{args.skill}' not found in {source} inventory.")

    doc = parse_doc(matching[0])
    adapter = get_adapter(args.target)
    rendered = adapter.render(doc)

    print(f"# Cinch Preview: {args.skill} -> target dialect: {args.target}")
    print(f"# Source: {matching[0].source}\n")
    for rf in rendered:
        print(f"--- [file: {rf.relpath}] (mode: {rf.mode}) ---")
        print(rf.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
