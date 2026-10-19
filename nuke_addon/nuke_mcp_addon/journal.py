"""Session journal: one JSON line per command that changed the script.

Files live in %TEMP%/nuke_mcp/sessions/<date>_<pid>.jsonl, newest 30 kept.
The journal answers "what did the agent do?" after the fact, and is what
replay_session re-runs on another script.
"""

import json
import os
import threading
import time

from .constants import JOURNAL_KEEP_FILES
from .util import temp_dir

_lock = threading.Lock()
_path = None


def path():
    global _path
    if _path is None:
        folder = temp_dir("sessions")
        stamp = time.strftime("%Y%m%d_%H%M%S")
        _path = os.path.join(folder, "%s_%d.jsonl" % (stamp, os.getpid()))
        _prune(folder)
    return _path


def _prune(folder):
    try:
        files = sorted(
            (os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".jsonl")),
            key=os.path.getmtime,
        )
        for old in files[:-JOURNAL_KEEP_FILES]:
            os.remove(old)
    except OSError:
        pass


def record(command, params, status, elapsed_ms, error=None, script=None):
    entry = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "command": command,
        "params": _shorten(params),
        "status": status,
        "elapsed_ms": elapsed_ms,
    }
    if error:
        entry["error"] = error
    if script:
        entry["script"] = script
    line = json.dumps(entry, default=str)
    with _lock:
        try:
            with open(path(), "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def read(last_n=50, file_path=None):
    target = file_path or path()
    if not os.path.exists(target):
        return []
    with open(target, encoding="utf-8") as fh:
        lines = fh.readlines()
    out = []
    for line in lines[-int(last_n):] if last_n else lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _shorten(params, limit=4000):
    try:
        text = json.dumps(params, default=str)
    except (TypeError, ValueError):
        return str(params)[:limit]
    if len(text) <= limit:
        return params
    return {"_truncated_json": text[:limit]}
