# AgentSleuth — Modular Edition v0.2.2

AgentSleuth reconstructs conversations from two forensic sources in a Tkinter viewer.

- **Codex** uses `state_5.sqlite` to find conversations and reconstructs them from their JSONL rollouts. Recorded attachments and recoverable file changes are saved to the selected output folder.
- **OpenCode** uses `opencode.db` to reconstruct sessions from the SQLite `session`, `message`, and `part` tables. It shows prompts, responses, tool executions, file references, patches, and other recorded parts. The parser skips `step-start`, `reasoning`, and `step-finish` Parts.

## Run

Use Python 3.10 or newer with Tkinter installed. AgentSleuth uses the Python standard library.

```bash
python main.py
```

Choose the agent tab and load its database. Select a conversation in the sidebar to reconstruct it. Each tab has its own worker, loaded database, transcript cache, and view state.

## Project layout

```text
agentsleuth/
    core/            Shared text, formatting and filesystem helpers
    parsers/
        codex/       SQLite discovery, JSONL events, attachments and recovery
        opencode/    SQLite schema inspection, session discovery and timeline reconstruction
    ui/              Desktop layout, background controller and transcript viewer
tests/               Parser fixtures, reconstruction tests and GUI regressions
main.py              Python launcher
script.py            Alternate Python launcher
```

### Adding an evidence parser

Create a sibling package under `agentsleuth/parsers/`. Its public module should
expose `name`, `source_label`, `source_hint`, `filetypes`, `load_threads(path)` and
`reconstruct_from_thread(path, thread, output_root, progress)`. The desktop app
accepts providers via `App(parser=codex_provider, opencode_parser=opencode_provider)`.
The shared viewer uses conversation dictionaries with an ID, display name and
working directory, plus reconstruction dictionaries with turns, ordered events
and a summary. A provider can set `uses_output_directory = False` to hide the
extracted-files control.

## Tests

From this folder:

```bash
python -m unittest discover -s tests -v
```

## Current GUI behavior

- Loading a database lists its conversations. Reconstruction starts when a conversation is selected.
- Each user prompt shows permission metadata from its rollout turn context. Missing turn permissions are labeled “Not recorded.” The SQLite thread summary is never substituted for a prompt's permissions.
- Mouse-wheel scrolling works anywhere over the conversation pane, including message cards and nested text widgets.
- The transcript scrolls continuously. Long message bodies and execution outputs have a capped visible height and their own scrollbar. Wheel scrolling continues in the outer transcript when an inner block reaches its edge.
- Tool-call and tool-output records are parsed and correlated internally using `call_id`, turn boundaries, ordinal ranges and command matching, but are not rendered as separate cards. This avoids duplicate content and reduces UI rendering cost.
- The conversation summary displays the number of visible activities rather than hidden tool-call records.
- Matched `CommandExecution`, `FileChange`, MCP and other supported activity records are rendered as standalone activity cards; command and aggregated output remain visible in the execution card.
- An OpenCode tool call is displayed as one execution with the recorded input, output, error and status when available. Repeated snapshots with the same call ID within one message share a card and retain their original rows in the reconstruction result.
- A rendering failure in one record is isolated to that record and does not prevent later conversation entries from rendering.
- Attachment and recovered-file links point to AgentSleuth's extracted/rebuilt copies. Historical source paths from the rollout are not used as link targets.
- Clicking a file link reveals its location in the system file manager; the file itself is not launched.

## Evidence handling notes

- SQLite is opened with `mode=ro` and `PRAGMA query_only=ON`.
- The OpenCode parser uses only the selected SQLite database. It follows the message-to-part relationship and orders each level by recorded sequence when available, with timestamps and IDs for the fallback order. Reconstructed records retain the source IDs and raw values.
- Rollout JSONL and source attachments are read, not executed.
- Embedded attachments are decoded only from recognized Base64 fields/data URIs and are written under the selected results directory.
- FileChange recovery only writes content explicitly present in the log. It does not claim to reproduce bytes that were never recorded.
- Tool-call/activity links may be inferred from the rollout event sequence and command matching; they are not treated as direct parent-ID proof unless the log contains an explicit link.
