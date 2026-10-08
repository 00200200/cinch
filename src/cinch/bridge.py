"""Dynamic MCP server schema bridge for Cinch.

Connects to Model Context Protocol (MCP) servers via stdio JSON-RPC, introspects
tool manifests (tools/list), and synthesizes clean, documented Cinch skills
wrapping each tool with input schemas and execution guidance.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _kebab(name: str) -> str:
    """Normalize identifier to kebab-case."""
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]+", "-", name.strip())
    cleaned = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", cleaned)
    cleaned = re.sub(r"[\s_]+", "-", cleaned)
    return re.sub(r"-+", "-", cleaned).strip("-").lower()


@dataclass
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)

    @property
    def properties(self) -> dict[str, Any]:
        return self.input_schema.get("properties", {})

    @property
    def required(self) -> list[str]:
        return self.input_schema.get("required", [])


class McpBridgeClient:
    """Simple stdio JSON-RPC client for introspecting MCP servers."""

    def __init__(self, command: Sequence[str] | str, timeout: float = 10.0) -> None:
        if isinstance(command, str):
            self.cmd = shlex.split(command)
        else:
            self.cmd = list(command)
        self.timeout = timeout

    def introspect_tools(self) -> list[McpTool]:
        """Spawn server, perform JSON-RPC handshake, and retrieve tools/list."""
        proc = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        try:
            # 1. Initialize
            init_req = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "cinch", "version": "0.1.0"},
                },
            }
            assert proc.stdin is not None
            proc.stdin.write(json.dumps(init_req) + "\n")
            proc.stdin.flush()

            # Read initialize response
            self._read_response(proc, req_id=1)

            # 2. Initialized notification
            init_notif = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }
            proc.stdin.write(json.dumps(init_notif) + "\n")
            proc.stdin.flush()

            # 3. tools/list
            tools_req = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            }
            proc.stdin.write(json.dumps(tools_req) + "\n")
            proc.stdin.flush()

            tools_resp = self._read_response(proc, req_id=2)
            result = tools_resp.get("result", {})
            raw_tools = result.get("tools", [])

            return [
                McpTool(
                    name=t.get("name", "unnamed"),
                    description=t.get("description", "").strip(),
                    input_schema=t.get("inputSchema", {}),
                )
                for t in raw_tools
            ]

        finally:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                proc.kill()

    def _read_response(self, proc: subprocess.Popen, req_id: int) -> dict[str, Any]:
        assert proc.stdout is not None
        while True:
            line = proc.stdout.readline()
            if not line:
                stderr = proc.stderr.read() if proc.stderr else ""
                raise RuntimeError(
                    f"MCP server exited unexpectedly without responding to id={req_id}. "
                    f"Stderr: {stderr.strip()}"
                )
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(f"MCP RPC Error ({req_id}): {msg['error']}")
                return msg


def synthesize_skill_from_tool(server_name: str, tool: McpTool) -> tuple[str, str]:
    """Synthesize canonical (skill_slug, skill_markdown) from an MCP tool."""
    srv_slug = _kebab(server_name)
    tool_slug = _kebab(tool.name)
    skill_name = f"mcp-{srv_slug}-{tool_slug}" if srv_slug else f"mcp-{tool_slug}"

    desc = tool.description or f"Invoke {tool.name} tool on {server_name} MCP server."
    # Clean description for YAML header
    desc_clean = desc.replace("\n", " ").strip()
    if len(desc_clean) > 200:
        desc_clean = desc_clean[:197] + "..."

    # Build YAML frontmatter
    fm_lines = [
        "---",
        f'name: "{skill_name}"',
        f'description: "{desc_clean}"',
    ]

    props = tool.properties
    required_set = set(tool.required)

    if props:
        fm_lines.append("parameters:")
        for prop_name, prop_meta in props.items():
            p_type = prop_meta.get("type", "string")
            p_help = prop_meta.get("description", "").replace("\n", " ").strip()
            fm_lines.append(f"  {prop_name}:")
            fm_lines.append(f"    type: {p_type}")
            if p_help:
                fm_lines.append(f'    help: "{p_help}"')
            if prop_name in required_set:
                fm_lines.append("    required: true")
            elif "default" in prop_meta:
                fm_lines.append(f"    default: {json.dumps(prop_meta['default'])}")

    fm_lines.append("---")
    fm_block = "\n".join(fm_lines)

    # Build Markdown instructions
    body_lines = [
        fm_block,
        "",
        f"# MCP Tool: {tool.name}",
        "",
        tool.description or "No description provided by MCP tool manifest.",
        "",
        "## Server & Tool Reference",
        f"- **MCP Server**: `{server_name}`",
        f"- **Tool Method**: `{tool.name}`",
        "",
    ]

    if props:
        body_lines.append("## Parameter Specifications")
        body_lines.append("| Parameter | Type | Required | Description |")
        body_lines.append("| :--- | :--- | :---: | :--- |")
        for prop_name, prop_meta in props.items():
            p_type = prop_meta.get("type", "string")
            p_req = "✅ Yes" if prop_name in required_set else "No"
            p_desc = prop_meta.get("description", "—").replace("|", "\\|")
            body_lines.append(f"| `{prop_name}` | `{p_type}` | {p_req} | {p_desc} |")
        body_lines.append("")

    body_lines.append("## Execution & Tool Invocation Guidelines")
    body_lines.append(
        f"When an operation requires `{tool.name}`, formulate and send the tool call "
        f"to the `{server_name}` MCP server."
    )
    if required_set:
        req_list = ", ".join(f"`{r}`" for r in sorted(required_set))
        body_lines.append(f"Ensure all required parameters ({req_list}) are properly validated.")
    body_lines.append(
        "Inspect the resulting structured tool output and handle error diagnostics gracefully."
    )

    return skill_name, "\n".join(body_lines) + "\n"


@dataclass
class BridgeResult:
    server: str
    skills_generated: list[str] = field(default_factory=list)
    written_files: list[Path] = field(default_factory=list)
    preview: list[tuple[str, str]] = field(default_factory=list)


def bridge_mcp_server(
    server_cmd: Sequence[str] | str | None = None,
    server_name: str | None = None,
    config_path: Path | str | None = None,
    output_dir: Path | str = ".skills",
    dry_run: bool = False,
    mock_tools: list[McpTool] | None = None,
) -> list[BridgeResult]:
    """Bridge MCP server(s) to Cinch skills."""
    out_root = Path(output_dir)
    results: list[BridgeResult] = []

    if config_path:
        cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
        mcp_servers = cfg.get("mcpServers", {})
        for s_name, s_conf in mcp_servers.items():
            cmd = s_conf.get("command")
            args = s_conf.get("args", [])
            full_cmd = [cmd] + args if cmd else []
            if not full_cmd:
                continue
            tools = McpBridgeClient(full_cmd).introspect_tools()
            res = _process_server_tools(s_name, tools, out_root, dry_run)
            results.append(res)
        return results

    if mock_tools is not None:
        name = server_name or "mock-server"
        res = _process_server_tools(name, mock_tools, out_root, dry_run)
        return [res]

    if not server_cmd:
        raise ValueError("Either server_cmd, config_path, or mock_tools must be provided.")

    if isinstance(server_cmd, str):
        cmd_parts = shlex.split(server_cmd)
    else:
        cmd_parts = list(server_cmd)

    name = server_name or (Path(cmd_parts[0]).name if cmd_parts else "mcp-server")
    client = McpBridgeClient(cmd_parts)
    tools = client.introspect_tools()
    res = _process_server_tools(name, tools, out_root, dry_run)
    return [res]


def _process_server_tools(
    server_name: str,
    tools: list[McpTool],
    out_root: Path,
    dry_run: bool,
) -> BridgeResult:
    result = BridgeResult(server=server_name)

    for tool in tools:
        skill_name, content = synthesize_skill_from_tool(server_name, tool)
        result.skills_generated.append(skill_name)
        target_file = out_root / skill_name / "SKILL.md"

        if dry_run:
            result.preview.append((str(target_file), content))
        else:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(content, encoding="utf-8")
            result.written_files.append(target_file)

    return result
