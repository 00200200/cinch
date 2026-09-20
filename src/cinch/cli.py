"""Cinch CLI: universal agents and skills for every harness."""

from __future__ import annotations

import argparse
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


if __name__ == "__main__":
    raise SystemExit(main())
