"""Cinch CLI: universal agents and skills for every harness."""

from __future__ import annotations

import argparse
import difflib
import json
import os
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
from cinch.params import parse_param_flags
from cinch.plan import CinchError, parse_csv, resolve_plan
from cinch.wire import apply_plan

HOOK = "Universal agents for every harness."
HELP = """\
Universal agents for every harness.

Init once. Translate and wire skills between Claude Code, Cursor, Codex,
GitHub Copilot, Gemini CLI, Windsurf, Cline, OpenCode, and Aider.
"""


def _force_terminal() -> bool | None:
    """Choose Rich vs plain output with correct FORCE_COLOR / NO_COLOR semantics.

    Rich treats any non-empty FORCE_COLOR (including ``0``) as a terminal. Per
    https://force-color.org/, ``0`` / ``false`` disable color, and NO_COLOR
    always wins. Return None so Rich can auto-detect when neither is set.
    """
    if os.environ.get("NO_COLOR", "") != "":
        return False
    force = os.environ.get("FORCE_COLOR")
    if force is None:
        return None
    return force.strip().lower() not in ("", "0", "false", "no", "off")


console = Console(force_terminal=_force_terminal())


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
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override a skill parameter (repeatable); wins over CINCH_PARAM_* env vars",
    )
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
    preview.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override a skill parameter (repeatable); wins over CINCH_PARAM_* env vars",
    )
    preview.add_argument(
        "--yes",
        action="store_true",
        help="Non-interactive; error if required parameters are unset",
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
    diff_cmd.add_argument(
        "--stat",
        action="store_true",
        help="Show token deltas and line statistics across files",
    )
    diff_cmd.add_argument(
        "--git-ref",
        metavar="REF",
        default=None,
        help="Compare current files against a git ref (e.g. HEAD~1, main)",
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
    check_cmd.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Enforce SkillManifestSchema: required name/description, known keys only, "
            "valid path globs (errors exit non-zero; misspelled keys get hints)"
        ),
    )
    check_cmd.add_argument(
        "--audit-secrets",
        action="store_true",
        help=(
            "Also scan skills for leaked API keys, tokens, high-entropy secrets, "
            "and hardcoded user paths (stdlib detector; exits 1 on findings)"
        ),
    )
    check_cmd.add_argument(
        "--policy",
        metavar="PATH",
        default=None,
        help="Path to .cinchpolicy.yml corporate compliance rules file",
    )

    from cinch.importer import IMPORT_DIALECTS

    import_cmd = commands.add_parser(
        "import",
        help="Decompile legacy .cursorrules / Claude skills / Copilot / Cline into Cinch format",
        parents=[shared],
        description=(
            "Reverse-sync legacy harness rules into canonical Cinch skill markdown "
            "under --out (default: .cinch/imported). Auto-detects dialect from path "
            "markers; pass --from-harness when detection is ambiguous."
        ),
    )
    import_cmd.add_argument(
        "path",
        help=(
            "Legacy file or directory "
            "(.cursorrules, SKILL.md, .github/instructions, .clinerules, …)"
        ),
    )
    import_cmd.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory for imported skills (default: .cinch/imported)",
    )
    import_cmd.add_argument(
        "--from-harness",
        "--from",
        dest="from_harness",
        choices=IMPORT_DIALECTS,
        help="Source dialect when auto-detect is ambiguous or the path has no markers",
    )
    import_cmd.add_argument(
        "--yes",
        action="store_true",
        help="Overwrite existing imported skills without prompting",
    )
    import_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview imported skills without writing files",
    )

    from cinch.watch import DEFAULT_DEBOUNCE_MS

    watch_cmd = commands.add_parser(
        "watch",
        help="Watch skill markdown and re-wire target harnesses on change",
        parents=[shared],
        description=(
            "Poll source skill directories for create/modify/delete, debounce, "
            "then re-run the wire/compile path for --harness target(s). "
            "Uses stdlib mtime polling (no watchfiles/watchdog)."
        ),
    )
    watch_cmd.add_argument(
        "project", nargs="?", default=".", help="Project directory (default: cwd)"
    )
    watch_cmd.add_argument(
        "--from-harness",
        choices=HARNESS_ORDER,
        help="Source harness to read inventory from (auto-detected if omitted)",
    )
    watch_cmd.add_argument(
        "--harness",
        help="Target harness(es) to wire (comma-separated, e.g. cursor,copilot)",
    )
    watch_cmd.add_argument("--purpose", choices=PURPOSES, help="Filter inventory by purpose")
    watch_cmd.add_argument("--skills", help="Comma-separated skill names to wire")
    watch_cmd.add_argument("--agents", help="Comma-separated agent names to wire")
    watch_cmd.add_argument("--hooks", help="Comma-separated hook names")
    watch_cmd.add_argument("--commands", help="Comma-separated command/prompt names")
    watch_cmd.add_argument(
        "--from",
        "--from-dir",
        dest="extra_roots",
        action="append",
        default=[],
        metavar="DIR",
        help="Skill root to watch and read (repeatable; same as init --from-dir)",
    )
    watch_cmd.add_argument(
        "--debounce",
        type=int,
        default=DEFAULT_DEBOUNCE_MS,
        metavar="MS",
        help=f"Quiet period before rebuild (default: {DEFAULT_DEBOUNCE_MS})",
    )
    watch_cmd.add_argument(
        "--once",
        action="store_true",
        help="Scan and rebuild once, then exit (for scripts and tests)",
    )
    watch_cmd.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override a skill parameter (repeatable); wins over CINCH_PARAM_* env vars",
    )

    mcp_cmd = commands.add_parser(
        "mcp-server",
        help="Run lightweight FastMCP prompt server over STDIO",
        parents=[shared],
    )
    mcp_cmd.add_argument(
        "--root",
        dest="project_root",
        default=".",
        metavar="DIR",
        help="Project directory containing skills (default: .)",
    )
    mcp_cmd.add_argument(
        "--from",
        "--from-dir",
        dest="extra_roots",
        action="append",
        default=[],
        metavar="DIR",
        help="Extra skill directory to expose as MCP prompts",
    )
    mcp_cmd.add_argument(
        "--no-starter",
        action="store_true",
        help="Do not include bundled starter skills",
    )

    export_cmd = commands.add_parser(
        "export",
        help="Export skill catalog as standalone documentation artifact",
        parents=[shared],
    )
    export_cmd.add_argument(
        "project",
        nargs="?",
        default=".",
        help="Project directory (default: cwd)",
    )
    export_cmd.add_argument(
        "--format",
        choices=["html"],
        default="html",
        help="Export format (default: html)",
    )
    export_cmd.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output HTML file path (default: stdout)",
    )
    export_cmd.add_argument(
        "--title",
        default=None,
        help="Catalog page title",
    )
    export_cmd.add_argument(
        "--no-starter",
        action="store_true",
        help="Exclude bundled starter skills",
    )

    eval_cmd = commands.add_parser(
        "eval",
        help="Run automated skill assertion & prompt regression tests",
        parents=[shared],
    )
    eval_cmd.add_argument(
        "skill",
        nargs="?",
        default=None,
        help="Specific skill name to evaluate (default: all discovered evals)",
    )
    eval_cmd.add_argument(
        "--eval-dir",
        default="evals",
        help="Directory containing eval test specs (default: evals)",
    )
    eval_cmd.add_argument(
        "--output-junit",
        default=None,
        help="Path to write JUnit XML test report",
    )
    eval_cmd.add_argument(
        "--project",
        default=".",
        help="Project directory (default: cwd)",
    )

    install_cmd = commands.add_parser(
        "install",
        help="Install remote skill package from Git repository",
        parents=[shared],
    )
    install_cmd.add_argument(
        "package",
        help="Git repo URL or shorthand (e.g. gh:owner/repo@v1.0)",
    )
    install_cmd.add_argument(
        "--project",
        default=".",
        help="Project directory (default: cwd)",
    )
    install_cmd.add_argument(
        "--skill",
        default=None,
        help="Specific skill name to install if repo contains multiple",
    )
    install_cmd.add_argument(
        "--force",
        action="store_true",
        help="Force reinstallation if skill already exists",
    )

    update_cmd = commands.add_parser(
        "update",
        help="Update installed remote skill packages",
        parents=[shared],
    )
    update_cmd.add_argument(
        "package",
        nargs="?",
        default=None,
        help="Specific package name to update (default: all)",
    )
    update_cmd.add_argument(
        "--project",
        default=".",
        help="Project directory (default: cwd)",
    )

    uninstall_cmd = commands.add_parser(
        "uninstall",
        help="Uninstall a vendored skill package",
        parents=[shared],
    )
    uninstall_cmd.add_argument(
        "package",
        help="Name of skill package to uninstall",
    )
    uninstall_cmd.add_argument(
        "--project",
        default=".",
        help="Project directory (default: cwd)",
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
        if args.command == "import":
            return _import(args)
        if args.command == "watch":
            return _watch(args)
        if args.command == "mcp-server":
            return _mcp_server(args)
        if args.command == "export":
            return _export(args)
        if args.command == "eval":
            return _eval(args)
        if args.command == "install":
            return _install(args)
        if args.command == "update":
            return _update(args)
        if args.command == "uninstall":
            return _uninstall(args)
        return _init(args)
    except CinchError as exc:
        print(f"cinch: {exc}", file=sys.stderr)
        return 2


def _install(args: argparse.Namespace) -> int:
    from cinch.package import install_package

    results = install_package(
        args.package,
        project=Path(args.project).resolve(),
        skill_name=args.skill,
        force=args.force,
    )
    for res in results:
        ref_str = f" @ {res.ref}" if res.ref else ""
        print(f"Installed {res.name} from {res.source}{ref_str} -> {res.vendor_path}")
        print(f"  commit:   {res.commit[:8]}")
        print(f"  checksum: {res.checksum}")
    return 0


def _update(args: argparse.Namespace) -> int:
    from cinch.package import update_package

    results = update_package(
        args.package,
        project=Path(args.project).resolve(),
    )
    for res in results:
        print(f"Updated {res.name} -> {res.commit[:8]} ({res.checksum})")
    return 0


def _uninstall(args: argparse.Namespace) -> int:
    from cinch.package import uninstall_package

    uninstall_package(
        args.package,
        project=Path(args.project).resolve(),
    )
    print(f"Uninstalled package '{args.package}'")
    return 0


def _export(args: argparse.Namespace) -> int:
    from cinch.html import export_html_catalog

    project = Path(args.project).resolve()
    title = args.title or f"{project.name} Skills Catalog"
    output = args.output

    html_content = export_html_catalog(
        project_root=project,
        output_path=output,
        include_starter=not args.no_starter,
        title=title,
    )

    if not output:
        sys.stdout.write(html_content)
    else:
        print(f"Exported HTML catalog to {output}")
    return 0


def _eval(args: argparse.Namespace) -> int:
    from cinch.eval import generate_junit_xml, print_eval_summary, run_evals

    project = Path(args.project).resolve()
    eval_dir = (project / args.eval_dir).resolve()
    suite = run_evals(project, eval_dir, skill_name=args.skill)

    if suite.total == 0:
        console.print(f"[yellow]No eval specs found in {eval_dir}[/yellow]")
        return 1 if args.skill else 0

    if args.output_junit:
        junit_path = Path(args.output_junit)
        junit_path.parent.mkdir(parents=True, exist_ok=True)
        junit_xml = generate_junit_xml(suite)
        junit_path.write_text(junit_xml, encoding="utf-8")

    print_eval_summary(suite, console=console)
    return 1 if suite.failed > 0 else 0


def _mcp_server(args: argparse.Namespace) -> int:
    from cinch.mcp import McpPromptServer

    server = McpPromptServer(
        project_root=Path(args.project_root),
        extra_roots=tuple(Path(p) for p in args.extra_roots),
        include_starter=not args.no_starter,
    )
    return server.run_stdio()


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
        param_overrides=parse_param_flags(getattr(args, "param", None)),
        interactive_params=not args.yes and sys.stdin.isatty(),
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
    from cinch.params import apply_parameters_to_doc

    doc = apply_parameters_to_doc(
        doc,
        cli_overrides=parse_param_flags(getattr(args, "param", None)),
        interactive=not getattr(args, "yes", False) and sys.stdin.isatty(),
    )
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

    total_added_tokens = 0
    total_removed_tokens = 0
    stat_records = []

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

        # Handle git-ref comparison if requested
        git_ref = getattr(args, "git_ref", None)
        if git_ref:
            try:
                import subprocess

                ref_cmd = ["git", "show", f"{git_ref}:{file.relpath}"]
                res = subprocess.run(ref_cmd, cwd=project, capture_output=True, text=True)
                if res.returncode == 0:
                    expected = res.stdout
            except Exception:
                pass

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

            # Compute approximate token counts (whitespace split * 1.3)
            exp_tokens = len(expected.split())
            disk_tokens = len(disk_content.split())
            delta_tokens = disk_tokens - exp_tokens
            stat_records.append((file.relpath, delta_tokens))
            if delta_tokens > 0:
                total_added_tokens += delta_tokens
            else:
                total_removed_tokens += abs(delta_tokens)

            if not getattr(args, "stat", False):
                if not console.is_terminal:
                    print(diff_text, end="")
                else:
                    token_hint = f" ({'+' if delta_tokens >= 0 else ''}{delta_tokens} tokens)"
                    syntax = Syntax(diff_text, "diff", theme="monokai", padding=1)
                    console.print(
                        Panel(syntax, title=f"{file.relpath}{token_hint}", border_style="yellow")
                    )

    if getattr(args, "stat", False) and stat_records:
        if not console.is_terminal:
            print("Token & file statistics:")
            for path, delta in stat_records:
                sign = "+" if delta >= 0 else ""
                print(f"  {path:40} {sign}{delta} tokens")
            print(f"Total token delta: +{total_added_tokens} / -{total_removed_tokens}")
        else:
            table = Table(title="Token & File Statistics", border_style="cyan")
            table.add_column("File", style="bold")
            table.add_column("Token Delta", justify="right")
            for path, delta in stat_records:
                color = "green" if delta <= 0 else "yellow"
                sign = "+" if delta >= 0 else ""
                table.add_row(path, f"[{color}]{sign}{delta} tokens[/{color}]")
            console.print(table)
            console.print(
                f"[bold]Total token delta:[/bold] [yellow]+{total_added_tokens}[/yellow] / "
                f"[green]-{total_removed_tokens}[/green]"
            )

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

    strict = bool(getattr(args, "strict", False))
    target = Path(args.path).expanduser()
    if target.is_file() or target.suffix == ".md":
        diagnostics = lint_skill(target, strict=strict)
    else:
        diagnostics = lint_directory(target, strict=strict)

    if getattr(args, "audit_secrets", False):
        from cinch.secrets import audit_directory, audit_skill

        if target.is_file() or target.suffix == ".md":
            diagnostics = diagnostics + audit_skill(target)
        else:
            diagnostics = diagnostics + audit_directory(target)

    # Check for corporate policy (.cinchpolicy.yml or --policy)
    from cinch.policy import audit_policy_directory, audit_policy_skill, load_policy

    policy_path = Path(args.policy) if getattr(args, "policy", None) else None
    policy = load_policy(policy_path, start_dir=target if target.is_dir() else target.parent)
    if policy is not None:
        if target.is_file() or target.suffix == ".md":
            diagnostics = diagnostics + audit_policy_skill(target, policy)
        else:
            diagnostics = diagnostics + audit_policy_directory(target, policy)

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


def _watch(args: argparse.Namespace) -> int:
    from cinch.watch import WatchChange, WatchConfig, run_watch

    project = Path(args.project).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    home = _home(args)
    extra = tuple(Path(root).expanduser().resolve() for root in args.extra_roots)
    harness = args.harness
    from_harness = args.from_harness

    if harness is None and from_harness is None and not extra:
        if not sys.stdin.isatty():
            raise CinchError("Pass --harness (or --from-dir) for non-interactive watch")
        harness = _prompt_harness(home=home, project=project)

    if args.debounce < 0:
        raise CinchError("--debounce must be >= 0")

    config = WatchConfig(
        project=project,
        home=home,
        harness=harness,
        from_harness=from_harness,
        extra_roots=extra,
        skills=parse_csv(args.skills),
        agents=parse_csv(args.agents),
        hooks=parse_csv(args.hooks),
        commands=parse_csv(args.commands),
        purpose=args.purpose,
        param_overrides=parse_param_flags(getattr(args, "param", None)),
        debounce_ms=args.debounce,
    )

    def on_start(roots: tuple[Path, ...]) -> None:
        roots_display = ", ".join(str(root) for root in roots)
        targets = harness or from_harness or "auto"
        if not console.is_terminal:
            print(f"cinch watch  watching {roots_display}")
            print(f"  harness   {targets}")
            print(f"  debounce  {args.debounce}ms")
            if args.once:
                print("  mode      once")
            return
        console.print(
            f"[bold]cinch watch[/bold]  watching [cyan]{roots_display}[/cyan] → "
            f"[bold]{targets}[/bold]  ([dim]debounce {args.debounce}ms[/dim])"
        )

    def on_rebuild(changes: list[WatchChange], result: dict, elapsed_ms: float) -> None:
        changed = ", ".join(f"{c.kind}:{Path(c.path).name}" for c in changes) or "startup"
        attached = ", ".join(result.get("copied") or []) or "(none)"
        if not console.is_terminal:
            print(f"  rebuild   {changed}  ({elapsed_ms:.0f}ms)")
            print(f"  attached  {attached}")
            for skip in result.get("skipped") or []:
                print(f"  skipped   {skip}")
            return
        console.print(f"  [green]rebuild[/green]  {changed}  [dim]({elapsed_ms:.0f}ms)[/dim]")
        console.print(f"  [dim]attached[/dim]  {attached}")
        for skip in result.get("skipped") or []:
            console.print(f"  [yellow]skipped[/yellow]  {skip}")

    def on_error(exc: BaseException) -> None:
        if not console.is_terminal:
            print(f"  error     {exc}", file=sys.stderr)
            return
        console.print(f"  [bold red]error[/bold red]  {exc}")

    return run_watch(
        config,
        once=bool(args.once),
        on_start=on_start,
        on_rebuild=on_rebuild,
        on_error=on_error,
    )


def _import(args: argparse.Namespace) -> int:
    from cinch.importer import DEFAULT_OUT, run_import

    path = Path(args.path).expanduser()
    out = Path(args.out).expanduser() if args.out else Path.cwd() / DEFAULT_OUT
    result = run_import(
        path,
        out=out,
        dialect=getattr(args, "from_harness", None),
        dry_run=bool(args.dry_run),
        overwrite=bool(args.yes),
    )

    if not console.is_terminal:
        print("cinch  " + HOOK)
        print(f"  import    {result.dialect}")
        print(f"  out       {result.out}")
        if result.written:
            print("  skills    " + ", ".join(result.written))
        else:
            print("  skills    (none)")
        for skip in result.skipped:
            print(f"  skipped   {skip}")
        if result.dry_run:
            print("  dry-run   no files written")
            for rel, text in result.preview:
                print(f"\n--- [file: {rel}] ---")
                print(text, end="" if text.endswith("\n") else "\n")
        return 0

    body = Text()
    body.append("import    ", style="dim")
    body.append(f"{result.dialect}\n", style="bold")
    body.append("out       ", style="dim")
    body.append(f"{result.out}\n")
    if result.written:
        body.append("skills    ", style="dim")
        body.append(", ".join(result.written) + "\n", style="green")
    else:
        body.append("skills    ", style="dim")
        body.append("(none)\n", style="dim italic")
    for skip in result.skipped:
        body.append("skipped   ", style="dim")
        body.append(f"{skip}\n", style="yellow")
    if result.dry_run:
        body.append("dry-run   ", style="dim")
        body.append("no files written\n", style="bold yellow")

    console.print(
        Panel(body, title="[bold]cinch import[/bold]", subtitle=HOOK, border_style="blue")
    )
    if result.dry_run:
        for rel, text in result.preview:
            console.print(f"\n[dim]── file: [bold]{rel}[/bold] ──[/dim]")
            console.print(Syntax(text, "markdown", theme="monokai", padding=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
