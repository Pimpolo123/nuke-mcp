"""MCP-layer tests for the tools added in 0.2 (darvosis fork).

The addon logic behind them is tested against real Nuke (15.1 / 17.0 / 17.1);
here the mock proves each tool forwards the right parameters, that images come
back as MCP image content, and that the safety gates work.
"""

import asyncio
import json
import os
import time

import pytest
from fastmcp import Client

from nukemcp.server import build_server
from nukemcp.tools._safety import scan


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mcp():
    return build_server(port=_free_port(), mock=True, mock_version="17.1v2", mock_variant="NukeX")


def call(mcp, name, args=None):
    async def go():
        async with Client(mcp) as client:
            return await client.call_tool(name, args or {}, raise_on_error=False)

    return asyncio.run(go())


def payload(result):
    for item in result.content:
        if getattr(item, "type", "") == "text":
            return json.loads(item.text)
    return None


# -- safety scan ------------------------------------------------------------------

@pytest.mark.parametrize("code", [
    "import os\nos.remove('x')",
    "import os as o\no.remove('x')",
    "from shutil import rmtree\nrmtree('x')",
    "import subprocess\nsubprocess.run(['ls'])",
    "nuke.scriptClose()",
    "open('f.txt', 'w').write('x')",
    "open('f.txt', mode='a')",
    "from pathlib import Path\nPath('x').unlink()",
    "exec(some_string)",
])
def test_scan_flags_dangerous(code):
    assert scan(code), code


@pytest.mark.parametrize("code", [
    "nuke.toNode('Blur1')['size'].value()",
    "result = [n.name() for n in nuke.allNodes()]",
    "s = 'a/b'.replace('/', '_')",
    "open('f.txt').read()",
    "open('f.txt', 'r')",
    "nuke.delete(nuke.toNode('Blur1'))",
    "def f(:",  # syntax errors are left to Nuke
])
def test_scan_allows_normal_code(code):
    assert not scan(code), code


# -- tools ------------------------------------------------------------------------

def test_new_tools_registered(mcp):
    async def names():
        async with Client(mcp) as client:
            return {t.name for t in await client.list_tools()}

    tools = asyncio.run(names())
    expected = {
        "query_python", "batch", "get_node_graph", "scene_digest", "scene_delta",
        "render_node_preview", "capture_screen", "undo_history", "undo_agent_session",
        "get_console_log", "get_session_journal", "replay_journal", "get_capabilities",
        "render_start", "task_status", "task_cancel", "audit_color",
        "cameratracker_user_tracks_to_axes", "cameratracker_import_user_tracks",
        "cameratracker_reprojection_qc", "node_classes_available", "find_missing_frames",
        "set_knob_keyframes", "replace_filepaths", "addon_reload",
        "list_nuke_instances", "select_nuke_instance",
    }
    assert expected <= tools, expected - tools


def test_query_python_forwards(mcp):
    data = payload(call(mcp, "query_python", {"code": "nuke.root().name()"}))
    assert data["echo"] == "query_python"
    assert data["params"]["code"] == "nuke.root().name()"


def test_query_python_blocks_unsafe(mcp):
    data = payload(call(mcp, "query_python", {"code": "import os\nos.remove('x')"}))
    assert data["action"] == "blocked"
    assert data["findings"][0]["line"] == 2


def test_execute_python_needs_confirm_then_scans(mcp):
    data = payload(call(mcp, "execute_python", {"code": "x = 1"}))
    assert data["action"] == "execute_python"
    data = payload(call(mcp, "execute_python", {"code": "nuke.scriptClose()", "confirm": True}))
    assert data["action"] == "blocked"


def test_batch_blocks_unsafe_python_inside(mcp):
    ops = [{"type": "create_node", "params": {"node_class": "Grade"}},
           {"type": "execute_python", "params": {"code": "import shutil\nshutil.rmtree('x')"}}]
    data = payload(call(mcp, "batch", {"operations": ops}))
    assert data["action"] == "blocked"
    assert data["findings"][0]["operation"] == 1


def test_render_node_preview_returns_image(mcp):
    result = call(mcp, "render_node_preview", {"node_name": "Blur1", "frame": 1001})
    kinds = [getattr(c, "type", "") for c in result.content]
    assert "image" in kinds
    info = payload(result)
    assert info["echo"]["node_name"] == "Blur1" and info["echo"]["frame"] == 1001


def test_capture_screen_returns_image(mcp):
    result = call(mcp, "capture_screen", {"mode": "dag"})
    assert any(getattr(c, "type", "") == "image" for c in result.content)


def test_render_start_requires_confirm(mcp):
    data = payload(call(mcp, "render_start", {"write_node": "Write1"}))
    assert data["action"] == "render_start"
    data = payload(call(mcp, "render_start", {"write_node": "Write1", "confirm": True,
                                              "first_frame": 1, "last_frame": 5}))
    assert data["params"] == {"step": 1, "continue_on_error": False, "write_node": "Write1",
                              "first_frame": 1, "last_frame": 5}


def test_undo_agent_session_requires_confirm(mcp):
    assert payload(call(mcp, "undo_agent_session"))["action"] == "undo_agent_session"
    assert payload(call(mcp, "undo_agent_session", {"confirm": True}))["echo"] == "undo_agent_session"


