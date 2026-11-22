# AgentSleuth — Modular Edition v0.2.2

AgentSleuth reads a Codex `state_5.sqlite` database in read-only mode, lists rows from `threads`, resolves each row's `rollout_path`, reconstructs the conversation, and extracts explicitly embedded attachments to a separate output folder.

## Run

Requirements: Python 3.10+ with Tkinter installed. The application uses only the Python standard library.

```powershell
uv run script.py
```

Or:

```bash
python main.py
```

## Project layout

```text
AgentSleuth_Modular/
├── script.py                    # uv-compatible launcher
├── main.py                      # python launcher
├── agentsleuth/
│   ├── config.py                # Limits, MIME types, regex patterns
│   ├── utils.py                 # Shared text, turn, hash helpers
│   ├── database.py              # Read-only SQLite access and threads table
│   ├── paths.py                 # Rollout path resolution and output folders
│   ├── attachments.py           # Base64 decoding and attachment markers
│   ├── codex_parser.py          # Record classification, normalization, correlation
│   ├── recovery.py              # Rebuild files represented in FileChange events
│   ├── reconstruction.py        # Full rollout-to-conversation pipeline
│   ├── formatting.py            # Pretty formatting for tool inputs/outputs
│   └── ui/
│       ├── app.py               # Tk root and application startup
│       ├── layout.py            # Window layout, styles and scrolling
│       ├── controller.py        # Loading DB, selecting threads, background tasks
│       └── conversation.py      # Rendering messages, tools, executions and file links
└── tests/
    └── test_core.py             # Core parser and SQLite tests
```

## Module responsibilities

| File | Responsibility |
|---|---|
| `config.py` | Global limits, recognized attachment fields and marker patterns |
| `utils.py` | Reusable small helpers shared across modules |
| `database.py` | Read `threads` from SQLite without modifying the database |
| `paths.py` | Resolve `rollout_path`, sanitize output folder names |
| `attachments.py` | Decode known Base64/data-URI attachment fields; extract filename/path markers |
| `codex_parser.py` | Classify and normalize Codex records; correlate tool calls and activities |
| `recovery.py` | Recover content explicitly recorded in `FileChange` items |
| `reconstruction.py` | Orchestrate the full reconstruction workflow |
| `formatting.py` | Format JSON-like arguments and tool output for display |
| `ui/layout.py` | Build the Tkinter window and apply styles |
| `ui/controller.py` | UI actions and background loading/reconstruction |
| `ui/conversation.py` | Render reconstructed conversation cards and safe file-location links |
| `ui/app.py` | Create the Tk root and combine UI mixins |

## Tests

From this folder:

```bash
python -m unittest discover -s tests -v
```

## Current GUI behavior

- Loading `state_5.sqlite` only lists conversations; no rollout is parsed automatically.
- A rollout is parsed only after the user selects a conversation; parsed results are cached for the current output folder.
- Mouse-wheel scrolling works anywhere over the conversation pane, including message cards and nested text widgets.
- Message bodies and tool outputs render in full; text wraps to the card width, measures its actual display-line count after layout, and the outer conversation pane handles scrolling (no per-message row cap or horizontal text scrollbar).
- Tool-call and tool-output records are parsed and correlated internally using `call_id`, turn boundaries, ordinal ranges and command matching, but are not rendered as separate cards. This avoids duplicate content and reduces UI rendering cost.
- The conversation summary displays the number of visible activities rather than hidden tool-call records.
- Matched `CommandExecution`, `FileChange`, MCP and other supported activity records are rendered as standalone activity cards; command and aggregated output remain visible in the execution card.
- A rendering failure in one record is isolated to that record and does not prevent later conversation entries from rendering.
- Attachment and recovered-file links point to AgentSleuth's extracted/rebuilt copies. Historical source paths from the rollout are not used as link targets.
- Clicking a file link reveals its location in the system file manager; the file itself is not launched.

## Evidence handling notes

- SQLite is opened with `mode=ro` and `PRAGMA query_only=ON`.
- Rollout JSONL and source attachments are read, not executed.
- Embedded attachments are decoded only from recognized Base64 fields/data URIs and are written under the selected results directory.
- FileChange recovery only writes content explicitly present in the log. It does not claim to reproduce bytes that were never recorded.
- Tool-call/activity links may be inferred from the rollout event sequence and command matching; they are not treated as direct parent-ID proof unless the log contains an explicit link.
