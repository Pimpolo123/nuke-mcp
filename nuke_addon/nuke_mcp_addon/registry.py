"""On-disk registry of running Nuke sessions with the addon started.

Each session writes %TEMP%/nuke_mcp/instances/<pid>.json and refreshes it every
few seconds from a plain thread. The MCP server can list sessions from these
files without opening a socket to each one, which also works while a session is
busy rendering and could not answer a handshake.

The heartbeat thread never touches the Nuke API (that is only safe on the main
thread); the script name is refreshed from Nuke callbacks and from commands.
"""

import json
import os
import threading
import time

from .constants import ADDON_VERSION, HEARTBEAT_SECONDS
from .util import temp_dir

# Survive addon hot reloads: one heartbeat thread, one state.
_state = globals().get("_state") or {}
_lock = globals().get("_lock") or threading.Lock()
_stop = globals().get("_stop") or threading.Event()
_thread = globals().get("_thread")


def _file():
    return os.path.join(temp_dir("instances"), "%d.json" % os.getpid())


def update(**fields):
    with _lock:
        _state.update(fields)
    _write()


def _write():
    with _lock:
        data = dict(_state)
    data["heartbeat"] = time.time()
    tmp = _file() + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, _file())
    except OSError:
        pass


def _beat():
    while not _stop.wait(HEARTBEAT_SECONDS):
        _write()


def start(port, nuke_version, variant, script):
    global _thread
    update(pid=os.getpid(), port=port, nuke_version=nuke_version, variant=variant,
           script=script, addon_version=ADDON_VERSION, started=time.time())
    _stop.clear()
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_beat, name="nuke-mcp-heartbeat", daemon=True)
        _thread.start()


def stop():
    _stop.set()
    try:
        os.remove(_file())
    except OSError:
        pass


def script_name():
    with _lock:
        return _state.get("script", "")
