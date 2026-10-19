<p align="center">
  <img src="docs/logos/banner_light.svg" alt="NukeMCP — Talk to Nuke." width="700"/>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/darvosis/nuke-mcp?color=blue" alt="License: MIT"/></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+"/></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-compatible-green" alt="MCP Compatible"/></a>
  <img src="https://img.shields.io/badge/Nuke-15.1%20%7C%2017.0%20%7C%2017.1-E8A317" alt="Nuke 15.1 | 17.0 | 17.1"/>
  <a href="https://github.com/darvosis/nuke-mcp/commits/main"><img src="https://img.shields.io/github/last-commit/darvosis/nuke-mcp" alt="Last Commit"/></a>
</p>

NukeMCP connects AI assistants (Claude Code, Claude Desktop, any MCP client) to a
running Nuke session through the [Model Context Protocol](https://modelcontextprotocol.io).
The assistant can read your comp, look at it, and build or change nodes, and every
change is a normal undo step you can take back.

> **Fork of [kleer001/nuke-mcp](https://github.com/kleer001/nuke-mcp)**, including
> [PABLOHERTA](https://github.com/PABLOHERTA/nuke-mcp)'s multi-session support.
> Version 0.2 rebuilds the Nuke addon and adds what we found missing in production
> use, plus the best ideas from the other Nuke MCP servers (credited below).

## What's new in 0.2

**It can't leave your script half-broken.**
- Every change runs as **one labelled undo step** (`MCP: create_node`, `MCP: batch`, ...).
- A command that fails half way is **rolled back completely**. No orphan nodes after an error.
- `query_python` lets the assistant inspect the script freely: every change it makes
  while probing is **always rolled back**, so it needs no confirmation.
- `undo_agent_session` takes back **only the assistant's steps** and stops at the
  first thing you did by hand.
- An AST **safety scan** stops code that deletes or moves files, spawns processes or
  closes/saves the script, unless you allow it explicitly.

**It can see.**
- `render_node_preview`: the pixels of **any node at any frame**, rendered through
  your viewer's OCIO display/view (or raw, for data passes). It is returned as an
  image the model can look at, and leaves no trace in the script or undo stack.
- `capture_screen`: the node graph, viewer, properties or the whole window. On Windows it uses
  `PrintWindow`, so it captures the GL viewer correctly and **never includes other
  applications** sitting on top of Nuke.

**It's reliable to drive.**
- `execute_python` runs in a single namespace (list comprehensions and functions work —
  in the original they failed with `NameError`), returns expression values, stdout/stderr and the failing line.
- Several Nuke sessions at once. Each one takes its own port, and an on-disk registry
  lists sessions even while they render. A Nuke-launched assistant targets its own
  session automatically through `NUKE_MCP_PORT`.
- The MCP server starts before Nuke and reconnects by itself. The addon hot-reloads
  (`addon_reload`) without restarting Nuke.
- Long renders run as background tasks with status, ETA and cancel.

**It knows compositing.**
- `audit_color`: finds data passes (depth/normals/position/vectors/IDs) read through a
  colour transform, 8-bit display-referred images read as linear, and mismatched
  Write colorspaces in ACES/OCIO scripts.
- CameraTracker user tracks: import 2D tracks from other trackers without the modal
  dialog (handling four silent traps), **export every user track as its own Axis**
  (Nuke's own menu makes one Axis at the average), and reprojection QC in pixels.
- `scene_digest` / `scene_delta`: a compact overview plus "what changed since".

### Compared with other Nuke MCP servers (October 2026)

| | this fork | [kleer001](https://github.com/kleer001/nuke-mcp) | [dgirondi/NukeMCP](https://github.com/dgirondi/NukeMCP) | [mcp-socket-nuke](https://github.com/abyrvalg379/mcp-socket-nuke) |
|---|:-:|:-:|:-:|:-:|
| Python runs in one namespace | ✅ | ❌ | ✅ | ✅ |
| Failed commands roll back | ✅ | ❌ | ❌ (batch is one undo step) | ❌ |
| Read-only inspection without confirmation | ✅ | ❌ | ❌ | ❌ |
| Undo only the agent's steps | ✅ | ❌ | ❌ | ✅ |
| Several Nuke sessions | ✅ registry + ports | ❌ | env var | ✅ |
| See node pixels (viewer transform) | ✅ | ❌ | ✅ (no OCIO view) | ❌ |
| Capture UI without other apps on top | ✅ (Windows) | ❌ | ❌ | ❌ |
| Async renders | ✅ status + cancel | ❌ | status | ❌ |
| Safety scan on code | ✅ AST | ❌ | patterns | ❌ |
| Console log / session journal | ✅ / ✅ + replay | ❌ | ❌ | ✅ / ✅ + replay |
| Colour pipeline audit | ✅ | ❌ | ❌ | ❌ |
| CameraTracker user tracks | ✅ | ❌ | ❌ | ❌ |
| Domain macros (keying, deep, CopyCat...) | ✅ (from kleer001) | ✅ | templates | ❌ |
| Tools | 106 | 57 | 33 | 11 |

## Tested on

| Nuke | How | Result |
|---|---|---|
| NukeX 17.1v2 | live GUI session (Windows 11) | all suites pass |
| NukeX 17.1v2, 17.0v4, 15.1v6 | addon command suite in `nuke --nukex -t` | 34/34 each |
| — | MCP server unit + integration tests (mock Nuke) | 197 pass |

macOS and Linux are expected to work (pure Python + PySide) but are untested; there
`capture_screen` falls back to a screen grab, which shows whatever is on top of Nuke.

## Install

Prerequisites: git, Python 3.10+, [uv](https://docs.astral.sh/uv/). Nuke 15.1 or newer.

```bash
git clone https://github.com/darvosis/nuke-mcp.git
cd nuke-mcp
uv sync
```

**Nuke addon.** Copy the folder `nuke_addon/nuke_mcp_addon` into `~/.nuke/` (or add
`nuke_addon/` to `NUKE_PATH`), then start it from `menu.py`:

```python
# ~/.nuke/menu.py
try:
    import nuke_mcp_addon
    nuke_mcp_addon.start(show_panel=False)      # every GUI session, silently
    nuke.menu("Nodes").addMenu("NukeMCP").addCommand(
        "Show Panel", "import nuke_mcp_addon; nuke_mcp_addon.start()")
except Exception as e:
    print("NukeMCP: could not start: %s" % e)
```

Upgrading from the single-file addon: delete `~/.nuke/nuke_mcp_addon.py` (the package
replaces it; old `menu.py` snippets keep working). In an open Nuke, run
`nuke_mcp_addon.reload()` or call the `addon_reload` tool after copying the new files.

**MCP client.** Claude Code picks up the included `.mcp.json` when run from the repo.
Elsewhere (Claude Desktop, other clients):

```json
{
  "mcpServers": {
    "nuke-mcp": {
      "command": "uv",
      "args": ["--directory", "/path/to/nuke-mcp", "run", "nuke-mcp"]
    }
  }
}
```

Try it without Nuke: `uv run nuke-mcp --mock`.

## Safety model

- Destructive tools (`delete_node`, `execute_python`, `load_script`, `save_script`,
  `render_start`, `undo_agent_session`) return a preview first and need `confirm=True`.
- `execute_python`, `query_python` and `batch` are scanned before they reach Nuke;
  file deletion/moves/writes, subprocesses and closing/saving the script need
  `allow_unsafe=True` on top.
- Every change is one undo step with the `MCP:` prefix; failures roll back.
- Previews create temporary nodes with undo disabled and your callbacks suspended
  (no Write-preset or publish hooks fire), then delete them.
- The addon listens on `127.0.0.1` only.

## Multiple Nuke sessions

Each addon takes the first free port in 54321–54330 (exclusively, so two sessions can
never share a port on Windows) and announces itself in `%TEMP%/nuke_mcp/instances`.

- `list_nuke_instances` — sessions with version, PID and open script (busy ones too).
- `select_nuke_instance` — switch by `port` or by part of the script path.
- Replies to changes carry `session.script`, so it's always clear which script was edited.
- The addon exports `NUKE_MCP_PORT`; an MCP server started from inside a Nuke session
  (e.g. by an assistant panel) connects to that session.

## Tools

<details>
<summary>All 106 tools</summary>

**Inspect (read-only):** `get_script_info`, `get_node_info` (knob filter, non-default only,
truncation, Root), `get_node_graph`, `scene_digest`, `scene_delta`, `get_selection`,
`get_node_metadata`, `list_channels`, `list_node_classes`, `node_classes_available`,
`get_node_default_knobs`, `find_nodes_by_type`, `find_error_nodes`, `find_broken_reads`,
`find_missing_frames`, `glob_files`, `query_python`, `audit_color`, `get_capabilities`.

**See:** `render_node_preview`, `capture_screen`, `get_viewer_info`.

**Edit:** `create_node`, `modify_node`, `delete_node`, `connect_nodes`, `disconnect_input`,
`position_node`, `auto_layout`, `duplicate_node`, `select_nodes`, `set_knob_expression`,
`set_knob_keyframes`, `remove_knob_animation`, `batch`, `execute_python`, `merge_script`,
`replace_filepaths`, `batch_set_knob`, `batch_reconnect`.

**Viewer & timeline:** `set_viewer_input`, `set_current_frame`, `zoom_to_node`, `viewer_playback`.

**Session:** `undo_history`, `undo_agent_session`, `get_console_log`, `clear_console_log`,
`get_session_journal`, `list_session_journals`, `replay_journal`, `addon_reload`,
`list_nuke_instances`, `select_nuke_instance`.

**Script & render:** `load_script`, `save_script`, `set_project_settings`, `set_frame_range`,
`set_proxy_mode`, `render_frames`, `render_start`, `task_status`, `task_cancel`, `list_tasks`.

**Tracking (NukeX):** `create_tracker`, `solve_tracker`, `setup_stabilize`,
`create_camera_tracker`, `cameratracker_list_user_tracks`, `cameratracker_import_user_tracks`,
`cameratracker_user_tracks_to_axes`, `cameratracker_reprojection_qc`.

**Comp macros, 3D, deep, ML, splats, templates, annotations, memory, docs search and
events** come from the original project: `setup_keyer`, `setup_despill`, `setup_basic_comp`,
`setup_grade_chain`, `setup_light_wrap`, `setup_edge_blur`, `setup_write_node`,
`create_3d_scene`, `setup_camera`, `setup_scanline_render`, `setup_projection`,
`setup_deep_pipeline`, `setup_deep_merge`, `convert_to_deep`, `setup_copycat`,
`train_copycat`, `setup_bigcat`, `import_splat`, `setup_splat_render`, `list_toolsets`,
`load_toolset`, `save_toolset`, `create_live_group`, `create_annotation`,
`list_annotations`, `read_memory`, `write_memory`, `list_memory`, `log_correction`,
`update_project_memory`, `search_nuke_docs`, `subscribe_events`, `get_events`,
`clear_events`.

</details>

## Headless mode

```bash
uv run nuke-mcp --discover            # find Nuke installations and licensing
uv run nuke-mcp --headless            # launch Nuke in terminal mode and connect
```

Terminal Nuke keeps no undo stack: there a failed command removes the nodes it created
(reported as `"rolled_back": "created_nodes_only"`), but knob edits cannot be reverted.

## Docs

- [Changelog](CHANGELOG.md)
- [Technical reference](docs/TECHNICAL.md) — architecture, events, memory, plugins, version gating
- [Best practices](docs/BEST_PRACTICES.md) — compositor-focused recipes
- [Contributing](CONTRIBUTING.md)

## Credits

- **[kleer001/nuke-mcp](https://github.com/kleer001/nuke-mcp)** — the project this fork
  builds on: server architecture, domain tools, memory, docs search, events.
- **[PABLOHERTA/nuke-mcp](https://github.com/PABLOHERTA/nuke-mcp)** — several Nuke
  sessions at once, lazy connection (cherry-picked with authorship).
- Ideas (re-implemented, not copied) from **[dgirondi/NukeMCP](https://github.com/dgirondi/NukeMCP)**
  (atomic batch, node screenshots, async render status),
  **[mcp-socket-nuke](https://github.com/abyrvalg379/mcp-socket-nuke)** (undo-label
  walking, console ring buffer, session journal, instance registry and its Nuke 17.1
  notes), **[cian-bit/joshw051 nuke-mcp](https://github.com/joshw051/nuke-mcp)**
  (AST safety scan, scene digest/delta, async tasks),
  **[cedarconnor/nuke_mcp](https://github.com/cedarconnor/nuke_mcp)** (capabilities, operation
  status) and **[phantomvfx/NukeMCP](https://github.com/phantomvfx/NukeMCP)** (missing frames,
  path replacement).
- Upstream acknowledgments: [dughogan/nuke_mcp](https://github.com/dughogan/nuke_mcp),
  [flowagent-sh/nuke-mcp](https://github.com/flowagent-sh/nuke-mcp),
  [kleer001/houdini-mcp](https://github.com/kleer001/houdini-mcp).

## License

MIT (original copyright retained).

---

<sub>NukeMCP is not affiliated with or endorsed by Foundry. Nuke is a trademark of Foundry.</sub>
