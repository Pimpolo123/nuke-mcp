"""Integration tests — verify build_server registers all modules correctly."""

import asyncio

import pytest

from nukemcp.server import build_server


def _find_free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get_tool_names(mcp) -> list[str]:
    """Get tool names from a FastMCP server."""
    result = mcp._tool_manager.get_tools()
    if asyncio.iscoroutine(result):
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(result)
        finally:
            loop.close()
    # FastMCP returns a dict of {name: Tool} — just need the keys
    if isinstance(result, dict):
        return list(result.keys())
    return [t.name for t in result]


@pytest.fixture
def server():
    port = _find_free_port()
    mcp = build_server(port=port, mock=True, mock_version="17.0v1", mock_variant="NukeX")
    yield mcp


def test_server_has_tools(server):
    """Verify core tools are registered."""
    tool_names = _get_tool_names(server)
    # Phase 1
    assert "get_script_info" in tool_names
    assert "create_node" in tool_names
    assert "execute_python" in tool_names
    # Phase 2
    assert "read_memory" in tool_names
    assert "write_memory" in tool_names
    # Phase 3
    assert "setup_keyer" in tool_names
    assert "setup_write_node" in tool_names
    assert "find_nodes_by_type" in tool_names
    # Phase 4 (NukeX, version 17)
    assert "create_tracker" in tool_names
    assert "setup_copycat" in tool_names
    assert "import_splat" in tool_names
    assert "create_annotation" in tool_names
    # Phase 5
    assert "search_nuke_docs" in tool_names
    # Phase 6
    assert "subscribe_events" in tool_names


def test_server_plain_nuke_keeps_nukex_tools():
    """NukeX tools stay registered: the user may switch to a NukeX session later."""
    port = _find_free_port()
    mcp = build_server(port=port, mock=True, mock_version="17.0v1", mock_variant="Nuke")
    tool_names = _get_tool_names(mcp)
    assert "create_tracker" in tool_names
    assert "setup_copycat" in tool_names
    assert "setup_deep_pipeline" in tool_names
    assert "get_script_info" in tool_names
    assert "list_nuke_instances" in tool_names
    assert "select_nuke_instance" in tool_names


def test_server_old_version_keeps_17_tools():
    """Nuke 17 tools stay registered: the user may switch to a Nuke 17 session later."""
    port = _find_free_port()
    mcp = build_server(port=port, mock=True, mock_version="15.1v3", mock_variant="NukeX")
    tool_names = _get_tool_names(mcp)
    assert "import_splat" in tool_names
    assert "create_annotation" in tool_names
    assert "create_tracker" in tool_names
