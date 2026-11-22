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
agentsleuth/
    core/            Shared text, formatting and filesystem helpers
    parsers/
        codex/       SQLite discovery, JSONL events, attachments and recovery
    ui/              Desktop layout, background controller and transcript viewer
tests/               Parser fixtures, reconstruction tests and GUI regressions
main.py              Python launcher
script.py            uv-compatible launcher
```

### Adding an evidence parser

Create a sibling package under `agentsleuth/parsers/`. Its public module should
expose `name`, `source_label`, `source_hint`, `filetypes`, `load_threads(path)` and
`reconstruct_from_thread(path, thread, output_root, progress)`. The desktop app
accepts the module as `App(parser=provider)` and defaults to Codex.
Use the Codex provider's thread and reconstruction dictionaries as the current
viewer contract (including turns, ordered entries, summary and extracted-file
metadata). Keep raw-format handling in the provider and add representative
fixtures under `tests/`.

## Tests

From this folder:

```bash
python -m unittest discover -s tests -v
```

## Current GUI behavior

- Loading `state_5.sqlite` only lists conversations; no rollout is parsed automatically.
- A rollout is parsed only after the user selects a conversation; parsed results are cached for the current output folder.
- Each user prompt shows permission metadata from its rollout turn context. Missing turn permissions are labeled “Not recorded.” The SQLite thread summary is never substituted for a prompt's permissions.
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
