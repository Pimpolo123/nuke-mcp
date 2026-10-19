"""Session tools: undo history, agent undo, console, journal, capabilities, reload."""

import os
import sys

from .. import console, journal, undo
from ..constants import ADDON_VERSION, UNDO_PREFIX
from ..dispatch import COMMANDS, META, command
from ..util import CommandError, get_nuke


@command("undo_history")
def undo_history(params):
    return {"steps": undo.history(int(params.get("limit", 20))), "agent_prefix": UNDO_PREFIX}


@command("undo_agent_session", journal=True)
def undo_agent_session(params):
    """Undo the agent's consecutive steps from the top of the undo stack.

    Stops at the first step made by the user, so their work is never touched.
    Everything can be brought back with Redo.
    """
    return undo.undo_agent_steps(int(params.get("max_steps", 200)))


@command("get_console_log")
def get_console_log(params):
    lines = console.read(last_n=int(params.get("last_n", 200)), stream=params.get("stream"),
                         contains=params.get("contains"), since_seq=params.get("since_seq"))
    return {"lines": lines, "count": len(lines),
            "last_seq": lines[-1]["seq"] if lines else params.get("since_seq")}


@command("clear_console_log")
def clear_console_log(params):
    console.clear()
    return {"cleared": True}


@command("get_session_journal")
def get_session_journal(params):
    path = params.get("path") or journal.path()
    return {"path": path, "entries": journal.read(int(params.get("last_n", 50)), path)}


@command("list_session_journals")
def list_session_journals(params):
    folder = os.path.dirname(journal.path())
    files = sorted((os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".jsonl")),
                   key=os.path.getmtime, reverse=True)
    return {"current": journal.path(), "files": files}


@command("replay_journal", undo=True, label="replay_journal")
def replay_journal(params):
    """Re-run the successful, undoable commands of a journal in this script.

    dry_run (default) only lists what would run. The replay is one atomic undo
    step: if any command fails, nothing it did stays.
    """
    path = params.get("path") or journal.path()
    entries = journal.read(0, path)
    skip = set(params.get("skip_commands") or [])
    plan = [e for e in entries
            if e.get("status") == "ok" and e.get("command") in META
            and META[e["command"]]["undo"] and e["command"] not in skip
            and e["command"] != "replay_journal" and isinstance(e.get("params"), dict)
            and "_truncated_json" not in e["params"]]
    if params.get("dry_run", True):
        return {"dry_run": True, "path": path,
                "would_run": [{"command": e["command"], "params": e["params"]} for e in plan]}
    done = []
    for i, entry in enumerate(plan):
        value = COMMANDS[entry["command"]](entry["params"])
        if isinstance(value, dict) and value.get("status") == "error":
            raise CommandError("step %d (%s) failed: %s" % (i, entry["command"], value.get("error")))
        done.append(entry["command"])
    return {"replayed": done, "count": len(done), "path": path}


@command("get_capabilities")
def get_capabilities(params):
    nuke = get_nuke()
    root = nuke.root()
    try:
        from PySide6 import __version__ as pyside_version
    except ImportError:
        try:
            from PySide2 import __version__ as pyside_version
        except ImportError:
            pyside_version = None
    caps = {
        "addon_version": ADDON_VERSION,
        "nuke_version": nuke.NUKE_VERSION_STRING,
        "nukex": bool(nuke.env.get("nukex")),
        "studio": bool(nuke.env.get("studio")),
        "gui": bool(getattr(nuke, "GUI", False)),
        "python": sys.version.split()[0],
        "pyside": pyside_version,
        "pid": os.getpid(),
        "commands": sorted(COMMANDS),
        "undo_supported": hasattr(nuke, "Undo"),
    }
    if "colorManagement" in root.knobs():
        caps["color_management"] = root["colorManagement"].value()
    for key in ("OCIO_config", "customOCIOConfigPath"):
        if key in root.knobs():
            caps[key] = root[key].value()
    caps["ocio_env"] = os.environ.get("OCIO")
    from .inspect import _walk_menu
    found = []
    try:
        _walk_menu(nuke.menu("Nodes"), [], found)
    except Exception:
        pass
    classes = {f["class"] for f in found}
    caps["ml"] = {c: c in classes for c in ("CopyCat", "BigCat", "Inference")}
    caps["notable_nodes"] = {c: c in classes for c in
                             ("CameraTracker", "OCIODisplay", "Polychase", "GaussianSplat",
                              "ScanlineRender2", "DeepRead", "SmartVector")}
    return caps


@command("addon_reload")
def addon_reload(params):
    """Hot-reload the addon code (after updating its files) without restarting Nuke.

    Runs right after this reply is sent; the client reconnects on its own.
    """
    nuke = get_nuke()
    if not getattr(nuke, "GUI", False):
        raise CommandError("addon_reload is only available in GUI sessions")
    try:
        from PySide6.QtCore import QTimer
    except ImportError:
        from PySide2.QtCore import QTimer
    package = sys.modules[__name__.rsplit(".", 2)[0]]
    QTimer.singleShot(300, package.reload)
    return {"reloading": True, "from_version": ADDON_VERSION}
