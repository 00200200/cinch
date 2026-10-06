"""Lightweight FastMCP STDIO Prompt Server for Cinch skills.

Exposes discovered skills as Model Context Protocol (MCP) prompts via JSON-RPC 2.0.
Responds to:
  - initialize
  - ping
  - prompts/list
  - prompts/get
with zero heavy dependencies (<20ms startup).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

from cinch.doc import Doc, parse_doc
from cinch.inventory import STARTER_DIR, Item
from cinch.params import apply_parameters_to_doc, parse_param_specs, render_template

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "cinch-mcp-server"
SERVER_VERSION = "0.1.0"


class McpPromptServer:
    """Lightweight stdio MCP server exposing Cinch skills as MCP prompts."""

    def __init__(
        self,
        project_root: Path | str | None = None,
        extra_roots: tuple[Path, ...] = (),
        include_starter: bool = True,
    ) -> None:
        self.project_root = Path(project_root).resolve() if project_root else Path.cwd()
        self.extra_roots = tuple(Path(r).resolve() for r in extra_roots)
        self.include_starter = include_starter
        self._skills: dict[str, Doc] = {}
        self.reload()

    def reload(self) -> None:
        """Scan directories and load all skills into memory."""
        self._skills.clear()
        roots_to_scan: list[Path] = []

        # Common skill locations within project
        for rel in (
            ".skills",
            "skills",
            ".claude/skills",
            ".agents/skills",
            ".cursor/skills",
            ".cinch/skills",
        ):
            candidate = self.project_root / rel
            if candidate.is_dir():
                roots_to_scan.append(candidate)

        # Check if project_root itself contains SKILL.md
        if (self.project_root / "SKILL.md").is_file():
            roots_to_scan.append(self.project_root)

        for extra in self.extra_roots:
            if extra.is_dir():
                roots_to_scan.append(extra)

        # Starter skills
        if self.include_starter and STARTER_DIR.is_dir():
            roots_to_scan.append(STARTER_DIR)

        for root in roots_to_scan:
            self._scan_root(root)

    def _scan_root(self, root: Path) -> None:
        if (root / "SKILL.md").is_file():
            name = root.name
            try:
                doc = parse_doc(Item(kind="skill", name=name, source=root, tags=frozenset()))
                self._skills.setdefault(doc.name, doc)
            except Exception:
                pass
            return

        for skill_md in sorted(root.rglob("SKILL.md")):
            skill_dir = skill_md.parent
            name = skill_dir.name
            try:
                doc = parse_doc(Item(kind="skill", name=name, source=skill_dir, tags=frozenset()))
                self._skills.setdefault(doc.name, doc)
            except Exception:
                pass

    @property
    def skills(self) -> dict[str, Doc]:
        return self._skills

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Handle a single JSON-RPC 2.0 request or notification."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        # Notifications do not return a response
        if req_id is None and method == "notifications/initialized":
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {
                        "prompts": {
                            "listChanged": False,
                        }
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                },
            }

        if method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {},
            }

        if method == "prompts/list":
            prompts = []
            for doc in sorted(self._skills.values(), key=lambda d: d.name):
                args = []
                raw_params = doc.extra_meta.get("parameters") if doc.extra_meta else None
                if raw_params:
                    try:
                        param_specs = parse_param_specs(raw_params)
                        for p in param_specs.values():
                            args.append(
                                {
                                    "name": p.name,
                                    "description": p.help or f"Parameter {p.name}",
                                    "required": not p.has_default,
                                }
                            )
                    except Exception:
                        pass
                prompts.append(
                    {
                        "name": doc.name,
                        "description": doc.description or f"Skill {doc.name}",
                        "arguments": args,
                    }
                )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"prompts": prompts},
            }

        if method == "prompts/get":
            prompt_name = params.get("name")
            if not prompt_name or prompt_name not in self._skills:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Prompt not found: {prompt_name}",
                    },
                }

            doc = self._skills[prompt_name]
            raw_arguments = params.get("arguments") or {}

            try:
                if doc.extra_meta and doc.extra_meta.get("parameters"):
                    resolved_doc = apply_parameters_to_doc(
                        doc,
                        cli_overrides={k: str(v) for k, v in raw_arguments.items()},
                        interactive=False,
                    )
                    prompt_text = resolved_doc.body
                else:
                    prompt_text = (
                        render_template(doc.body, raw_arguments) if raw_arguments else doc.body
                    )
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Error resolving prompt parameters: {exc}",
                    },
                }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "description": doc.description,
                    "messages": [
                        {
                            "role": "user",
                            "content": {
                                "type": "text",
                                "text": prompt_text,
                            },
                        }
                    ],
                },
            }

        if req_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            }
        return None

    def run_stdio(
        self,
        in_stream: TextIO | None = None,
        out_stream: TextIO | None = None,
    ) -> int:
        """Run line-delimited or Content-Length framed JSON-RPC loop over stdio."""
        stream_in = in_stream if in_stream is not None else sys.stdin
        stream_out = out_stream if out_stream is not None else sys.stdout

        while True:
            line = stream_in.readline()
            if not line:
                break
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.lower().startswith("content-length:"):
                try:
                    length = int(stripped.split(":", 1)[1].strip())
                    while True:
                        next_line = stream_in.readline()
                        if not next_line or next_line.strip() == "":
                            break
                    body = stream_in.read(length)
                    req = json.loads(body)
                except Exception:
                    continue
            else:
                try:
                    req = json.loads(stripped)
                except json.JSONDecodeError:
                    continue

            resp = self.handle_request(req)
            if resp is not None:
                stream_out.write(json.dumps(resp) + "\n")
                stream_out.flush()

        return 0
