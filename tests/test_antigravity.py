import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from agentsleuth.parsers import antigravity as provider


class AntigravityTests(unittest.TestCase):
    def test_index_transcript_and_metadata_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = root / 'conversation_summaries.db'
            with closing(sqlite3.connect(index)) as db, db:
                db.execute('CREATE TABLE conversation_summaries '
                           '(conversation_id, title, workspace_uris, last_modified_time)')
                db.executemany('INSERT INTO conversation_summaries VALUES (?, ?, ?, ?)',
                               [('session', 'Example', '["file:///workspace"]', 1),
                                ('../outside', 'Missing', '[]', 0)])
            thread, missing = provider.load_threads(index)
            self.assertEqual(thread['cwd'], 'file:///workspace')
            self.assertEqual(provider.reconstruct_from_thread(index, missing)['turns'], [])
            dbpath = root / 'conversations' / 'session.db'
            dbpath.parent.mkdir()
            with closing(sqlite3.connect(dbpath)) as db, db:
                db.execute('CREATE TABLE steps(idx, step_type, status)')
                db.execute('INSERT INTO steps VALUES (7, 5, 3)')
            metadata = provider.reconstruct_from_thread(index, thread)
            self.assertIn('metadata only', metadata['source_detail'])
            self.assertEqual(metadata['turns'][0]['entries'][0]['step_index'], 7)
            transcript = root / 'brain/session/.system_generated/logs/transcript.jsonl'
            transcript.parent.mkdir(parents=True)
            records = [dict(type='USER_INPUT', content='Inspect the log', step_index=1),
                       dict(type='PLANNER_RESPONSE', tool_calls=[dict(name='view_file', args={'path':'log'})]),
                       dict(type='VIEW_FILE', content='Recorded result', truncated_fields=['content']),
                       dict(type='PLANNER_RESPONSE', content='Done'), dict(type='USER_INPUT', content='Next')]
            transcript.write_text('\n'.join(map(json.dumps, records)) + '\n{broken', encoding='utf-8')
            for source in (index, dbpath, transcript):
                selected = provider.load_threads(source)[0]
                result = provider.reconstruct_from_thread(source, selected)
                self.assertEqual(result['source_path'], str(transcript))
                self.assertEqual(result['summary']['turns'], 2)
                self.assertEqual(result['summary']['tool_calls'], 1)
                first, second = result['turns']
                self.assertEqual(first['entries'][0]['role'], 'user')
                self.assertEqual(first['entries'][2]['truncated_fields'], ['content'])
                self.assertEqual(first['entries'][-1]['role'], 'assistant')
                self.assertEqual(second['entries'][-1]['activity_type'], 'UNREADABLE_RECORD')
