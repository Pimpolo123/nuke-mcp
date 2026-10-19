"""Tests for NukeConnection.send_command and error handling."""

import pytest

from nukemcp.connection import NukeConnectionError


def test_send_command_success(connection):
    result = connection.send_command("get_script_info")
    assert "name" in result
    assert "fps" in result


def test_send_command_error_raises(connection):
    with pytest.raises(RuntimeError, match="not found"):
        connection.send_command("get_node_info", {"node_name": "nonexistent"})


def test_send_command_unknown_command(connection):
    with pytest.raises(RuntimeError, match="Unknown command"):
        connection.send_command("totally_bogus_command")


def test_send_command_with_params(connection):
    result = connection.send_command("create_node", {"node_class": "Grade", "name": "MyGrade"})
    assert result["name"] == "MyGrade"
    assert result["class"] == "Grade"


def test_send_reconnects_after_drop(connection):
    """A dropped socket must not kill the connection for good."""
    connection._reset()
    assert not connection.is_connected

    result = connection.send_command("get_script_info")
    assert "name" in result
    assert connection.is_connected


def test_send_raises_when_addon_unreachable(mock_port):
    """mock_port is free but unserved — nothing is listening on it."""
    from nukemcp.connection import NukeConnection

    conn = NukeConnection("127.0.0.1", mock_port)
    with pytest.raises(NukeConnectionError, match="Failed to connect"):
        conn.send({"type": "ping"})
