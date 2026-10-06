from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from cinch.mcp import (
    PROTOCOL_VERSION,
    SERVER_NAME,
    McpPromptServer,
)


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_dir.name)

        # Create custom skills directory
        skills_dir = self.project / ".skills"
        skills_dir.mkdir(parents=True)

        # 1. Parameterized skill
        test_writer_dir = skills_dir / "test-writer"
        test_writer_dir.mkdir()
        (test_writer_dir / "SKILL.md").write_text(
            """---
name: test-writer
description: Write comprehensive unit tests for given target file.
parameters:
  target_file:
    type: string
    help: File path to test
  framework:
    type: string
    default: pytest
---
Generate comprehensive tests for {{ target_file }} using {{ framework }}.
""",
            encoding="utf-8",
        )

        # 2. Parameterless skill
        cleaner_dir = skills_dir / "clean-code"
        cleaner_dir.mkdir()
        (cleaner_dir / "SKILL.md").write_text(
            """---
name: clean-code
description: Refactor code cleanly.
---
Refactor the selected code following standard maintainability patterns.
""",
            encoding="utf-8",
        )

        self.server = McpPromptServer(project_root=self.project, include_starter=False)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_discovery_loads_skills(self):
        skills = self.server.skills
        self.assertIn("test-writer", skills)
        self.assertIn("clean-code", skills)
        self.assertEqual(len(skills), 2)

    def test_initialize_response(self):
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        }
        res = self.server.handle_request(req)
        self.assertIsNotNone(res)
        self.assertEqual(res["jsonrpc"], "2.0")
        self.assertEqual(res["id"], 1)
        self.assertEqual(res["result"]["protocolVersion"], PROTOCOL_VERSION)
        self.assertIn("prompts", res["result"]["capabilities"])
        self.assertEqual(res["result"]["serverInfo"]["name"], SERVER_NAME)

    def test_notification_returns_none(self):
        req = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        res = self.server.handle_request(req)
        self.assertIsNone(res)

    def test_ping(self):
        req = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
        res = self.server.handle_request(req)
        self.assertEqual(res["result"], {})

    def test_prompts_list(self):
        req = {"jsonrpc": "2.0", "id": 3, "method": "prompts/list"}
        res = self.server.handle_request(req)
        self.assertIsNotNone(res)
        prompts = res["result"]["prompts"]
        self.assertEqual(len(prompts), 2)

        prompt_dict = {p["name"]: p for p in prompts}
        self.assertIn("test-writer", prompt_dict)
        self.assertIn("clean-code", prompt_dict)

        tw = prompt_dict["test-writer"]
        self.assertEqual(tw["description"], "Write comprehensive unit tests for given target file.")
        self.assertEqual(len(tw["arguments"]), 2)
        args = {a["name"]: a for a in tw["arguments"]}
        self.assertTrue(args["target_file"]["required"])
        self.assertFalse(args["framework"]["required"])

        cc = prompt_dict["clean-code"]
        self.assertEqual(len(cc["arguments"]), 0)

    def test_prompts_get_with_parameters_and_defaults(self):
        req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "prompts/get",
            "params": {
                "name": "test-writer",
                "arguments": {
                    "target_file": "src/utils.py",
                },
            },
        }
        res = self.server.handle_request(req)
        self.assertIsNotNone(res)
        messages = res["result"]["messages"]
        self.assertEqual(len(messages), 1)
        text = messages[0]["content"]["text"]
        self.assertIn("Generate comprehensive tests for src/utils.py using pytest.", text)

    def test_prompts_get_with_explicit_overrides(self):
        req = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "prompts/get",
            "params": {
                "name": "test-writer",
                "arguments": {
                    "target_file": "src/core.py",
                    "framework": "unittest",
                },
            },
        }
        res = self.server.handle_request(req)
        text = res["result"]["messages"][0]["content"]["text"]
        self.assertIn("Generate comprehensive tests for src/core.py using unittest.", text)

    def test_prompts_get_unknown_prompt(self):
        req = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "prompts/get",
            "params": {"name": "nonexistent-skill"},
        }
        res = self.server.handle_request(req)
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -32602)
        self.assertIn("Prompt not found", res["error"]["message"])

    def test_unknown_method_error(self):
        req = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/list",
        }
        res = self.server.handle_request(req)
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -32601)

    def test_run_stdio_newline_delimited_flow(self):
        in_stream = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "prompts/list"})
            + "\n"
        )
        out_stream = io.StringIO()

        ret = self.server.run_stdio(in_stream=in_stream, out_stream=out_stream)
        self.assertEqual(ret, 0)

        lines = [ln for ln in out_stream.getvalue().splitlines() if ln.strip()]
        out_lines = [json.loads(ln) for ln in lines]
        self.assertEqual(len(out_lines), 2)
        self.assertEqual(out_lines[0]["id"], 1)
        self.assertEqual(out_lines[1]["id"], 2)
        self.assertEqual(len(out_lines[1]["result"]["prompts"]), 2)

    def test_run_stdio_content_length_framed_flow(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 10, "method": "ping"})
        frame = f"Content-Length: {len(body)}\r\n\r\n{body}"
        in_stream = io.StringIO(frame)
        out_stream = io.StringIO()

        ret = self.server.run_stdio(in_stream=in_stream, out_stream=out_stream)
        self.assertEqual(ret, 0)

        lines = [ln for ln in out_stream.getvalue().splitlines() if ln.strip()]
        out_lines = [json.loads(ln) for ln in lines]
        self.assertEqual(len(out_lines), 1)
        self.assertEqual(out_lines[0]["id"], 10)


if __name__ == "__main__":
    unittest.main()
