"""Cinch CLI: universal agents and skills for every harness."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cinch.inventory import Item

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from cinch.catalog import HARNESS_ORDER, HARNESSES, PURPOSES
from cinch.detect import detect_harnesses
from cinch.inventory import Item
from cinch.plan import CinchError, parse_csv, resolve_plan
from cinch.wire import apply_plan

HOOK = "Universal agents for every harness."
HELP = """\
Universal agents for every harness.

Init once. Translate and wire skills between Claude Code, Cursor, Codex,
GitHub Copilot, Gemini CLI, Windsurf, Cline, OpenCode, and Aider.
"""

console = Console()


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
    init.add_argument(
        "--starter",
        action="store_true",
        help=(
            "Include curated starter skills (humanizer, security-auditor, test-writer, git-commit)"
        ),
    )

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
    inventory.add_argument(
        "--starter",
        action="store_true",
        help="Show bundled starter skills",
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

    diff_cmd = commands.add_parser(
        "diff",
        help="Show drift between wired files on disk and source skills",
        parents=[shared],
    )
    diff_cmd.add_argument(
        "project", nargs="?", default=".", help="Project directory (default: cwd)"
    )
    diff_cmd.add_argument(
        "--from",
        "--from-dir",
        dest="extra_roots",
        action="append",
        default=[],
        metavar="DIR",
        help="Extra directory to search for skills",
    )
    check_cmd = commands.add_parser(
        "check",
        help="Validate and lint SKILL.md files against dialect best practices",
        parents=[shared],
    )
    check_cmd.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to a skill directory, file, or root containing skills (default: .)",
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
        if args.command == "diff":
            return _diff(args)
        if args.command == "check":
            return _check(args)
        return _init(args)
    except CinchError as exc:
        print(f"cinch: {exc}", file=sys.stderr)
        return 2


def _home(args: argparse.Namespace) -> Path:
    return Path(args.home).expanduser() if args.home else Path.home()


def _list_harnesses(args: argparse.Namespace) -> int:
    rows = detect_harnesses(home=_home(args))
    if not console.is_terminal:
        print("cinch  " + HOOK)
        print(f"{'id':<12}{'harness':<18}this machine")
        for row in rows:
            mark = "on disk" if row.present else "—"
            print(f"{row.id:<12}{row.title:<18}{mark}")
        return 0

    table = Table(title=HOOK, title_style="bold", show_edge=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Harness", style="bold")
    table.add_column("This Machine", justify="center")
    for row in rows:
        if row.present:
            mark = Text("✓", style="green")
        else:
            mark = Text("—", style="dim")
        table.add_row(row.id, row.title, mark)
    console.print(table)
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
        include_starter=args.starter,
    )
    spec = HARNESSES[args.harness]

    if not console.is_terminal:
        print(f"cinch  {spec.title}")
        if not items:
            print("  (empty inventory)")
            return 0
        print(f"{'kind':<10}name")
        for item in items:
            print(f"{item.kind:<10}{item.name}")
        return 0

    if not items:
        console.print(Panel(Text("(empty inventory)", style="dim"), title=spec.title))
        return 0

    table = Table(title=spec.title, title_style="bold", show_edge=True)
    table.add_column("Kind", style="dim")
    table.add_column("Name", style="bold")
    for item in items:
        table.add_row(item.kind, item.name)
    console.print(table)
    return 0


def _init(args: argparse.Namespace) -> int:
    from cinch.inventory import STARTER_DIR, collect_inventory

    project = Path(args.project).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    home = _home(args)
    extra = tuple(Path(root).expanduser().resolve() for root in args.extra_roots)
    if getattr(args, "starter", False) and STARTER_DIR not in extra:
        extra = extra + (STARTER_DIR,)
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
        source_for_prompt = from_harness or (harness.split(",")[0] if harness else None) or "claude"
        if source_for_prompt not in HARNESSES:
            source_for_prompt = "claude"
        initial_items = collect_inventory(
            harness=source_for_prompt,
            home=home,
            project=project,
            purpose=args.purpose,
            extra_roots=extra,
        )
        if not initial_items:
            import questionary

            starter_choices = [
                "humanizer",
                "security-auditor",
                "test-writer",
                "git-commit",
            ]
            selected_starter = questionary.checkbox(
                "No local skills found. Wire curated starter skills?",
                choices=starter_choices,
            ).ask()
            if selected_starter is None:
                raise CinchError("Cancelled")
            if selected_starter:
                if STARTER_DIR not in extra:
                    extra = extra + (STARTER_DIR,)
                skills = tuple(selected_starter)
        else:
            skills, agents, hooks, commands = _prompt_inventory(
                harness=source_for_prompt,
                home=home,
                project=project,
                purpose=args.purpose,
                extra_roots=extra,
                items=initial_items,
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
    if not console.is_terminal:
        print(_render_init(result))
    else:
        _render_init_rich(result)
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


def _render_init_rich(result: dict) -> None:
    """Render init result as a Rich Panel (only called when console is a TTY)."""
    body = Text()

    targets = result.get("targets", [result.get("harness")])
    if len(targets) == 1:
        body.append("harness   ", style="dim")
        body.append(f"{result['title']} ({result['harness']})\n", style="bold")
    else:
        body.append("targets   ", style="dim")
        body.append(f"{result['title']}\n", style="bold")
        if result.get("source_harness"):
            body.append("source    ", style="dim")
            body.append(f"{result['source_harness']}\n")

    if result["copied"]:
        body.append("attached  ", style="dim")
        body.append(", ".join(result["copied"]) + "\n", style="green")
    else:
        body.append("attached  ", style="dim")
        body.append("(none)\n", style="dim italic")

    body.append("project   ", style="dim")
    body.append(f"{result['project']}\n")

    if result.get("skipped"):
        for skip_msg in result["skipped"]:
            body.append("skipped   ", style="dim")
            body.append(f"{skip_msg}\n", style="yellow")

    if result["dry_run"]:
        body.append("dry-run   ", style="dim")
        body.append("no files written\n", style="bold yellow")

    panel = Panel(
        body,
        title="[bold]cinch[/bold]",
        subtitle=HOOK,
        border_style="blue",
    )
    console.print(panel)


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
    items: list[Item] | None = None,
) -> tuple[
    tuple[str, ...] | None,
    tuple[str, ...] | None,
    tuple[str, ...] | None,
    tuple[str, ...] | None,
]:
    import questionary

    from cinch.inventory import collect_inventory

    if items is None:
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

    if not console.is_terminal:
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
            print(
                f"\nwarning: {missing} wired file(s) missing on disk. Run 'cinch init' to repair."
            )
        else:
            print("\nall wired files are verified and present on disk.")
        return 0

    # Rich TTY output
    console.print(
        Panel(
            f"[dim]project[/dim]   {project}\n"
            f"[dim]source[/dim]    {source}\n"
            f"[dim]targets[/dim]   {', '.join(targets)}",
            title="[bold]cinch[/bold]",
            subtitle=HOOK,
            border_style="blue",
        )
    )

    if not results:
        console.print("  [dim]no items recorded in manifest[/dim]")
        return 0

    table = Table(
        title=f"Wired Files — {project}",
        title_style="bold",
        show_edge=True,
    )
    table.add_column("Target", style="cyan", no_wrap=True)
    table.add_column("Item", style="bold")
    table.add_column("Path")
    table.add_column("Status", justify="center")

    missing = 0
    for item in results:
        rel = item.get("path", "")
        target = item.get("target", "")
        kind = item.get("kind", "skill")
        name = item.get("name", "")
        file_on_disk = project / rel
        if file_on_disk.exists():
            status_text = Text("✓ synced", style="green")
        else:
            status_text = Text("✗ missing", style="red")
            missing += 1
        table.add_row(target, f"{kind}:{name}", rel, status_text)

    console.print(table)

    if missing > 0:
        console.print(
            Panel(
                f"[bold red]{missing}[/bold red] wired file(s) missing on disk."
                " Run [bold]cinch init[/bold] to repair.",
                style="yellow",
            )
        )
    else:
        console.print(
            Panel(
                "[green]All wired files are verified and present on disk.[/green]",
                style="green",
            )
        )
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

    if not console.is_terminal:
        print(f"# Cinch Preview: {args.skill} -> target dialect: {args.target}")
        print(f"# Source: {matching[0].source}\n")
        for rf in rendered:
            print(f"--- [file: {rf.relpath}] (mode: {rf.mode}) ---")
            print(rf.text)
        return 0

    # Rich TTY output
    console.print(
        Panel(
            f"[bold]{args.skill}[/bold] → target dialect: [cyan]{args.target}[/cyan]\n"
            f"[dim]Source: {matching[0].source}[/dim]",
            title="[bold]Cinch Preview[/bold]",
            border_style="blue",
        )
    )
    for rf in rendered:
        console.print(f"\n[dim]── file: [bold]{rf.relpath}[/bold] (mode: {rf.mode}) ──[/dim]")
        # Guess lexer from file extension
        ext = Path(rf.relpath).suffix.lstrip(".")
        lexer = {"md": "markdown", "toml": "toml", "json": "json", "yaml": "yaml"}.get(ext, "text")
        syntax = Syntax(rf.text, lexer, theme="monokai", padding=1)
        console.print(syntax)
    return 0


def _diff(args: argparse.Namespace) -> int:
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
    targets = tuple(manifest.get("targets", [manifest.get("harness", "unknown")]))
    results = manifest.get("results", [])

    skills = (
        tuple(dict.fromkeys(item["name"] for item in results if item.get("kind") == "skill"))
        or None
    )
    agents = (
        tuple(dict.fromkeys(item["name"] for item in results if item.get("kind") == "agent"))
        or None
    )
    hooks = (
        tuple(dict.fromkeys(item["name"] for item in results if item.get("kind") == "hook")) or None
    )
    commands = (
        tuple(dict.fromkeys(item["name"] for item in results if item.get("kind") == "command"))
        or None
    )

    if not (skills or agents or hooks or commands) and "copied" in manifest:
        copied_skills = []
        copied_agents = []
        copied_hooks = []
        copied_commands = []
        for entry in manifest.get("copied", []):
            if ":" in entry:
                k, n = entry.split(":", 1)
                if k == "skill":
                    copied_skills.append(n)
                elif k == "agent":
                    copied_agents.append(n)
                elif k == "hook":
                    copied_hooks.append(n)
                elif k == "command":
                    copied_commands.append(n)
        skills = tuple(dict.fromkeys(copied_skills)) or None
        agents = tuple(dict.fromkeys(copied_agents)) or None
        hooks = tuple(dict.fromkeys(copied_hooks)) or None
        commands = tuple(dict.fromkeys(copied_commands)) or None

    extra = tuple(Path(root).expanduser().resolve() for root in getattr(args, "extra_roots", []))

    plan = resolve_plan(
        harness=targets,
        from_harness=source,
        project=project,
        home=_home(args),
        skills=skills,
        agents=agents,
        hooks=hooks,
        commands=commands,
        extra_roots=extra,
    )

    has_drift = False
    seen_missing: set[str] = set()
    seen_diffs: set[str] = set()

    for file in plan.files:
        disk_path = project / file.relpath
        if not disk_path.exists():
            has_drift = True
            if file.relpath not in seen_missing:
                seen_missing.add(file.relpath)
                if not console.is_terminal:
                    print(f"{file.relpath}: [missing on disk]")
                else:
                    console.print(
                        Panel(
                            f"[bold red]{file.relpath}[/bold red]: [missing on disk]",
                            title=f"[bold]{file.relpath}[/bold]",
                            border_style="red",
                        )
                    )
            continue

        expected = file.content
        if not expected and file.source and file.source.is_file():
            try:
                expected = file.source.read_text(encoding="utf-8")
            except Exception:
                expected = file.content

        try:
            disk_content = disk_path.read_text(encoding="utf-8")
        except Exception:
            disk_content = ""

        if file.mode == "merge":
            addition_lines = [line.strip() for line in expected.splitlines() if line.strip()]
            if all(line == "read:" or line in disk_content for line in addition_lines):
                continue

        if disk_content != expected:
            diff_key = f"{file.relpath}:{expected}:{disk_content}"
            if diff_key in seen_diffs:
                continue
            seen_diffs.add(diff_key)
            has_drift = True
            diff_lines = list(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    disk_content.splitlines(keepends=True),
                    fromfile=f"a/{file.relpath}",
                    tofile=f"b/{file.relpath}",
                )
            )
            diff_text = "".join(diff_lines)
            if not diff_text.endswith("\n"):
                diff_text += "\n"

            if not console.is_terminal:
                print(diff_text, end="")
            else:
                syntax = Syntax(diff_text, "diff", theme="monokai", padding=1)
                console.print(Panel(syntax, title=file.relpath, border_style="yellow"))

    manifest_paths = {item.get("path") for item in results if item.get("path")}
    planned_paths = {file.relpath for file in plan.files}
    for relpath in manifest_paths - planned_paths:
        disk_path = project / relpath
        if not disk_path.exists():
            has_drift = True
            if relpath not in seen_missing:
                seen_missing.add(relpath)
                if not console.is_terminal:
                    print(f"{relpath}: [missing on disk]")
                else:
                    console.print(
                        Panel(
                            f"[bold red]{relpath}[/bold red]: [missing on disk]",
                            title=f"[bold]{relpath}[/bold]",
                            border_style="red",
                        )
                    )

    if has_drift:
        return 1

    if not console.is_terminal:
        print("No drift detected. Project is up to date.")
    else:
        console.print("[green]No drift detected. Project is up to date.[/green]")
    return 0


def _check(args: argparse.Namespace) -> int:
    from cinch.check import lint_directory, lint_skill

    target = Path(args.path).expanduser()
    if target.is_file() or target.suffix == ".md":
        diagnostics = lint_skill(target)
    else:
        diagnostics = lint_directory(target)

    if console.is_terminal:
        if diagnostics:
            table = Table(show_header=True, header_style="bold", show_edge=True)
            table.add_column("Severity")
            table.add_column("Rule")
            table.add_column("Path")
            table.add_column("Message")

            for diag in diagnostics:
                if diag.severity == "error":
                    sev_style = "bold red"
                elif diag.severity == "warning":
                    sev_style = "yellow"
                else:
                    sev_style = "cyan"

                path_str = f"{diag.path}:{diag.line}" if diag.line is not None else str(diag.path)
                table.add_row(
                    Text(diag.severity, style=sev_style),
                    Text(diag.rule, style=sev_style),
                    Text(path_str),
                    Text(diag.message),
                )
            console.print(table)

            error_count = sum(1 for d in diagnostics if d.severity == "error")
            warning_count = sum(1 for d in diagnostics if d.severity == "warning")
            if error_count > 0:
                summary_msg = (
                    f"✗ Found {len(diagnostics)} diagnostics "
                    f"({error_count} error{'s' if error_count != 1 else ''}, "
                    f"{warning_count} warning{'s' if warning_count != 1 else ''})"
                )
                panel_style = "bold red"
                border_style = "red"
            elif warning_count > 0:
                summary_msg = (
                    f"⚠ Found {len(diagnostics)} diagnostics "
                    f"({warning_count} warning{'s' if warning_count != 1 else ''})"
                )
                panel_style = "bold yellow"
                border_style = "yellow"
            else:
                info_count = len(diagnostics)
                summary_msg = (
                    f"✓ All checks passed "
                    f"({info_count} informational note{'s' if info_count != 1 else ''})"
                )
                panel_style = "bold green"
                border_style = "green"
            console.print(Panel(Text(summary_msg, style=panel_style), border_style=border_style))
        else:
            console.print(
                Panel(Text("✓ All checks passed", style="bold green"), border_style="green")
            )
    else:
        for diag in diagnostics:
            loc = f"{diag.path}:{diag.line}:" if diag.line is not None else f"{diag.path}:"
            print(f"{loc} [{diag.severity.upper()}] {diag.rule}: {diag.message}")

    has_errors = any(d.severity == "error" for d in diagnostics)
    return 1 if has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
