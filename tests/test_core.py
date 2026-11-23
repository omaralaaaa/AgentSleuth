import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agentsleuth.parsers.codex.attachments import extract_file_markers
from agentsleuth.parsers.codex.events import classify
from agentsleuth.parsers.codex import load_threads, reconstruct_from_thread


SOURCE_SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample_rollout.jsonl"


class AgentSleuthCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sessions = self.root / "sessions" / "2026" / "11" / "22"
        self.sessions.mkdir(parents=True)
        self.rollout = self.sessions / "rollout-test.jsonl"
        shutil.copyfile(SOURCE_SAMPLE, self.rollout)

        self.db = self.root / "state_5.sqlite"
        con = sqlite3.connect(self.db)
        con.execute(
            """CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                name TEXT,
                title TEXT,
                rollout_path TEXT,
                sandbox_policy TEXT,
                cwd TEXT,
                updated_at INTEGER
            )"""
        )
        con.execute(
            "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "thread-001",
                "Conversation name from name column",
                "This is only the first user prompt",
                "sessions/2026/11/22/rollout-test.jsonl",
                '{"type":"workspace-write","network_access":false}',
                "D:\\AgentSleuth",
                100,
            ),
        )
        con.commit()
        con.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_database_uses_name_not_title(self):
        threads = load_threads(self.db)
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["name"], "Conversation name from name column")
        self.assertNotEqual(threads[0]["name"], threads[0]["raw"]["title"])

    def test_prompt_permissions_follow_turn_context(self):
        def prompt(turn, text):
            return 'response_item', dict(type='message', role='user', turn_id=turn,
                                         content=[dict(type='input_text', text=text)])
        records = [
            prompt('a', 'first'),
            ('turn_context', dict(turn_id='a', sandbox_policy={'type': 'workspace-write'},
                                  permission_profile={'type': 'managed', 'network': 'restricted'},
                                  active_permission_profile={'id': ':workspace'}, approval_policy='on-request')),
            ('turn_context', dict(turn_id='a', sandbox_policy={'type': 'read-only'})),
            prompt('a', 'second'),
            ('event_msg', dict(type='task_started', turn_id='b')),
            ('turn_context', dict(sandbox_policy={'type': 'danger-full-access'}, approval_policy='never')),
            prompt('', 'third'),
            ('event_msg', dict(type='task_complete', turn_id='b')),
            prompt('c', 'fourth'),
        ]
        self.rollout.write_text('\n'.join(json.dumps(dict(type=t, ordinal=i, payload=p))
                                          for i, (t, p) in enumerate(records)), encoding='utf-8')
        result = reconstruct_from_thread(self.db, load_threads(self.db)[0], self.root / 'results')
        labels = {e['text']: e['permissions'] for turn in result['turns'] for e in turn['entries']}
        self.assertEqual(labels, {
            'first': ':workspace · workspace-write · Network: restricted · Approval: on-request',
            'second': 'read-only', 'third': 'danger-full-access · Approval: never',
            'fourth': 'Not recorded',
        })

    def test_file_markers_become_filename_and_path(self):
        cleaned, refs = extract_file_markers(
            '<image name=[Image #1] path="D:\\mem_lab\\flag_fixed.png"></image>'
        )
        self.assertEqual(cleaned, "")
        self.assertEqual(refs[0]["filename"], "flag_fixed.png")
        self.assertEqual(refs[0]["path"], "D:\\mem_lab\\flag_fixed.png")

    def test_classification_only_recognizes_selected_records(self):
        self.assertEqual(
            classify({"type": "response_item", "payload": {"type": "custom_tool_call"}}),
            ("Tool Call", "custom_tool_call"),
        )
        self.assertIsNone(
            classify({"type": "event_msg", "payload": {"type": "token_count"}})
        )

    def test_reconstructs_rollout_and_extracts_attachments(self):
        thread = load_threads(self.db)[0]
        result = reconstruct_from_thread(self.db, thread, self.root / "results")
        summary = result["summary"]
        self.assertEqual(summary["attachments"], 2)
        self.assertGreaterEqual(summary["tool_calls"], 1)
        attachment_dir = Path(result["output_directory"]) / "attachments"
        self.assertTrue((attachment_dir / "attachment_0001.png").is_file())
        self.assertTrue((attachment_dir / "attachment_0002.wav").is_file())
        self.assertEqual(result["thread"]["name"], "Conversation name from name column")

        # Tool calls and outputs are still parsed for correlation, but are not
        # included as duplicate UI entries. Their matched executions remain visible.
        entries = [entry for turn in result["turns"] for entry in turn["entries"]]
        self.assertFalse(any(entry["kind"] in {"tool", "tool_output"} for entry in entries))
        command_executions = [
            entry for entry in entries
            if entry["kind"] == "activity"
            and entry["activity_type"] == "CommandExecution"
        ]
        self.assertEqual(len(command_executions), 1)
        self.assertEqual(command_executions[0].get("parent_call_id"), "call_example_001")
        self.assertEqual(command_executions[0].get("correlation_note"), "inferred_command_match")
        self.assertTrue(all(entry['agent'] == 'codex' and entry['session_id'] for entry in entries))
        self.assertEqual(command_executions[0]['raw']['payload']['item']['type'], 'CommandExecution')
        self.assertEqual(command_executions[0]['call_id'], 'call_example_001')


if __name__ == "__main__":
    unittest.main()
