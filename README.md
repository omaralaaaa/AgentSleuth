# AgentSleuth

AgentSleuth is a local desktop viewer for investigating conversations recorded by coding agents. Open an evidence source, select a session, and follow each user prompt through the agent's replies, tool calls, recorded output, and file changes. A separate tab handles each agent's storage format.

## Run the viewer

Install Python 3.10 or newer. AgentSleuth uses Qt through PySide6 Essentials.

```shell
git clone https://github.com/omaralaaaa/AgentSleuth.git
cd AgentSleuth
python -m pip install .
python main.py
```

Cloning requires access to the repository. Once installed, you can also launch it with the `agentsleuth` command. Run `python main.py --demo` to try a synthetic 1,000-entry transcript.

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

Each result represents one agent folder. Use the row checkboxes or the **Select all** button to choose folders, then click **Open selected**. Double-click a folder name to open it individually. Each source loads its own conversation list. Multiple sources for the same agent open in separate tabs. The scanner resolves the index automatically, choosing the highest numbered Codex state database when several are present. Antigravity folders without an index can list sessions from generated transcripts and trajectory databases. Scroll horizontally to inspect long paths.

### Open a source manually

1. Select an agent tab and click **Browse** to pick and load its source file. If you type or paste a path, press **Enter** to load it.
2. The default export directory is `AgentSleuth_Export/` beside the application script. **Change folder** selects a shared directory for all agent tabs and saves the choice for future launches.
3. Select a conversation in the sidebar. The sidebar filter searches conversation names, working directories, and IDs. Each tab loads and caches its own sessions.
4. Press **Ctrl+F** to search the selected transcript. Terms are case-insensitive and can appear in any order. The filter lists values present in the selected conversation or turn, including exact tool names, activity types, and recorded statuses. For example, a recorded Bash call can match **Commands**, **Tool calls**, or **Tool: bash**. Filtering by a tool name also includes failed attempts. Tree view keeps a matching reply's parent prompt for context.
5. Responses and tool calls are grouped under each prompt in Tree view. Click the response count to collapse or expand that prompt's replies. Long text blocks scroll independently. Click an extracted filename to reveal its copy in the file manager.

## Interpret the results

AgentSleuth creates export folders when it saves an artifact. Files go under the agent and conversation title, in `attachments/` or `recovered_files/` according to the artifact type. When a title folder is already taken, AgentSleuth adds a short session ID suffix.

When a selected conversation has exported files, **Open export folder** opens its session directory. **Uploads by prompt** lists the recorded uploads beneath their prompts and shows the corresponding exported filenames. Select a prompt or file to read the full prompt text.

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

Generated JSONL takes precedence over SQLite step metadata. Keep each session's `.user_uploaded/` folder alongside `.system_generated/` to export uploads linked to user prompts. Requests and result steps remain separate when the transcript provides no matching call ID. Standalone legacy `.pb` conversations are unsupported.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| A session is listed but its transcript is missing | Check the companion paths in the source table. An index can survive after its detailed records have been moved or removed. |
| A file is visible but has no clickable copy | Inspect its status. Reference-only records contain no embedded bytes; invalid or oversized payloads may fail extraction. |
| A newly recorded event is missing | Refresh your evidence snapshot, then reload the source to clear that tab's session cache. |
| The viewer starts but a search looks empty | Use **Clear** to reset the query and type filter, then select **Entire conversation** to search all turns. |

## Development

The [provider packages](agentsleuth/parsers/) handle evidence discovery and reconstruction. [Shared core code](agentsleuth/core/) handles search, paths and artifact storage. The [Qt viewer](agentsleuth/ui/qt_app.py) runs reconstruction on per-tab background workers and mounts transcript cards near the visible area.

To add a provider, implement `load_threads(path)` and `reconstruct_from_thread(path, thread, output_root, progress)`. Return a thread ID, display name and working directory for discovery, and ordered turns, entries and a summary for rendering. Register the provider in the Qt viewer. Run `python main.py --benchmark 1000` to time transcript rendering.