def test_user_tracks_to_axes_params(mcp):
    data = payload(call(mcp, "cameratracker_user_tracks_to_axes",
                        {"node_name": "CameraTracker2", "tracks": ["user 4"]}))
    assert data["params"]["tracks"] == ["user 4"]
    assert data["params"]["skip_existing"] is True and data["params"]["verify"] is True


# -- instance registry & port ----------------------------------------------------

def test_registry_instances(tmp_path, monkeypatch):
    from nukemcp import connection

    monkeypatch.setattr(connection.tempfile, "gettempdir", lambda: str(tmp_path))
    folder = tmp_path / "nuke_mcp" / "instances"
    folder.mkdir(parents=True)
    (folder / "1.json").write_text(json.dumps(
        {"pid": 1, "port": 54329, "nuke_version": "17.1v2", "heartbeat": time.time()}))
    (folder / "2.json").write_text(json.dumps(
        {"pid": 2, "port": 54328, "nuke_version": "15.1v6", "heartbeat": time.time() - 3600}))
    found = connection.registry_instances()
    assert set(found) == {54329}  # the stale one is ignored
    listed = connection.scan_instances("127.0.0.1", 54329, 1)
    assert listed[0]["source"] == "registry" and listed[0]["nuke_version"] == "17.1v2"


def test_default_port_from_env():
    """An MCP server started from inside a Nuke session inherits NUKE_MCP_PORT."""
    import subprocess
    import sys

    env = dict(os.environ, NUKE_MCP_PORT="54327")
    out = subprocess.run(
        [sys.executable, "-c", "import nukemcp.connection as c; print(c.DEFAULT_PORT)"],
        env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "54327"


@pytest.mark.parametrize("tool,args,command", [
    ("get_node_graph", {"filter_class": "Blur"}, "get_node_graph"),
    ("scene_digest", {}, "scene_digest"),
    ("scene_delta", {"token": "abc"}, "scene_delta"),
    ("get_selection", {}, "get_selection"),
    ("select_nodes", {"node_names": ["Blur1"]}, "select_nodes"),
    ("get_node_metadata", {"node_name": "Read1", "frame": 1001, "keys": ["exr"]}, "get_node_metadata"),
    ("list_channels", {"node_name": "Read1"}, "list_channels"),
    ("list_node_classes", {"category": "Filter", "contains": "blur"}, "list_node_classes"),
    ("node_classes_available", {"classes": ["CopyCat"]}, "node_classes_available"),
    ("get_node_default_knobs", {"node_class": "Blur"}, "get_node_default_knobs"),
    ("find_missing_frames", {"node_names": ["Read1"]}, "find_missing_frames"),
    ("glob_files", {"pattern": "C:/x/*.exr"}, "glob_files"),
    ("set_knob_expression", {"node_name": "B", "knob_name": "size", "expression": "frame",
                             "field_index": 0}, "set_knob_expression"),
    ("set_knob_keyframes", {"node_name": "B", "knob_name": "size", "keys": {"1": 2},
                            "field_index": 0}, "set_knob_keyframes"),
    ("remove_knob_animation", {"node_name": "B", "knob_name": "size", "field_index": 0},
     "remove_knob_animation"),
    ("disconnect_input", {"node_name": "B"}, "disconnect_input"),
    ("duplicate_node", {"node_name": "B"}, "duplicate_node"),
    ("merge_script", {"path": "C:/x.nk"}, "merge_script"),
    ("replace_filepaths", {"find": "X:", "replace": "Y:", "node_classes": ["Read"]},
     "replace_filepaths"),
    ("get_viewer_info", {}, "get_viewer_info"),
    ("set_viewer_input", {"node_name": "B"}, "set_viewer_input"),
    ("set_current_frame", {"frame": 1001}, "set_current_frame"),
    ("zoom_to_node", {"node_name": "B"}, "zoom_to_node"),
    ("viewer_playback", {"action": "goto", "frame": 1010}, "viewer_playback"),
    ("undo_history", {}, "undo_history"),
    ("get_console_log", {"stream": "stderr", "contains": "error", "since_seq": 3},
     "get_console_log"),
    ("clear_console_log", {}, "clear_console_log"),
    ("get_session_journal", {"path": "C:/j.jsonl"}, "get_session_journal"),
    ("list_session_journals", {}, "list_session_journals"),
    ("replay_journal", {"path": "C:/j.jsonl", "skip_commands": ["delete_node"]}, "replay_journal"),
    ("get_capabilities", {}, "get_capabilities"),
    ("task_status", {"task_id": "abc"}, "task_status"),
    ("task_cancel", {"task_id": "abc"}, "task_cancel"),
    ("list_tasks", {}, "list_tasks"),
    ("audit_color", {}, "audit_color"),
    ("cameratracker_list_user_tracks", {"node_name": "CT"}, "cameratracker_list_user_tracks"),
    ("cameratracker_import_user_tracks", {"node_name": "CT", "tracks": [{"keys": {"1": [1, 2]}}]},
     "cameratracker_import_user_tracks"),
    ("cameratracker_reprojection_qc", {"node_name": "CT", "camera_node": "Cam"},
     "cameratracker_reprojection_qc"),
])
def test_tool_forwards_to_addon_command(mcp, tool, args, command):
    data = payload(call(mcp, tool, args))
    assert data["echo"] == command, data
