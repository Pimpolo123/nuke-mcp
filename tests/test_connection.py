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


def test_send_not_connected(monkeypatch):
    from nukemcp import connection
    # Don't let the lazy connect find a real Nuke running on this machine
    monkeypatch.setattr(connection, "scan_instances", lambda *a, **k: [])
    conn = connection.NukeConnection(port=1)
    with pytest.raises(NukeConnectionError, match="No Nuke addon found"):
        conn.send({"type": "ping"})


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_scan_and_switch_between_instances():
    from nukemcp.connection import NukeConnection, scan_instances
    from nukemcp.mock import MockNukeServer

    port_a, port_b = _free_port(), _free_port()
    a = MockNukeServer(port=port_a, nuke_version="16.0v6", variant="NukeX")
    b = MockNukeServer(port=port_b, nuke_version="17.0v4", variant="NukeX")
    a.start()
    b.start()
    try:
        assert scan_instances("127.0.0.1", port_a, 1)[0]["nuke_version"] == "16.0v6"
        assert scan_instances("127.0.0.1", port_b, 1)[0]["nuke_version"] == "17.0v4"

        conn = NukeConnection("127.0.0.1", port_a)
        assert conn.ensure_connected()["nuke_version"] == "16.0v6"
        assert conn.switch(port_b)["nuke_version"] == "17.0v4"
        assert "name" in conn.send_command("get_script_info")
        conn.disconnect()
    finally:
        a.stop()
        b.stop()
