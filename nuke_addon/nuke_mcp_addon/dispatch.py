"""Command registry and the single entry point that runs a command.

``run_command`` is what the socket server hands to Nuke's main thread. It never
raises: ``nuke.executeInMainThreadWithResult`` swallows exceptions and returns
None, which would look like a silent success to the caller.

Commands that change the script run inside a labelled undo transaction. When
they fail (by exception or by returning an error) the transaction is cancelled,
so a half-finished operation never stays in the user's script.
"""

import os
import time
import traceback

from . import journal, registry
from .undo import Transaction
from .util import CommandError, get_nuke, jsonable

COMMANDS = {}
META = {}


def command(name, undo=False, journal=None, label=None, atomic=True):
    """Register a handler.

    Handlers take a params dict and return a value (wrapped as the result) or a
    legacy {"status": ..., ...} envelope, and raise CommandError for user-facing
    failures.

    undo:    run inside a labelled undo transaction (rolled back on failure).
    journal: record the call in the session journal (defaults to ``undo``).
    """

    def decorator(fn):
        COMMANDS[name] = fn
        META[name] = {
            "undo": undo,
            "journal": undo if journal is None else journal,
            "label": label or name,
            "atomic": atomic,
        }
        return fn

    return decorator


class _ReturnedError(Exception):
    def __init__(self, response):
        super().__init__(response.get("error"))
        self.response = response


def _normalize(value):
    if isinstance(value, dict) and value.get("status") in ("ok", "error"):
        return value
    return {"status": "ok", "result": value}


def _current_script():
    try:
        name = get_nuke().root().name()
    except Exception:
        return registry.script_name()
    return "" if name == "Root" else name  # unsaved script


def run_command(name, params=None):
    started = time.perf_counter()
    handler = COMMANDS.get(name)
    if handler is None:
        return {"status": "error", "error": "Unknown command: %s" % name}
    meta = META[name]
    params = params or {}
    atomic = meta["atomic"] and params.get("atomic", True)
    txn = Transaction(meta["label"], atomic=atomic,
                      enabled=meta["undo"] and params.get("undo_group", True))
    try:
        with txn:
            response = _normalize(handler(params))
            if response.get("status") == "error" and txn.enabled and atomic:
                raise _ReturnedError(response)
    except _ReturnedError as e:
        response = e.response
    except CommandError as e:
        response = {"status": "error", "error": str(e)}
    except Exception as e:
        response = {
            "status": "error",
            "error": "%s: %s" % (type(e).__name__, e),
            "traceback": traceback.format_exc(limit=8),
        }
    if txn.rolled_back:
        response["rolled_back"] = True

    # Only guarantee serializability here; size limits are each handler's call
    # (images travel as large base64 strings).
    response = jsonable(response, max_items=1000000, max_str=1 << 30)
    elapsed = int((time.perf_counter() - started) * 1000)
    response["elapsed_ms"] = elapsed

    script = _current_script()
    if script != registry.script_name():
        registry.update(script=script)
    if meta["journal"]:
        response["session"] = {"pid": os.getpid(), "script": script}
        journal.record(name, params, response.get("status"), elapsed,
                       response.get("error"), script)
    return response
