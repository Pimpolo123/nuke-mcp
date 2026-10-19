"""Session tools: undo history, undo the agent's work, Nuke's console, the session
journal (and replay), capabilities, async render tasks and hot-reloading the addon."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nukemcp.server import NukeMCPServer

RO = {"readOnlyHint": True}


def register(server: NukeMCPServer):
    mcp = server.mcp
    conn = server.connection

    # -- undo -----------------------------------------------------------------

    @mcp.tool(annotations=RO)
    def undo_history(limit: int = 20) -> dict:
        """Top of Nuke's undo stack. Steps made by the agent are flagged agent=True
        (labels start with "MCP: ").

        Args:
            limit: How many steps to list.
        """
        return conn.send_command("undo_history", {"limit": limit})

    @mcp.tool(annotations={"destructiveHint": True})
    def undo_agent_session(max_steps: int = 200, confirm: bool = False) -> dict:
        """Undo the agent's own consecutive steps from the top of the undo stack.

        Stops at the first step the user made by hand, so their work is never
        touched. Everything can be brought back with Redo (Ctrl+Shift+Z) as long
        as nothing new is done in between.

        Args:
            max_steps: Safety cap.
            confirm: Must be True; call undo_history first and show the user what
                     will be undone.
        """
        if not confirm:
            return {"action": "undo_agent_session",
                    "message": "Call undo_history, show the user the agent steps that will "
                               "be undone, then call again with confirm=True."}
        return conn.send_command("undo_agent_session", {"max_steps": max_steps})

    # -- console & journal ----------------------------------------------------

    @mcp.tool(annotations=RO)
    def get_console_log(last_n: int = 200, stream: str | None = None,
                        contains: str | None = None, since_seq: int | None = None) -> dict:
        """Read what Nuke's Python printed (stdout/stderr), including errors from
        callbacks and gizmos, without asking the user to copy the Script Editor.

        Args:
            last_n: Last N lines.
            stream: "stdout" or "stderr".
            contains: Case-insensitive filter.
            since_seq: Only lines after this sequence number (from a previous call).
        """
        params: dict = {"last_n": last_n}
        if stream:
            params["stream"] = stream
        if contains:
            params["contains"] = contains
        if since_seq is not None:
            params["since_seq"] = since_seq
        return conn.send_command("get_console_log", params)

    @mcp.tool()
    def clear_console_log() -> dict:
        """Clear the console buffer kept by the addon (not the Script Editor)."""
        return conn.send_command("clear_console_log")

    @mcp.tool(annotations=RO)
    def get_session_journal(last_n: int = 50, path: str | None = None) -> dict:
        """What the agent changed in this Nuke session: one entry per command that
        modified the script (command, params, status, time).

        Args:
            last_n: Last N entries.
            path: Another journal file (see list_session_journals).
        """
        params: dict = {"last_n": last_n}
        if path:
            params["path"] = path
        return conn.send_command("get_session_journal", params)

    @mcp.tool(annotations=RO)
    def list_session_journals() -> dict:
        """Journal files of recent sessions, newest first."""
        return conn.send_command("list_session_journals")

    @mcp.tool(annotations={"destructiveHint": True})
    def replay_journal(path: str | None = None, skip_commands: list[str] | None = None,
                       dry_run: bool = True) -> dict:
        """Re-run the successful changes recorded in a journal on the current script
        (e.g. repeat a setup on the next shot). Dry run lists the steps first;
        the real run is one atomic undo step.

        Args:
            path: Journal file (default: this session's).
            skip_commands: Command names to leave out.
            dry_run: Only list what would run.
        """
        params: dict = {"dry_run": dry_run}
        if path:
            params["path"] = path
        if skip_commands:
            params["skip_commands"] = skip_commands
        return conn.send_command("replay_journal", params, timeout=300.0)

    # -- capabilities & addon ---------------------------------------------------

    @mcp.tool(annotations=RO)
    def get_capabilities() -> dict:
        """Nuke version/variant, Python and PySide, colour management and OCIO config,
        ML nodes (CopyCat/BigCat/Inference) and other notable nodes available, and
        every addon command."""
        return conn.send_command("get_capabilities", timeout=30.0)

    @mcp.tool()
    def addon_reload() -> dict:
        """Hot-reload the addon inside Nuke after its files were updated (no restart,
        same port). The connection drops for a moment and reconnects by itself."""
        result = conn.send_command("addon_reload")
        conn.disconnect()
        return result

    # -- async renders ------------------------------------------------------------

    @mcp.tool(annotations={"destructiveHint": True})
    def render_start(write_node: str | None = None, write_nodes: list[str] | None = None,
                     first_frame: int | None = None, last_frame: int | None = None,
                     step: int = 1, continue_on_error: bool = False,
                     confirm: bool = False) -> dict:
        """Start rendering Write node(s) in the background and return a task id.

        Frames render one by one on Nuke's main thread; Nuke stays responsive,
        and the job can be polled with task_status and stopped with task_cancel.
        The user's render callbacks run as in a normal render.

        Args:
            write_node: Write to render (or write_nodes for several).
            write_nodes: Several Writes rendered frame by frame together.
            first_frame: Default: script range.
            last_frame: Default: script range.
            step: Frame step.
            continue_on_error: Keep going when a frame fails.
            confirm: Must be True (renders write files to disk).
        """
        if not confirm:
            return {"action": "render_start",
                    "message": "Rendering writes files to disk. Confirm with the user, then "
                               "call again with confirm=True."}
        params: dict = {"step": step, "continue_on_error": continue_on_error}
        if write_nodes:
            params["write_nodes"] = write_nodes
        elif write_node:
            params["write_node"] = write_node
        else:
            raise ValueError("Give write_node or write_nodes")
        if first_frame is not None:
            params["first_frame"] = first_frame
        if last_frame is not None:
            params["last_frame"] = last_frame
        return conn.send_command("render_start", params)

    @mcp.tool(annotations=RO)
    def task_status(task_id: str) -> dict:
        """Progress of a background task: state, frames done/total, current frame,
        failed frames, elapsed and ETA.

        Args:
            task_id: From render_start.
        """
        return conn.send_command("task_status", {"task_id": task_id})

    @mcp.tool()
    def task_cancel(task_id: str) -> dict:
        """Stop a background task after the frame in progress.

        Args:
            task_id: From render_start.
        """
        return conn.send_command("task_cancel", {"task_id": task_id})

    @mcp.tool(annotations=RO)
    def list_tasks() -> dict:
        """All background tasks of this Nuke session, newest first."""
        return conn.send_command("list_tasks")

    # -- colour -------------------------------------------------------------------

    @mcp.tool(annotations=RO)
    def audit_color() -> dict:
        """Audit the script's colour pipeline (ACES/OCIO) and report mistakes that
        silently corrupt pixels: data passes (depth/normals/position/vectors/IDs)
        read through a colour transform, 8-bit display-referred files read as
        linear, EXRs read with display curves, Writes whose colorspace does not
        fit the file type. Report only; changes nothing."""
        return conn.send_command("audit_color", timeout=60.0)
