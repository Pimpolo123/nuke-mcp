# Changelog

## 0.2.0 — 2026-10-19 (darvosis fork)

### Addon (runs inside Nuke)
- Rewritten as the `nuke_mcp_addon` package (same import name; old `menu.py` snippets keep working).
- `execute_python`: one namespace (comprehensions/closures no longer raise `NameError`),
  single expressions return their value, stdout/stderr captured, failing snippet line
  reported, optional persistent namespace.
- Every mutating command is one labelled undo step (`MCP: ...`), cancelled on failure.
  Terminal sessions (no undo stack) remove the nodes they created instead.
- New: `query_python` (always rolled back), atomic `batch`, node graph with outputs,
  scene digest/delta, metadata, channels, node classes + availability probe, default
  knobs, missing frames, glob, expressions/keyframes, path replace, viewer control,
  `capture_screen` (PrintWindow on Windows), `render_node_preview` (viewer OCIO
  display/view), async renders, undo history + agent-only undo, console ring buffer,
  JSONL session journal + replay, capabilities, colour audit, CameraTracker user-track
  list/import/export-to-Axis/reprojection QC, `addon_reload` (hot reload).
- Exclusive port binding (no two sessions on one port on Windows), on-disk instance
  registry with heartbeat, `NUKE_MCP_PORT` exported for child processes.
- The dispatcher never raises (Nuke's `executeInMainThreadWithResult` swallows
  exceptions); large replies (images) are not truncated.
- Previews suspend the user's callbacks and disable undo for their temporary nodes.
- `get_node_info` handles Root (upstream PR #3), filters knobs, skips defaults,
  truncates huge values. `create_node` no longer wires itself to the selection.
- Undo-agent walk also takes back Nuke 17's deferred `change <Write>.out_colorspace`
  step for Writes the agent created.

### MCP server
- 45+ new tools exposing the above; images returned as MCP image content.
- AST safety scan before `execute_python`, `query_python` and `batch`.
- Instance listing from the registry (works while a session renders) and handshake
  validation (other tools on the port range are no longer mistaken for Nuke).
- Richer instructions for the model (read vs change, seeing, Nuke pitfalls).
- Code tools return the full reply, so non-dict results and error details survive.
- Fixes: posix paths from `list_files`, discovery without HOME, headless launcher
  finds the addon package.

### Earlier fork commits
- `executeInMainThreadWithResult` for GUI dispatch (upstream PRs #1/#4).
- Lazy reconnect after a dropped socket; `timeout_seconds` on `execute_python`.
- Several Nuke sessions at once (PABLOHERTA).

### Testing
- Addon suite in terminal NukeX 15.1v6, 17.0v4, 17.1v2: 34/34 each.
- Live GUI suites in NukeX 17.1v2 on Windows 11.
- 197 server tests, coverage 75%.
