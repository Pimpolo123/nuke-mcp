"""Editing tools: animation, expressions, wiring, duplication, path replace and
the generic atomic batch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nukemcp.tools._safety import scan

if TYPE_CHECKING:
    from nukemcp.server import NukeMCPServer


def register(server: NukeMCPServer):
    mcp = server.mcp
    conn = server.connection

    @mcp.tool()
    def batch(operations: list[dict], label: str = "batch",
              timeout_seconds: float = 120.0, allow_unsafe: bool = False) -> dict:
        """Run several commands as ONE undo step, all-or-nothing.

        If any operation fails, everything the batch did is rolled back and the
        failing operation is reported. Use it for multi-node setups so the user
        can undo the whole thing with one Ctrl+Z.

        Args:
            operations: [{"type": "<addon command>", "params": {...}}, ...] using the
                        addon command names (create_node, modify_node, connect_nodes,
                        set_knob_expression, set_knob_keyframes, execute_python, ...).
            label: Shown in the undo history as "MCP: batch".
            timeout_seconds: Raise for large batches.
            allow_unsafe: Let execute_python operations do what the safety scan flags.
        """
        if not allow_unsafe:
            findings = []
            for i, op in enumerate(operations):
                if (op.get("type") or op.get("tool")) in ("execute_python", "query_python"):
                    code = (op.get("params") or {}).get("code", "")
                    findings += [{"operation": i, **f.as_dict()} for f in scan(code)]
            if findings:
                return {"action": "blocked", "findings": findings,
                        "message": "Python inside the batch does something undo cannot revert. "
                                   "Show it to the user; only if they agree, call again with "
                                   "allow_unsafe=True."}
        return conn.send_command("batch", {"operations": operations, "label": label},
                                 timeout=timeout_seconds)

    @mcp.tool()
    def set_knob_expression(node_name: str, knob_name: str, expression: str,
                            field_index: int | None = None) -> dict:
        """Set (or clear, with "") an expression on a knob.

        Args:
            node_name: Node.
            knob_name: Knob, e.g. "translate".
            expression: TCL expression, e.g. "Tracker1.translate.x" or "frame*2".
            field_index: Only this field of a multi-value knob (0=x, 1=y, ...).
        """
        params: dict = {"node_name": node_name, "knob_name": knob_name, "expression": expression}
        if field_index is not None:
            params["field_index"] = field_index
        return conn.send_command("set_knob_expression", params)

    @mcp.tool()
    def set_knob_keyframes(node_name: str, knob_name: str, keys: dict,
                           field_index: int | None = None, replace: bool = False) -> dict:
        """Set many keyframes in one call and verify the key count.

        Args:
            node_name: Node.
            knob_name: Knob.
            keys: {frame: value} for single values, {frame: [x, y, ...]} for
                  multi-value knobs. Frames may be strings.
            field_index: Field for single values on a multi-value knob.
            replace: Clear existing animation first.
        """
        params: dict = {"node_name": node_name, "knob_name": knob_name, "keys": keys,
                        "replace": replace}
        if field_index is not None:
            params["field_index"] = field_index
        return conn.send_command("set_knob_keyframes", params, timeout=60.0)

    @mcp.tool()
    def remove_knob_animation(node_name: str, knob_name: str,
                              field_index: int | None = None) -> dict:
        """Remove keys and expressions from a knob (keeps the current value).

        Args:
            node_name: Node.
            knob_name: Knob.
            field_index: Only this field.
        """
        params: dict = {"node_name": node_name, "knob_name": knob_name}
        if field_index is not None:
            params["field_index"] = field_index
        return conn.send_command("remove_knob_animation", params)

    @mcp.tool()
    def disconnect_input(node_name: str, input_index: int = 0) -> dict:
        """Disconnect one input of a node.

        Args:
            node_name: Node.
            input_index: Input to disconnect.
        """
        return conn.send_command("disconnect_input", {"node_name": node_name,
                                                      "input_index": input_index})

    @mcp.tool()
    def duplicate_node(node_name: str, x_offset: int = 100, y_offset: int = 0) -> dict:
        """Copy a node with all its knobs (does not touch the user's clipboard).

        Args:
            node_name: Node to copy.
            x_offset: Placement offset of the copy.
            y_offset: Placement offset of the copy.
        """
        return conn.send_command("duplicate_node", {"node_name": node_name,
                                                    "x_offset": x_offset, "y_offset": y_offset})

    @mcp.tool()
    def merge_script(path: str) -> dict:
        """Import all nodes of another .nk into the current script (one undo step).

        Args:
            path: Absolute path of the .nk to import.
        """
        return conn.send_command("merge_script", {"path": path}, timeout=60.0)

    @mcp.tool()
    def replace_filepaths(find: str, replace: str, regex: bool = False,
                          node_classes: list[str] | None = None,
                          dry_run: bool = True) -> dict:
        """Search/replace in file knobs (Read, Write, ReadGeo, Camera, ...).

        Dry run by default: shows every change first. Call again with
        dry_run=False after the user agrees; it is a single undo step.

        Args:
            find: Text (or regex) to find.
            replace: Replacement.
            regex: Treat find as a regular expression.
            node_classes: Limit to these classes.
            dry_run: Only report.
        """
        params: dict = {"find": find, "replace": replace, "regex": regex, "dry_run": dry_run}
        if node_classes:
            params["node_classes"] = node_classes
        return conn.send_command("replace_filepaths", params)
