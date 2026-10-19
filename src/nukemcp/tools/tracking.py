"""Tracking tools — 2D tracking, camera tracking, stabilization. NukeX-gated."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nukemcp.server import NukeMCPServer


def register(server: NukeMCPServer):
    if not server.version.is_nukex:
        return

    mcp = server.mcp
    conn = server.connection

    @mcp.tool()
    def create_tracker(source_node: str, name: str = "tracker") -> dict:
        """Create a Tracker node connected to a source.

        Requires NukeX.

        Args:
            source_node: Node to track.
            name: Name for the Tracker node.
        """
        return conn.send_command("create_tracker", {"source_node": source_node, "name": name})

    @mcp.tool(annotations={"destructiveHint": True})
    def solve_tracker(
        tracker_node: str,
        first_frame: int | None = None,
        last_frame: int | None = None,
        confirm: bool = False,
    ) -> dict:
        """Run the tracking solve on a Tracker node.

        This can be a long operation. Requires confirmation.

        Args:
            tracker_node: Name of the Tracker node to solve.
            first_frame: Start frame (defaults to script range).
            last_frame: End frame (defaults to script range).
            confirm: Must be True to proceed.
        """
        if not confirm:
            return {
                "action": "solve_tracker",
                "tracker_node": tracker_node,
                "message": "This will run a tracking solve. Confirm to proceed.",
            }
        params = {"tracker_node": tracker_node}
        if first_frame is not None:
            params["first_frame"] = first_frame
        if last_frame is not None:
            params["last_frame"] = last_frame
        return conn.send_command("solve_tracker", params, timeout=3600.0)

    @mcp.tool()
    def setup_stabilize(source_node: str, tracker_node: str, name: str = "stabilize") -> dict:
        """Set up a stabilization using tracking data from a Tracker node.

        Args:
            source_node: Node to stabilize.
            tracker_node: Tracker node with solved tracking data.
            name: Name for the stabilize node.
        """
        return conn.send_command("setup_stabilize", {
            "source_node": source_node, "tracker_node": tracker_node, "name": name,
        })

    @mcp.tool()
    def create_camera_tracker(source_node: str, name: str = "camera_tracker") -> dict:
        """Create a CameraTracker node for 3D camera solving.

        Requires NukeX.

        Args:
            source_node: Node to track (plate footage).
            name: Name for the CameraTracker node.
        """
        return conn.send_command("create_camera_tracker", {
            "source_node": source_node, "name": name,
        })

    # -- CameraTracker user tracks ---------------------------------------------

    @mcp.tool(annotations={"readOnlyHint": True})
    def cameratracker_list_user_tracks(node_name: str) -> dict:
        """User tracks of a CameraTracker: name, keyed frames and range, solved 3D
        position. (The point used as scene origin sits at ~0,0,0 and is valid.)

        Args:
            node_name: The CameraTracker.
        """
        return conn.send_command("cameratracker_list_user_tracks", {"node_name": node_name})

    @mcp.tool()
    def cameratracker_import_user_tracks(node_name: str, tracks: list[dict],
                                         timeout_seconds: float = 600.0) -> dict:
        """Add 2D tracks (from MegaFlow, CoTracker, 3DE, another tracker...) as
        CameraTracker User Tracks, without the modal import dialog.

        Handles the four silent traps of doing this from Python (panel must be
        built, cells must be set animated, stray keys, panel redraw slowness)
        and verifies the key count read back from the knob. The camera must
        still be solved from the GUI: Solve has no Python entry point.

        Args:
            node_name: The CameraTracker.
            tracks: [{"keys": {frame: [x, y], ...}}, ...] in plate pixel coordinates.
            timeout_seconds: Large imports (90 tracks x 300 frames) take a while.
        """
        return conn.send_command("cameratracker_import_user_tracks",
                                 {"node_name": node_name, "tracks": tracks},
                                 timeout=timeout_seconds)

    @mcp.tool()
    def cameratracker_user_tracks_to_axes(
        node_name: str,
        tracks: list | None = None,
        camera_node: str | None = None,
        axis_class: str | None = None,
        skip_existing: bool = True,
        verify: bool = True,
        qc_frames: int = 5,
    ) -> dict:
        """Export every solved user track as its own Axis, in one undo step.

        Nuke's right-click 'create > axis' puts ONE object at the average of the
        selected points; this makes one Axis per track at its solved position,
        labelled with the track name. Tracks that already have an Axis at the
        same position are skipped, so it can finish a half-done export.
        verify=True reprojects each point through the solved camera and reports
        the pixel error against its 2D track (median, max, worst tracks).

        Args:
            node_name: The CameraTracker.
            tracks: Only these tracks (names like "user 3" or indices).
            camera_node: The solved camera (auto-detected when unambiguous).
            axis_class: Axis class to create (default: same as existing Axis nodes).
            skip_existing: Don't duplicate tracks already exported.
            verify: Reprojection QC.
            qc_frames: Frames sampled across the script range for the QC.
        """
        params: dict = {"node_name": node_name, "skip_existing": skip_existing,
                        "verify": verify, "qc_frames": qc_frames}
        if tracks:
            params["tracks"] = tracks
        if camera_node:
            params["camera_node"] = camera_node
        if axis_class:
            params["axis_class"] = axis_class
        return conn.send_command("cameratracker_user_tracks_to_axes", params, timeout=300.0)

    @mcp.tool(annotations={"readOnlyHint": True})
    def cameratracker_reprojection_qc(node_name: str, camera_node: str | None = None,
                                      qc_frames: int = 5) -> dict:
        """Reprojection error of every solved user track through the solved camera:
        per-track pixel error at sampled frames, median/max and the worst tracks.

        Args:
            node_name: The CameraTracker.
            camera_node: The solved camera (auto-detected when unambiguous).
            qc_frames: Frames sampled across the script range.
        """
        params: dict = {"node_name": node_name, "qc_frames": qc_frames}
        if camera_node:
            params["camera_node"] = camera_node
        return conn.send_command("cameratracker_reprojection_qc", params, timeout=300.0)
