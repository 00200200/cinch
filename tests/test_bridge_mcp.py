"""Tests for the dynamic MCP server schema bridge (cinch bridge mcp)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from cinch.bridge import (
    McpBridgeClient,
    McpTool,
    _kebab,
    bridge_mcp_server,
    synthesize_skill_from_tool,
)
from cinch.cli import main


def test_kebab_normalization():
    assert _kebab("readFile") == "read-file"
    assert _kebab("read_file") == "read-file"
    assert _kebab("Read File Now") == "read-file-now"
    assert _kebab("mcp_server_123") == "mcp-server-123"


def test_synthesize_skill_from_tool():
    tool = McpTool(
        name="read_file",
        description="Read file contents from the local filesystem.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative file path to read",
                },
                "encoding": {
                    "type": "string",
                    "description": "Text encoding format",
                    "default": "utf-8",
                },
            },
            "required": ["path"],
        },
    )

    skill_name, content = synthesize_skill_from_tool("filesystem", tool)
    assert skill_name == "mcp-filesystem-read-file"
    assert 'name: "mcp-filesystem-read-file"' in content
    assert "parameters:" in content
    assert "path:" in content
    assert "required: true" in content
    assert "encoding:" in content
    assert "# MCP Tool: read_file" in content
    assert "| `path` | `string` | ✅ Yes |" in content
    assert "| `encoding` | `string` | No |" in content
    assert "Ensure all required parameters (`path`) are properly validated." in content


def test_bridge_mcp_server_with_mock_tools(tmp_path: Path):
    tools = [
        McpTool(
            name="query_db",
            description="Run a read-only SQL query against Postgres database.",
            input_schema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL query string"},
                },
                "required": ["sql"],
            },
        ),
        McpTool(
            name="list_tables",
            description="List all public database tables.",
        ),
    ]

    out_dir = tmp_path / ".skills"

    # Dry-run test
    dry_results = bridge_mcp_server(
        mock_tools=tools,
        server_name="postgres",
        output_dir=out_dir,
        dry_run=True,
    )
    assert len(dry_results) == 1
    assert len(dry_results[0].skills_generated) == 2
    assert len(dry_results[0].written_files) == 0
    assert len(dry_results[0].preview) == 2
    assert not out_dir.exists()

    # Real write test
    results = bridge_mcp_server(
        mock_tools=tools,
        server_name="postgres",
        output_dir=out_dir,
        dry_run=False,
    )
    assert len(results[0].written_files) == 2
    skill_file = out_dir / "mcp-postgres-query-db" / "SKILL.md"
    assert skill_file.is_file()
    text = skill_file.read_text(encoding="utf-8")
    assert "mcp-postgres-query-db" in text
    assert "SQL query string" in text


def test_bridge_mcp_server_with_mock_subprocess(tmp_path: Path):
    # Create a minimal mock python script that acts as an MCP server
    mock_server_script = tmp_path / "mock_server.py"
    mock_server_script.write_text(
        """import sys, json

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    req_id = req.get("id")
    method = req.get("method")
    
    if method == "initialize":
        res = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "mock-mcp", "version": "1.0.0"}
            }
        }
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        res = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo back input text",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "message": {"type": "string", "description": "Text to echo"}
                            },
                            "required": ["message"]
                        }
                    }
                ]
            }
        }
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
""",
        encoding="utf-8",
    )

    out_dir = tmp_path / "skills_out"
    client = McpBridgeClient([sys.executable, str(mock_server_script)])
    tools = client.introspect_tools()
    assert len(tools) == 1
    assert tools[0].name == "echo"
    assert "message" in tools[0].properties

    # Bridge via bridge_mcp_server
    results = bridge_mcp_server(
        server_cmd=[sys.executable, str(mock_server_script)],
        server_name="echo-server",
        output_dir=out_dir,
    )
    assert len(results) == 1
    assert "mcp-echo-server-echo" in results[0].skills_generated
    assert (out_dir / "mcp-echo-server-echo" / "SKILL.md").is_file()


def test_bridge_cli_integration(tmp_path: Path):
    # Test CLI invocation without subcommand
    assert main(["bridge"]) == 1

    # Test CLI invocation with --dry-run and mock tool via config
    mock_server_script = tmp_path / "mock_server.py"
    mock_server_script.write_text(
        """import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    req = json.loads(line)
    req_id = req.get("id")
    method = req.get("method")
    if method == "initialize":
        res = {"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05"}}
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "tools/list":
        res = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": [{"name": "ping", "description": "Ping test"}]},
        }
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
""",
        encoding="utf-8",
    )

    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "test-srv": {
                        "command": sys.executable,
                        "args": [str(mock_server_script)],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["bridge", "mcp", "--config", str(config_file), "--dry-run"])
    assert exit_code == 0
