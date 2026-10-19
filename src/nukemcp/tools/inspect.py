"""Read-only inspection tools: graph, selection, metadata, channels, classes,
scene digest/delta, missing frames, file listing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nukemcp.server import NukeMCPServer

RO = {"readOnlyHint": True}


def register(server: NukeMCPServer):
    mcp = server.mcp
    conn = server.connection

    @mcp.tool(annotations=RO)
    def get_node_graph(filter_class: str | None = None, recurse_groups: bool = False,
                       max_nodes: int = 500) -> dict:
        """The whole node graph: every node with class, position, inputs AND outputs,
        label, selected/disabled/error flags, plus the active viewer.

        Args:
            filter_class: Only nodes of this class.
            recurse_groups: Include nodes inside Groups (full names like "Group1.Blur1").
            max_nodes: Cap for very large scripts.
        """
        params = {"recurse_groups": recurse_groups, "max_nodes": max_nodes}
        if filter_class:
            params["filter_class"] = filter_class
        return conn.send_command("get_node_graph", params)

    @mcp.tool(annotations=RO)
    def scene_digest() -> dict:
        """Compact overview of the script: counts by class, sources (Read/Camera...
        with file and colorspace), Writes, nodes in error, selection. Returns a
        token for scene_delta. Prefer this over dumping every node."""
        return conn.send_command("scene_digest")

    @mcp.tool(annotations=RO)
    def scene_delta(token: str) -> dict:
        """What changed since a scene_digest/scene_delta token: added, removed and
        edited nodes (knob values or connections). Returns a new token.

        Args:
            token: Token from a previous scene_digest or scene_delta.
        """
        return conn.send_command("scene_delta", {"token": token})

    @mcp.tool(annotations=RO)
    def get_selection() -> dict:
        """Nodes currently selected by the user."""
        return conn.send_command("get_selection")

    @mcp.tool()
    def select_nodes(node_names: list[str], additive: bool = False) -> dict:
        """Select nodes in the node graph (clears the selection first unless additive).

        Args:
            node_names: Nodes to select.
            additive: Keep the current selection.
        """
        return conn.send_command("select_nodes", {"node_names": node_names, "additive": additive})

    @mcp.tool(annotations=RO)
    def get_node_metadata(node_name: str, frame: int | None = None,
                          keys: list[str] | None = None) -> dict:
        """Image metadata flowing through a node (EXR headers, camera data, timecode,
        colorspace tags...).

        Args:
            node_name: Usually a Read.
            frame: Frame to read it at (default: current).
            keys: Only keys containing any of these substrings (case-insensitive).
        """
        params: dict = {"node_name": node_name}
        if frame is not None:
            params["frame"] = frame
        if keys:
            params["keys"] = keys
        return conn.send_command("get_node_metadata", params)

    @mcp.tool(annotations=RO)
    def list_channels(node_name: str) -> dict:
        """Layers and channels available at a node's output (e.g. depth.Z, N.x).

        Args:
            node_name: Node to inspect.
        """
        return conn.send_command("list_channels", {"node_name": node_name})

    @mcp.tool(annotations=RO)
    def list_node_classes(category: str | None = None, contains: str | None = None) -> dict:
        """Node classes from the Nodes menu, with their menu path. Use before
        create_node when unsure of a class name (ML/NukeX nodes may be missing
        from the menu: check those with node_classes_available).

        Args:
            category: Menu path filter, e.g. "Filter" or "3D".
            contains: Substring of the class or label, e.g. "blur".
        """
        params = {}
        if category:
            params["category"] = category
        if contains:
            params["contains"] = contains
        return conn.send_command("list_node_classes", params)

    @mcp.tool(annotations=RO)
    def node_classes_available(classes: list[str]) -> dict:
        """Whether node classes exist in this session (e.g. CopyCat, BigCat, Inference,
        CameraTracker, or a third-party plugin). Probed by creating and deleting
        each class once with undo disabled; leaves no trace.

        Args:
            classes: Class names to check.
        """
        return conn.send_command("node_classes_available", {"classes": classes})

    @mcp.tool(annotations=RO)
    def get_node_default_knobs(node_class: str) -> dict:
        """Default knob values of a node class (probed on a throw-away node).

        Args:
            node_class: e.g. "ZDefocus2".
        """
        return conn.send_command("get_node_default_knobs", {"node_class": node_class})

    @mcp.tool(annotations=RO)
    def find_error_nodes(recurse_groups: bool = True) -> dict:
        """Every node currently in error, with its message.

        Args:
            recurse_groups: Look inside Groups too.
        """
        return conn.send_command("find_error_nodes", {"recurse_groups": recurse_groups})

    @mcp.tool(annotations=RO)
    def find_missing_frames(node_names: list[str] | None = None,
                            timeout_seconds: float = 120.0) -> dict:
        """Check on disk every frame of every Read (or the given nodes) and report
        gaps as frame ranges.

        Args:
            node_names: Limit to these Reads.
            timeout_seconds: Raise for long sequences on network drives.
        """
        params = {"node_names": node_names} if node_names else {}
        return conn.send_command("find_missing_frames", params, timeout=timeout_seconds)

    @mcp.tool(annotations=RO)
    def glob_files(pattern: str, limit: int = 500) -> dict:
        """List files on disk from Nuke's point of view (render folders, plates).

        Args:
            pattern: glob pattern, e.g. "T:/show/shot/render/v003/*.exr".
            limit: Max files returned.
        """
        return conn.send_command("glob_files", {"pattern": pattern, "limit": limit})
