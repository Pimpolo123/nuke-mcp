"""Viewer, timeline and 'seeing' tools: captures of Nuke's UI and rendered node previews."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nukemcp.tools._helpers import image_content

if TYPE_CHECKING:
    from nukemcp.server import NukeMCPServer


def register(server: NukeMCPServer):
    mcp = server.mcp
    conn = server.connection

    @mcp.tool(annotations={"readOnlyHint": True})
    def render_node_preview(node_name: str, frame: int | None = None, max_size: int = 1024,
                            channels: str = "rgb", view_transform: bool | str = True):
        """LOOK at the image any node produces, at any frame.

        Renders one frame to a small PNG through the active Viewer's OCIO
        display/view, so it looks like what the compositor sees. Temporary
        nodes are created with undo disabled and the user's callbacks
        suspended, then deleted: nothing is left in the script or undo stack.
        Independent of what the Viewer currently shows.

        Args:
            node_name: Node to look at.
            frame: Frame (default: current).
            max_size: Longest side in pixels.
            channels: "rgb" or "alpha" (alpha shown as grey).
            view_transform: True = viewer's display/view, False = raw values (data
                            passes), or "Display/View" to force one (e.g. "ACES/Rec.709").
        """
        params: dict = {"node_name": node_name, "max_size": max_size, "channels": channels,
                        "view_transform": view_transform}
        if frame is not None:
            params["frame"] = frame
        return image_content(conn.send_command("render_node_preview", params, timeout=180.0))

    @mcp.tool(annotations={"readOnlyHint": True})
    def capture_screen(mode: str = "window", max_size: int = 1600, format: str = "png"):
        """LOOK at Nuke's interface: the main window or one panel.

        mode: "window", "dag" (Node Graph), "viewer", "properties", "script_editor",
        "curve_editor", "dope_sheet", any text matching a panel title, or "screen"
        (the whole monitor — includes other applications; use only if asked).
        On Windows panels are captured with PrintWindow: only Nuke's pixels,
        GL viewer included, even if other windows cover Nuke.

        Args:
            mode: What to capture.
            max_size: Longest side in pixels.
            format: "png" or "jpg" (smaller).
        """
        return image_content(conn.send_command("capture_screen", {
            "mode": mode, "max_size": max_size, "format": format}, timeout=30.0))

    @mcp.tool(annotations={"readOnlyHint": True})
    def get_viewer_info() -> dict:
        """Active Viewer: inputs, active input, frame, viewer process (display/view),
        gain, gamma, channels, frame range."""
        return conn.send_command("get_viewer_info")

    @mcp.tool()
    def set_viewer_input(node_name: str, input_index: int = 0) -> dict:
        """Show a node in the active Viewer (on input slot input_index).

        Args:
            node_name: Node to view.
            input_index: Viewer input slot (0-9, keyboard 1-0).
        """
        return conn.send_command("set_viewer_input", {"node_name": node_name,
                                                      "input_index": input_index})

    @mcp.tool()
    def set_current_frame(frame: int) -> dict:
        """Move the timeline to a frame.

        Args:
            frame: Frame number.
        """
        return conn.send_command("set_current_frame", {"frame": frame})

    @mcp.tool()
    def zoom_to_node(node_name: str, scale: float = 1.0) -> dict:
        """Center the Node Graph on a node.

        Args:
            node_name: Node.
            scale: Zoom level.
        """
        return conn.send_command("zoom_to_node", {"node_name": node_name, "scale": scale})

    @mcp.tool()
    def viewer_playback(action: str, frame: int | None = None) -> dict:
        """Control playback: play, backward, stop, next, prev, goto (needs frame).

        Args:
            action: One of the actions above.
            frame: Target for goto.
        """
        params: dict = {"action": action}
        if frame is not None:
            params["frame"] = frame
        return conn.send_command("viewer_playback", params)
