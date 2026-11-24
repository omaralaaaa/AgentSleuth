import unittest

from agentsleuth.core.search import TranscriptIndex


class RecordedFilterTests(unittest.TestCase):
    def test_type_aliases_are_hidden_only_when_they_match_a_category(self):
        runcmd = dict(kind='activity', activity_type='CommandExecution', status='completed')
        change = dict(kind='activity', activity_type='FileChange', status='failed')
        turn = dict(title='Codex', entries=[runcmd, change])
        index = TranscriptIndex([turn])
        self.assertEqual(index.filters, ('All entries', 'Commands', 'File changes',
                                         'Status: completed', 'Status: failed'))
        self.assertEqual(index.turn_filters[0], index.filters)
        self.assertEqual([entry for _, _, entry in index.matches('', 'Commands')], [runcmd])
        self.assertEqual([entry for _, _, entry in index.matches('', 'File changes')], [change])

        bash = dict(kind='activity', activity_type='ToolExecution', execution=dict(tool='bash'))
        index = TranscriptIndex([turn, dict(title='Agent activity', entries=[bash])])
        self.assertIn('Type: CommandExecution', index.filters)
        self.assertNotIn('Type: CommandExecution', index.turn_filters[0])
        self.assertIn('Tool: bash', index.filters)
        self.assertEqual([entry for _, _, entry in index.matches('', 'Commands')], [runcmd, bash])
        self.assertEqual([entry for _, _, entry in index.matches('', 'Type: CommandExecution')], [runcmd])

    def test_choices_and_results_use_the_same_recorded_values(self):
        entries = [
            dict(kind='activity', activity_type='ToolExecution',
                 execution=dict(tool='bash', status='failed', recorded_status='error')),
            dict(kind='message', role='assistant', event_type='assistant_error', text='Timed out'),
            dict(kind='activity', activity_type='file_attachment'),
            dict(kind='activity', activity_type='McpToolCall', item=dict(tool='lookup')),
            dict(kind='activity', activity_type='ToolExecution', tool_name='view_file'),
            dict(kind='activity', activity_type='LIST_DIRECTORY', status=0),
            dict(kind='activity', activity_type='ToolExecution', execution=dict(tool='Edit')),
        ]
        index = TranscriptIndex([dict(title='First', entries=entries[:3]),
                                 dict(title='Second', entries=entries[3:])])
        for choice, positions in [('Commands', [0]), ('Status: error', [0]), ('Errors', [1]),
                                  ('Agent messages', [1]), ('Attachments', [2]), ('Tool: lookup', [3]), ('Tool: view_file', [4]),
                                  ('Type: LIST_DIRECTORY', [5]), ('Status: 0', [5]), ('File changes', [6])]:
            with self.subTest(choice=choice):
                self.assertIn(choice, index.filters)
                self.assertEqual([e for _, _, e in index.matches('', choice)], [entries[i] for i in positions])
        self.assertNotIn('Status: failed', index.filters)
        self.assertNotIn('Tool: lookup', index.turn_filters[0])
        self.assertNotIn('Commands', index.turn_filters[1])
        for turn, choices in enumerate(index.turn_filters):
            for choice in choices:
                self.assertTrue(list(index.matches('', choice, turn)))
