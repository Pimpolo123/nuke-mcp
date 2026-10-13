"""Multi-instance tools — list running Nuke sessions and switch between them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nukemcp.connection import scan_instances

if TYPE_CHECKING:
    from nukemcp.server import NukeMCPServer


def register(server: NukeMCPServer):
    mcp = server.mcp
    conn = server.connection

    @mcp.tool(annotations={"readOnlyHint": True})
    def list_nuke_instances() -> dict:
        """List every running Nuke session with the NukeMCP addon started.

        Each entry has the port, Nuke version/variant, PID and open script.
        "active" marks the session that tools are currently talking to.
        Use select_nuke_instance to switch.
        """
        instances = scan_instances(conn.host)
        for inst in instances:
            inst["active"] = conn.is_connected and inst["port"] == conn.port
        return {"instances": instances, "count": len(instances)}

    @mcp.tool()
    def select_nuke_instance(port: int | None = None, script: str | None = None) -> dict:
        """Switch all Nuke tools to another running Nuke session.

        Pick it by port, or by part of the open script's name/path
        (case-insensitive, e.g. "0040" or "SC010"). Call list_nuke_instances
        first if you don't know what is open.

        Args:
            port: Port of the Nuke session (from list_nuke_instances).
            script: Text contained in the target session's script path.
        """
        if port is None and not script:
            raise ValueError("Give either port or script.")
        if port is None:
            needle = script.lower()
            matches = [
                i for i in scan_instances(conn.host)
                if needle in (i.get("script") or "").lower()
            ]
            if not matches:
                raise ValueError(f"No open Nuke script matches {script!r}.")
            if len(matches) > 1:
                return {
                    "message": "Several sessions match; call again with port.",
                    "matches": matches,
                }
            port = matches[0]["port"]
        handshake = conn.switch(port)
        return {"port": port, **{k: v for k, v in handshake.items() if k != "type"}}
