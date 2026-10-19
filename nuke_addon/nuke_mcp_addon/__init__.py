"""NukeMCP addon: the socket server that runs inside Nuke.

Usage from menu.py or the Script Editor::

    import nuke_mcp_addon
    nuke_mcp_addon.start(show_panel=False)   # silent auto-start
    nuke_mcp_addon.start()                   # show the status panel
    nuke_mcp_addon.reload()                  # hot-reload after updating the files

Each Nuke session takes the first free port in 54321-54330. Only the standard
library and the PySide that ships with Nuke are used.
"""

import importlib
import sys

from .constants import ADDON_VERSION, DEFAULT_PORT, PORT_RANGE  # noqa: F401
from .dispatch import COMMANDS, command, run_command  # noqa: F401
from . import handlers  # noqa: F401  (registers every command)
from .server import NukeMCPServer  # noqa: F401

# Survive importlib.reload(): keep the live panel/server objects.
_panel = globals().get("_panel")
_headless_server = globals().get("_headless_server")


def __getattr__(name):
    # Qt is imported only when the panel is actually needed (not in nuke -t).
    if name == "NukeMCPPanel":
        from .panel import NukeMCPPanel
        return NukeMCPPanel
    # 0.1 compatibility: in-Nuke tools counted connected clients through this name.
    if name == "_event_client_sockets":
        from . import events
        return events._clients
    raise AttributeError(name)


def _gui():
    try:
        import nuke
        return bool(nuke.GUI)
    except ImportError:
        return False


def start(port=DEFAULT_PORT, show_panel=True):
    """Start the server (idempotent). In terminal mode this blocks and serves."""
    global _panel, _headless_server
    if not _gui():
        _headless_server = NukeMCPServer(port)
        _headless_server.serve_forever()
        return _headless_server
    if _panel is None:
        from .panel import NukeMCPPanel
        _panel = NukeMCPPanel(port=port)
    if show_panel:
        _panel.show()
        _panel.raise_()
    if not (_panel._server and _panel._server._running):
        _panel._toggle_server()
    return _panel._server


def stop():
    if _panel is not None and _panel._server and _panel._server._running:
        _panel._toggle_server()
    if _headless_server is not None:
        _headless_server.stop()


def server():
    """The running server in this session, or None."""
    if _panel is not None and _panel._server and _panel._server._running:
        return _panel._server
    return None


def reload():
    """Reload the addon code without restarting Nuke, keeping the same port."""
    global _panel
    running = server()
    port = running.port if running else DEFAULT_PORT
    visible = bool(_panel is not None and _panel.isVisible())
    stop()
    if _panel is not None:
        _panel.close()
        _panel.deleteLater()
        _panel = None
    prefix = __name__ + "."
    order = ["constants", "util", "undo", "hooks", "console", "journal", "registry",
             "events", "dispatch"]
    for short in order:
        mod = sys.modules.get(prefix + short)
        if mod is not None:
            importlib.reload(mod)
    for name in sorted(n for n in sys.modules if n.startswith(prefix + "handlers.")):
        importlib.reload(sys.modules[name])
    for short in ("handlers", "server", "panel"):
        mod = sys.modules.get(prefix + short)
        if mod is not None:
            importlib.reload(mod)
    package = importlib.reload(sys.modules[__name__])
    return package.start(port=port, show_panel=visible)
