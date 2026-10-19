# NukeMCP — AI Behavior Rules

You are connected to a live Nuke compositing session via MCP. Follow these rules.

## Architecture

Three-layer system:
1. **Nuke Addon** — socket server running inside Nuke (port 54321)
2. **MCP Server** (`src/nukemcp/`) — FastMCP bridge, exposes tools via stdio
3. **AI Client** — you, reading this file

## Destructive Actions

**Never** perform destructive actions without explicit user confirmation:

- `delete_node` — always call first with `confirm=False` to show what would be deleted, then confirm with the user before calling with `confirm=True`
- `execute_python` — always show the code to the user first, then confirm before calling with `confirm=True`
- `load_script` — always warn that the current script will be replaced, then confirm

**The pattern:**
1. Call the tool with `confirm=False` (returns a description of what would happen)
2. Show the description to the user
3. Ask for confirmation
4. Only if confirmed, call again with `confirm=True`

## Before Making Changes

- Call `get_script_info` to understand the current state (`scene_digest` for a compact overview)
- Call `get_node_info` on relevant nodes before modifying them (`non_default_only=True` keeps it short)
- Never assume what nodes exist — always check first
- Read error messages carefully; they tell you what went wrong

## Reading vs Changing

- To read or compute anything, use `query_python`: every change it makes is rolled back,
  so it needs no confirmation. A single expression returns its value.
- To change the script, use the dedicated tools, `batch` (several steps, one undo) or
  `execute_python` (confirm first). Every change is one undo step labelled `MCP: ...`.
- A failed command is rolled back completely — retrying never leaves half-built graphs.
- Code that touches files or processes is blocked by the safety scan; pass
  `allow_unsafe=True` only after the user agreed to those exact lines.
- `undo_agent_session` (after `undo_history`) undoes only your own steps.

## Check Your Work Visually

- After building or changing a setup, look at the result with `render_node_preview`
  (pixels of any node at any frame through the viewer's display transform; raw for
  data passes) instead of assuming it worked.
- `capture_screen` shows the node graph, viewer or properties panel.

## Several Nuke Sessions

- `list_nuke_instances` / `select_nuke_instance`. Replies to changes include
  `session.script` — make sure it is the script the user means.

## Node Naming

Use descriptive, lowercase names with underscores:
- `fg_key` not `Keyer1`
- `bg_grade` not `Grade3`
- `hero_merge` not `Merge1`
- `plate_read` not `Read1`

## Node Organization

- Keep the graph flowing top-to-bottom
- Source nodes (Read) at the top, output nodes (Write) at the bottom
- Use `auto_layout` after creating multi-node setups
- Position related nodes near each other

## Colorspace

- Respect the project's working colorspace — check with `get_script_info`
- Never change colorspace settings without asking
- When creating Read nodes, mention the expected colorspace if relevant

## Memory

- On session start, read `nuke://memory/facility` and `nuke://memory/corrections` resources for context
- After any correction by the compositor, call `log_correction` to persist it for future sessions
- Periodically call `update_project_memory` to keep the project snapshot current
- If facility conventions exist, follow them (colorspace, naming, preferred tools)

## When Uncertain

- Ask the user rather than guessing
- If a tool returns an error, report it clearly — don't retry silently
- If you don't know what a specific Nuke knob does, say so
