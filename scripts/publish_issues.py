#!/usr/bin/env python3
"""Publish curated contribution issues to cinch GitHub repository via `gh issue create`."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def load_issues() -> list[dict]:
    path = Path(__file__).parent / "issues.json"
    if not path.is_file():
        raise FileNotFoundError(f"Missing {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def create_issue(issue: dict, repo: str, total: int = 15, dry_run: bool = False):
    print(f"\n[{issue['id']}/{total}] {issue['title']}")
    print(f"Labels: {', '.join(issue['labels'])}")
    if dry_run:
        print("(DRY RUN - skipping actual creation)")
        return
    cmd = [
        "gh",
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        issue["title"],
        "--body",
        issue["body"],
    ]
    for label in issue["labels"]:
        cmd.extend(["--label", label])
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    print(f"Created: {result.stdout.strip()}")


def main():
    parser = argparse.ArgumentParser(description="Publish cinch issues to GitHub.")
    parser.add_argument("--repo", default="00200200/cinch", help="GitHub repo")
    parser.add_argument("--list", action="store_true", help="List all issues")
    parser.add_argument("--dry-run", action="store_true", help="Dry run")
    parser.add_argument("--issue", type=int, help="Issue ID (1-15)")
    parser.add_argument("--all", action="store_true", help="Create all 15 issues")
    args = parser.parse_args()

    issues = load_issues()

    if args.list:
        for iss in issues:
            print(f"  #{iss['id']:2d}: {iss['title']} [{', '.join(iss['labels'])}]")
        return

    if args.issue:
        matching = [iss for iss in issues if iss["id"] == args.issue]
        if not matching:
            sys.exit(f"Issue #{args.issue} not found.")
        create_issue(matching[0], args.repo, total=len(issues), dry_run=args.dry_run)
        return

    if args.all:
        for iss in issues:
            create_issue(iss, args.repo, total=len(issues), dry_run=args.dry_run)
            time.sleep(1.5)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
