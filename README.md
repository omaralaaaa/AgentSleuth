# AgentSleuth

AgentSleuth is a local desktop viewer for investigating conversations recorded by coding agents. Open an evidence source, select a session, and follow each user prompt through the agent's replies, tool calls, recorded output, and file changes. A separate tab handles each agent's storage format.

## Run the viewer

Install Python 3.10 or newer with Tkinter. AgentSleuth uses the Python standard library. From a terminal:

```shell
git clone https://github.com/omaralaaaa/AgentSleuth.git
cd AgentSleuth
python main.py
```

Cloning requires access to the repository. If you already have a checkout, run the last command from its root. To check whether your Python installation includes Tk, run `python -m tkinter`; a small test window should open.

## Choose the evidence source

| Tab | File to open | What to keep alongside it |
| --- | --- | --- |
| Codex | `state_5.sqlite` | The session rollout JSONL files referenced by the database. Preserve their `sessions/` directory structure when copying evidence. |
| OpenCode | `opencode.db` | Sessions, messages, file parts and tool state are in SQLite. Embedded uploads can be recovered from the database itself. |
| Claude Code | `history.jsonl` | The sibling `projects/` tree contains session transcripts. Keep `file-history/` if you need available file snapshots. |
| Antigravity | `conversation_summaries.db` | Keep the sibling `brain/` and `conversations/` trees. You can also open a generated `transcript.jsonl` or an individual trajectory `.db` directly. |

For SQLite evidence, use a consistent snapshot. Recent records may still be in a database's `-wal` file. Copying only the main database from a running application can produce an incomplete timeline.

## Investigate a conversation

### Discover evidence automatically

Click **Scan for artifacts…** above the agent tabs. **Scan this PC** checks known agent directories in accessible Windows user profiles. **Scan evidence folder…** searches beneath a directory you select, such as the top of a KAPE collection or its extracted C-drive folder. You can select the collection even when the user profiles are nested several levels down. Raw disk-image files must first be mounted or extracted.

Each result represents one agent folder. Double-click a row or click **Open folder** to load its conversation list in the corresponding tab. The scanner resolves the index automatically, choosing the highest numbered Codex state database when several are present. Antigravity folders without an index can list sessions from generated transcripts and trajectory databases. Different users' folders remain separate. Scroll horizontally to inspect long paths.

### Open a source manually

1. Select an agent tab and browse to its source file. Use **Load conversations** after entering a path manually.
2. For providers that extract files, choose the results folder before opening the session. The default is `AgentSleuth_Results/` under the checkout.
3. Select a conversation in the sidebar. The sidebar filter searches conversation names, working directories, and IDs. Each tab loads and caches its own sessions.
4. Press **Ctrl+F** to search the selected transcript. Terms are case-insensitive and can appear in any order. The filter lists values present in the selected conversation or turn, including exact tool names, activity types, and recorded statuses. For example, a recorded Bash call can match **Commands**, **Tool calls**, or **Tool: bash**. Filtering by a tool name also includes failed attempts. Tree view keeps a matching reply's parent prompt for context.
5. Choose **Tree** to group responses and tool calls under each prompt, or **Conversation** to read matching entries in timeline order. Switching views keeps the selected turn, search, and filters. Returning to Tree restores folded prompts. Long text blocks scroll independently. Click an extracted filename to reveal its copy in the file manager.

## Interpret the results

### Codex

AgentSleuth reads the SQLite thread list and reconstructs selected messages and activities from rollout records. Each user prompt displays the permission settings recorded in its turn context, or **Not recorded** when those settings are missing. Execution cards show recorded commands and output; PowerShell commands use syntax highlighting.

Tool-call IDs, turn boundaries, ordinal ranges and command matches help correlate activity. A correlation note identifies inferred relationships. File-change recovery and attachment extraction use bytes or content present in the rollout.

### OpenCode

The parser links parts to their source messages, orders records by recorded sequence when available, and uses timestamps and IDs for fallback ordering. Repeated snapshots of a tool call within one message contribute to one execution card. Step boundaries and reasoning parts are omitted from the displayed timeline.

Embedded file-part uploads produce copies under `OpenCode/<session-hash>/attachments/` in the results folder. The file card shows MIME type, byte count and SHA-256. A path or remote URL without embedded bytes remains a reference. A decoding error stays associated with its file.

### Claude Code

The history index provides session discovery. The parser resolves the matching project transcript, preserves line order, and correlates tool uses and results within their branch. Sidechain records are tracked separately. Extracted evidence goes under `Claude/<session-id>/` in the results folder. Proposed writes and recovered backup copies are labeled according to the available evidence.

### Antigravity

On the inspected Windows installation, the index is under `%USERPROFILE%\.gemini\antigravity\`. AgentSleuth resolves companion files relative to the **selected** evidence tree, so copied evidence can be investigated on another machine.

| Available session evidence | What the viewer can recover |
| --- | --- |
| `brain/<session-id>/.system_generated/logs/transcript.jsonl` | User prompts, planner replies, tool requests, recorded step output and errors. Each step retains its source index when available. Truncation markers identify incomplete source fields. |
| `conversations/<session-id>.db` with a `steps` table | Ordered step indexes and recorded numeric type/status values. Binary step payloads are not decoded. |
| Summary index only | Session title and recorded workspace. Selecting the session explains why transcript content is unavailable. |

Generated JSONL takes precedence over SQLite step metadata. Requests and result steps remain separate when the transcript provides no matching call ID. Standalone legacy `.pb` conversations are unsupported.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| A session is listed but its transcript is missing | Check the companion paths in the source table. An index can survive after its detailed records have been moved or removed. |
| A file is visible but has no clickable copy | Inspect its status. Reference-only records contain no embedded bytes; invalid or oversized payloads may fail extraction. |
| A newly recorded event is missing | Refresh your evidence snapshot, then reload the source to clear that tab's session cache. |
| The viewer starts but a search looks empty | Use **Clear** to reset the query and type filter, then select **Entire conversation** to search all turns. |

## Development

Run the regression suite from the repository root. GUI tests need a Python installation with Tk and a usable display.

```shell
python -m unittest discover -s tests -v
```

The [provider packages](agentsleuth/parsers/) handle evidence discovery and reconstruction. [Shared core code](agentsleuth/core/) handles search, paths and artifact storage. The [Tkinter viewer](agentsleuth/ui/) runs reconstruction on per-tab background workers.

To add a provider, implement `load_threads(path)` and `reconstruct_from_thread(path, thread, output_root, progress)`. Return a thread ID, display name and working directory for discovery, and ordered turns, entries and a summary for rendering. Register the provider in [the desktop app](agentsleuth/ui/app.py) and add fixtures and regression tests under [tests/](tests/).
