"""Core node graph tools — create, modify, delete, connect, position, layout, inspect,
and running Python inside Nuke."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nukemcp.tools._safety import scan

if TYPE_CHECKING:
    from nukemcp.server import NukeMCPServer


def _blocked(code: str, allow_unsafe: bool) -> dict | None:
    findings = [] if allow_unsafe else scan(code)
    if not findings:
        return None
    return {
        "action": "blocked",
        "findings": [f.as_dict() for f in findings],
        "message": (
            "The code does something the undo stack cannot take back (files, processes, "
            "closing/saving the script). Show these lines to the user; only if they agree, "
            "call again with allow_unsafe=True."
        ),
    }


def register(server: NukeMCPServer):
    mcp = server.mcp
    conn = server.connection

    @mcp.tool(annotations={"readOnlyHint": True})
    def get_script_info() -> dict:
        """Get information about the current Nuke script.

        Returns script name, modified flag, frame range, current frame, FPS, format,
        proxy, colour management (OCIO config, working space), views, selection and
        node count.
        """
        return conn.send_command("get_script_info")

    @mcp.tool(annotations={"readOnlyHint": True})
    def get_node_info(
        node_name: str,
        knobs: list[str] | None = None,
        non_default_only: bool = False,
        max_value_chars: int = 500,
    ) -> dict:
        """Get a node's class, position, inputs, outputs, error state and knob values.

        "Root" returns the project settings. Animated knobs are flagged and
        expressions are included. Huge values (table knobs such as a
        CameraTracker's tracks) are truncated to max_value_chars.

        Args:
            node_name: Node name (full name for nodes inside groups, e.g. "Group1.Blur1").
            knobs: Only return these knobs.
            non_default_only: Skip knobs still at their default value (much shorter).
            max_value_chars: Truncate each knob value to this many characters.
        """
        params: dict = {"node_name": node_name, "non_default_only": non_default_only,
                        "max_value_chars": max_value_chars}
        if knobs:
            params["knobs"] = knobs
        return conn.send_command("get_node_info", params)

    @mcp.tool()
    def create_node(
        node_class: str,
        name: str | None = None,
        knobs: dict | None = None,
        position: list[int] | None = None,
        inputs: list[str] | None = None,
        connect_to_selected: bool = False,
    ) -> dict:
        """Create a new node. Fails (and leaves nothing behind) if a knob is invalid.

        Unlike the Nodes menu, it does not wire itself to whatever the user has
        selected unless connect_to_selected=True.

        Args:
            node_class: The Nuke node class (e.g. "Grade", "Merge2", "Read").
            name: Optional node name.
            knobs: Knob values to set on creation.
            position: Optional [x, y] in the node graph (auto-placed otherwise).
            inputs: Node names to connect to inputs 0, 1, ... (None to skip an input).
            connect_to_selected: Behave like the Nodes menu (connect to the selection).
        """
        params: dict = {"node_class": node_class, "connect_to_selected": connect_to_selected}
        if name is not None:
            params["name"] = name
        if knobs is not None:
            params["knobs"] = knobs
        if position is not None:
            params["position"] = position
        if inputs is not None:
            params["inputs"] = inputs
        return conn.send_command("create_node", params)

    @mcp.tool(annotations={"idempotentHint": True})
    def modify_node(node_name: str, knobs: dict) -> dict:
        """Set knob values on an existing node (all-or-nothing).

        Args:
            node_name: The name of the node to modify.
            knobs: Dict of knob names to new values (lists for multi-value knobs).
        """
        return conn.send_command("modify_node", {"node_name": node_name, "knobs": knobs})

    @mcp.tool(annotations={"destructiveHint": True})
    def delete_node(node_name: str, confirm: bool = False) -> dict:
        """Delete a node from the Nuke script.

        This is a destructive action. You must set confirm=True after getting
        user confirmation.

        Args:
            node_name: The name of the node to delete.
            confirm: Must be True to proceed. If False, returns a description
                     of what would be deleted without deleting it.
        """
        if not confirm:
            return {
                "action": "delete_node",
                "node_name": node_name,
                "message": (
                    f"This will permanently delete node '{node_name}'. "
                    "Ask the user to confirm, then call again with confirm=True."
                ),
            }
        return conn.send_command("delete_node", {"node_name": node_name})

    @mcp.tool()
    def connect_nodes(
        output_node: str,
        input_node: str,
        input_index: int = 0,
    ) -> dict:
        """Connect the output of one node to an input of another.

        Args:
            output_node: The node whose output to connect.
            input_node: The node whose input receives it.
            input_index: Which input on input_node (default 0).
        """
        return conn.send_command("connect_nodes", {
            "output_node": output_node,
            "input_node": input_node,
            "input_index": input_index,
        })

    @mcp.tool(annotations={"idempotentHint": True})
    def position_node(node_name: str, x: int, y: int) -> dict:
        """Set the position of a node in the node graph.

        Args:
            node_name: The name of the node to position.
            x: X coordinate in the node graph.
            y: Y coordinate in the node graph.
        """
        return conn.send_command("position_node", {"node_name": node_name, "x": x, "y": y})

    @mcp.tool()
    def auto_layout(node_names: list[str] | None = None) -> dict:
        """Auto-arrange nodes in the node graph for a clean layout.

        Args:
            node_names: Optional list of node names to arrange. If None, arranges all nodes.
        """
        params = {}
        if node_names is not None:
            params["node_names"] = node_names
        return conn.send_command("auto_layout", params)

    @mcp.tool(annotations={"readOnlyHint": True})
    def query_python(code: str, allow_unsafe: bool = False,
                     timeout_seconds: float = 60.0) -> dict:
        """Run Python in Nuke to INSPECT the script — every change is rolled back.

        Use this instead of execute_python whenever you only need to read or
        compute something: it needs no confirmation because the undo
        transaction is always cancelled (nodes created or knobs changed while
        probing are restored). A single expression returns its value; otherwise
        assign to `result`. `nuke` and `nukescripts` are available; list
        comprehensions and functions work normally.

        Args:
            code: Python to run.
            allow_unsafe: Allow file/process operations flagged by the safety scan
                          (only after the user agrees; undo cannot revert those).
            timeout_seconds: How long to wait for Nuke.
        """
        blocked = _blocked(code, allow_unsafe)
        if blocked:
            return blocked
        return conn.send({"type": "query_python", "params": {"code": code}},
                         timeout=timeout_seconds)

    @mcp.tool(annotations={"destructiveHint": True})
    def execute_python(
        code: str,
        confirm: bool = False,
        timeout_seconds: float = 120.0,
        atomic: bool = True,
        persist: bool = False,
        reset_session: bool = False,
        allow_unsafe: bool = False,
    ) -> dict:
        """Execute Python in Nuke that CHANGES the script (use query_python to read).

        Runs as one undo step labelled "MCP: execute_python". With atomic=True
        (default) a snippet that raises half way is rolled back completely, so it
        never leaves a half-built graph. A single expression returns its value;
        otherwise assign to `result`. stdout/stderr are returned. Errors report
        the failing line of the snippet.

        Args:
            code: Python code. `nuke` and `nukescripts` are available.
            confirm: Must be True to proceed (show the code to the user first).
            timeout_seconds: Raise for bulk edits or anything that keeps Nuke busy.
            atomic: Roll everything back if the snippet raises.
            persist: Keep variables between calls (a REPL-like session namespace).
            reset_session: Clear the persistent namespace first.
            allow_unsafe: Allow operations the safety scan flags (deleting/moving
                          files, subprocesses, closing or saving the script).
                          Only after the user agreed to those specific lines.
        """
        if not confirm:
            return {
                "action": "execute_python",
                "code_preview": code[:400],
                "message": (
                    "This will execute Python that can modify the script. "
                    "Show the code to the user and ask them to confirm, "
                    "then call again with confirm=True. For read-only "
                    "inspection use query_python instead (no confirmation needed)."
                ),
            }
        blocked = _blocked(code, allow_unsafe)
        if blocked:
            return blocked
        # The full reply (status, result, stdout/stderr, failing line, rolled_back,
        # session) — `result` can be any JSON value, and errors keep their details.
        return conn.send({"type": "execute_python", "params": {
            "code": code, "atomic": atomic, "persist": persist, "reset": reset_session,
        }}, timeout=timeout_seconds)
