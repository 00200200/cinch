from __future__ import annotations

import io
import json
import unittest

from cinch.cli import main
from cinch.lsp import (
    COMPLETION_PROPERTY,
    COMPLETION_SNIPPET,
    COMPLETION_VALUE,
    SERVER_NAME,
    SERVER_VERSION,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    LspServer,
    parse_diagnostics,
)


class LspServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = LspServer()

    def test_initialize(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"capabilities": {}},
        }
        resp, notifs = self.server.handle_message(req)
        self.assertEqual(notifs, [])
        self.assertIsNotNone(resp)
        self.assertEqual(resp["id"], 1)
        res = resp["result"]
        self.assertEqual(res["serverInfo"]["name"], SERVER_NAME)
        self.assertEqual(res["serverInfo"]["version"], SERVER_VERSION)
        caps = res["capabilities"]
        self.assertTrue(caps["hoverProvider"])
        self.assertIn("textDocumentSync", caps)
        self.assertIn("completionProvider", caps)

    def test_initialized_notification(self) -> None:
        msg = {
            "jsonrpc": "2.0",
            "method": "initialized",
            "params": {},
        }
        resp, notifs = self.server.handle_message(msg)
        self.assertIsNone(resp)
        self.assertEqual(notifs, [])

    def test_shutdown_and_exit(self) -> None:
        msg_shutdown = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "shutdown",
            "params": {},
        }
        resp, notifs = self.server.handle_message(msg_shutdown)
        self.assertIsNotNone(resp)
        self.assertIsNone(resp["result"])
        self.assertTrue(self.server.is_shutdown)

        msg_exit = {
            "jsonrpc": "2.0",
            "method": "exit",
            "params": {},
        }
        resp_exit, notifs_exit = self.server.handle_message(msg_exit)
        self.assertIsNone(resp_exit)
        self.assertEqual(notifs_exit, [])

    def test_unknown_method(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "custom/unknownMethod",
            "params": {},
        }
        resp, notifs = self.server.handle_message(req)
        self.assertIsNotNone(resp)
        self.assertEqual(resp["error"]["code"], -32601)

    def test_did_open_valid_skill(self) -> None:
        uri = "file:///workspace/SKILL.md"
        valid_text = (
            "---\n"
            "name: test-runner\n"
            "description: Run test suites cleanly across test targets.\n"
            "---\n\n"
            "Body content goes here.\n"
        )
        msg = {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "markdown",
                    "version": 1,
                    "text": valid_text,
                }
            },
        }
        resp, notifs = self.server.handle_message(msg)
        self.assertIsNone(resp)
        self.assertEqual(len(notifs), 1)
        notif = notifs[0]
        self.assertEqual(notif["method"], "textDocument/publishDiagnostics")
        self.assertEqual(notif["params"]["uri"], uri)
        self.assertEqual(notif["params"]["diagnostics"], [])

    def test_diagnostics_missing_frontmatter(self) -> None:
        diags = parse_diagnostics("Just some markdown without frontmatter.")
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0]["code"], "E002")
        self.assertEqual(diags[0]["severity"], SEVERITY_ERROR)
        self.assertIn("Missing YAML frontmatter", diags[0]["message"])

    def test_diagnostics_unclosed_frontmatter(self) -> None:
        diags = parse_diagnostics("---\nname: my-skill\ndescription: Some description here\n")
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0]["code"], "E002")
        self.assertEqual(diags[0]["severity"], SEVERITY_ERROR)
        self.assertIn("Unclosed YAML frontmatter", diags[0]["message"])

    def test_diagnostics_unrecognized_key_with_suggestion(self) -> None:
        text = "---\nname: my-skill\ndesc: Short description for the skill here.\n---\n"
        diags = parse_diagnostics(text)
        unrecognized = [d for d in diags if d["code"] == "E005"]
        self.assertEqual(len(unrecognized), 1)
        self.assertIn("Unrecognized frontmatter key 'desc'", unrecognized[0]["message"])
        self.assertIn("Did you mean 'description'?", unrecognized[0]["message"])

    def test_diagnostics_aliases_suggestions(self) -> None:
        text = (
            "---\n"
            "name: my-skill\n"
            "description: Valid description of the skill.\n"
            "variables:\n"
            "  env: staging\n"
            "compatibility: cursor\n"
            "---\n"
        )
        diags = parse_diagnostics(text)
        msgs = [d["message"] for d in diags if d["code"] == "E005"]
        self.assertTrue(any("variables" in m and "parameters" in m for m in msgs))
        self.assertTrue(any("compatibility" in m and "applyTo" in m for m in msgs))

    def test_diagnostics_invalid_kebab_case_name(self) -> None:
        text = (
            "---\n"
            "name: Invalid_Skill_Name!\n"
            "description: Proper description with enough characters.\n"
            "---\n"
        )
        diags = parse_diagnostics(text)
        kebab_diags = [d for d in diags if d["code"] == "W001"]
        self.assertEqual(len(kebab_diags), 1)
        self.assertEqual(kebab_diags[0]["severity"], SEVERITY_WARNING)

    def test_diagnostics_short_description(self) -> None:
        text = "---\nname: my-skill\ndescription: Short\n---\n"
        diags = parse_diagnostics(text)
        desc_diags = [d for d in diags if d["code"] == "W002"]
        self.assertEqual(len(desc_diags), 1)

    def test_diagnostics_too_long_description(self) -> None:
        text = f"---\nname: my-skill\ndescription: {'a' * 1050}\n---\n"
        diags = parse_diagnostics(text)
        long_diags = [d for d in diags if d["code"] == "E007"]
        self.assertEqual(len(long_diags), 1)
        self.assertEqual(long_diags[0]["severity"], SEVERITY_ERROR)

    def test_diagnostics_invalid_glob_backslash(self) -> None:
        text = (
            "---\n"
            "name: my-skill\n"
            "description: Valid description of the skill.\n"
            "paths:\n"
            "  - 'src\\**\\*.py'\n"
            "---\n"
        )
        diags = parse_diagnostics(text)
        glob_diags = [d for d in diags if d["code"] == "W004"]
        self.assertEqual(len(glob_diags), 1)
        self.assertIn("contains backslashes", glob_diags[0]["message"])

    def test_diagnostics_tabs_forbidden(self) -> None:
        text = "---\nname: my-skill\n\tdescription: Tab indented description here.\n---\n"
        diags = parse_diagnostics(text)
        tab_diags = [d for d in diags if "Tabs are not allowed" in d["message"]]
        self.assertEqual(len(tab_diags), 1)

    def test_diagnostics_did_change_and_did_close(self) -> None:
        uri = "file:///workspace/SKILL.md"
        # Open with invalid name
        bad_text = "---\nname: Bad_Name\ndescription: A valid long description.\n---\n"
        good_text = "---\nname: good-name\ndescription: A valid long description.\n---\n"
        self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "version": 1,
                        "text": bad_text,
                    }
                },
            }
        )
        # Change to valid name
        _, notifs = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didChange",
                "params": {
                    "textDocument": {"uri": uri, "version": 2},
                    "contentChanges": [{"text": good_text}],
                },
            }
        )
        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0]["params"]["diagnostics"], [])

        # Close doc
        _, close_notifs = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didClose",
                "params": {"textDocument": {"uri": uri}},
            }
        )
        self.assertEqual(len(close_notifs), 1)
        self.assertEqual(close_notifs[0]["params"]["diagnostics"], [])
        self.assertNotIn(uri, self.server.documents)

    def test_completion_snippet_empty_file(self) -> None:
        uri = "file:///workspace/empty.md"
        self.server.documents[uri] = ""
        req = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 0, "character": 0},
            },
        }
        resp, _ = self.server.handle_message(req)
        self.assertIsNotNone(resp)
        items = resp["result"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["label"], "frontmatter")
        self.assertEqual(items[0]["kind"], COMPLETION_SNIPPET)

    def test_completion_keys_inside_frontmatter(self) -> None:
        uri = "file:///workspace/SKILL.md"
        self.server.documents[uri] = "---\nname: my-skill\n\n---\n"
        req = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 2, "character": 0},
            },
        }
        resp, _ = self.server.handle_message(req)
        self.assertIsNotNone(resp)
        items = resp["result"]["items"]
        labels = [item["label"] for item in items]
        self.assertIn("name", labels)
        self.assertIn("description", labels)
        self.assertIn("paths", labels)
        self.assertIn("globs", labels)
        self.assertIn("applyTo", labels)
        self.assertIn("parameters", labels)
        self.assertIn("disable-model-invocation", labels)
        self.assertTrue(all(item["kind"] == COMPLETION_PROPERTY for item in items))

    def test_completion_apply_to_dialects(self) -> None:
        uri = "file:///workspace/SKILL.md"
        self.server.documents[uri] = "---\nname: my-skill\napplyTo: \n---\n"
        req = {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 2, "character": 9},
            },
        }
        resp, _ = self.server.handle_message(req)
        self.assertIsNotNone(resp)
        items = resp["result"]["items"]
        labels = [item["label"] for item in items]
        self.assertIn("cursor", labels)
        self.assertIn("claude", labels)
        self.assertIn("windsurf", labels)
        self.assertIn("zed", labels)
        self.assertTrue(all(item["kind"] == COMPLETION_VALUE for item in items))

    def test_completion_disable_model_invocation(self) -> None:
        uri = "file:///workspace/SKILL.md"
        self.server.documents[uri] = "---\nname: my-skill\ndisable-model-invocation: \n---\n"
        req = {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 2, "character": 26},
            },
        }
        resp, _ = self.server.handle_message(req)
        self.assertIsNotNone(resp)
        items = resp["result"]["items"]
        labels = [item["label"] for item in items]
        self.assertIn("true", labels)
        self.assertIn("false", labels)

    def test_completion_paths_globs(self) -> None:
        uri = "file:///workspace/SKILL.md"
        self.server.documents[uri] = "---\nname: my-skill\npaths:\n  - \n---\n"
        req = {
            "jsonrpc": "2.0",
            "id": 14,
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 3, "character": 4},
            },
        }
        resp, _ = self.server.handle_message(req)
        self.assertIsNotNone(resp)
        items = resp["result"]["items"]
        labels = [item["label"] for item in items]
        self.assertIn('"**/*.py"', labels)
        self.assertIn('"**/*.ts"', labels)

    def test_hover_frontmatter_key(self) -> None:
        uri = "file:///workspace/SKILL.md"
        self.server.documents[uri] = (
            "---\n"
            "name: my-skill\n"
            "description: Long description here.\n"
            "disable-model-invocation: true\n"
            "---\n"
        )
        req = {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "textDocument/hover",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 1, "character": 2},
            },
        }
        resp, _ = self.server.handle_message(req)
        self.assertIsNotNone(resp)
        res = resp["result"]
        self.assertIn("### `name`", res["contents"]["value"])
        self.assertIn("kebab-case", res["contents"]["value"])

        # Hover over disable-model-invocation
        req["id"] = 21
        req["params"]["position"] = {"line": 3, "character": 5}
        resp2, _ = self.server.handle_message(req)
        self.assertIn("disable-model-invocation", resp2["result"]["contents"]["value"])
        self.assertIn("Claude Code", resp2["result"]["contents"]["value"])

    def test_hover_dialect(self) -> None:
        uri = "file:///workspace/SKILL.md"
        self.server.documents[uri] = "---\nname: my-skill\napplyTo: cursor\n---\n"
        req = {
            "jsonrpc": "2.0",
            "id": 22,
            "method": "textDocument/hover",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 2, "character": 11},
            },
        }
        resp, _ = self.server.handle_message(req)
        self.assertIsNotNone(resp)
        res = resp["result"]
        self.assertIn("Cursor IDE", res["contents"]["value"])

    def test_hover_alias_suggestion(self) -> None:
        uri = "file:///workspace/SKILL.md"
        self.server.documents[uri] = "---\nname: my-skill\ndesc: A brief description\n---\n"
        req = {
            "jsonrpc": "2.0",
            "id": 23,
            "method": "textDocument/hover",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": 2, "character": 2},
            },
        }
        resp, _ = self.server.handle_message(req)
        self.assertIsNotNone(resp)
        self.assertIn("Did you mean", resp["result"]["contents"]["value"])
        self.assertIn("description", resp["result"]["contents"]["value"])

    def test_run_stdio_framed_flow(self) -> None:
        body1 = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        skill_text = "---\nname: foo-bar\ndescription: Proper description here.\n---\n"
        body2 = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///test.md",
                        "text": skill_text,
                    }
                },
            }
        )
        body3 = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "shutdown"})
        body4 = json.dumps({"jsonrpc": "2.0", "method": "exit"})

        stream_data = (
            f"Content-Length: {len(body1.encode())}\r\n\r\n{body1}"
            f"Content-Length: {len(body2.encode())}\r\n\r\n{body2}"
            f"Content-Length: {len(body3.encode())}\r\n\r\n{body3}"
            f"Content-Length: {len(body4.encode())}\r\n\r\n{body4}"
        )
        in_stream = io.BytesIO(stream_data.encode())
        out_stream = io.BytesIO()

        server = LspServer()
        ret = server.run_stdio(in_stream=in_stream, out_stream=out_stream)
        self.assertEqual(ret, 0)

        out_bytes = out_stream.getvalue()
        self.assertIn(b"Content-Length:", out_bytes)
        self.assertIn(b"cinch-lsp", out_bytes)
        self.assertIn(b"publishDiagnostics", out_bytes)

    def test_cli_lsp_help(self) -> None:
        ret = main(["lsp", "--help"])
        self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()
