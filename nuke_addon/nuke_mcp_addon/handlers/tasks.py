"""Long jobs that must not freeze the conversation: async renders.

A worker thread renders one frame at a time, hopping to Nuke's main thread for
each frame. Between frames Nuke stays responsive, status can be polled and the
job can be cancelled. Being a real render, the user's render callbacks fire.
"""

import threading
import time
import uuid

from ..dispatch import command
from ..util import CommandError, get_nuke, require_node

_tasks = globals().get("_tasks") or {}  # running renders survive a hot reload
_lock = globals().get("_lock") or threading.Lock()


def _public(task):
    t = {k: v for k, v in task.items() if not k.startswith("_")}
    done = t["frames_done"]
    total = t["frames_total"]
    elapsed = (t.get("finished") or time.time()) - t["started"]
    t["elapsed_s"] = round(elapsed, 1)
    if done and t["state"] == "running":
        t["eta_s"] = round(elapsed / done * (total - done), 1)
    t["progress"] = round(100.0 * done / total, 1) if total else 100.0
    return t


def _render_one(write_names, frame):
    """Runs on the main thread. Returns None on success or an error string:
    executeInMainThreadWithResult swallows exceptions, so they must not escape."""
    try:
        nuke = get_nuke()
        nodes = [nuke.toNode(n) for n in write_names]
        if len(nodes) == 1:
            nuke.execute(nodes[0], frame, frame)
        else:
            nuke.executeMultiple(nodes, ((frame, frame, 1),))
        return None
    except Exception as e:
        return "%s: %s" % (type(e).__name__, e)


def _worker(task_id):
    from ..server import call_main

    task = _tasks[task_id]
    for frame in task["_frames"]:
        if task["_cancel"].is_set():
            task["state"] = "cancelled"
            break
        task["current_frame"] = frame
        try:
            error = call_main(_render_one, task["write_nodes"], frame)
        except Exception as e:
            error = "%s: %s" % (type(e).__name__, e)
        if error is None:
            task["frames_done"] += 1
            continue
        task["failed_frames"].append({"frame": frame, "error": error})
        if not task["continue_on_error"]:
            task["state"] = "failed"
            break
    else:
        task["state"] = "completed_with_errors" if task["failed_frames"] else "completed"
    task["finished"] = time.time()
    task["current_frame"] = None


@command("render_start", journal=True)
def render_start(params):
    nuke = get_nuke()
    names = params.get("write_nodes") or [params["write_node"]]
    nodes = [require_node(n) for n in names]
    for n in nodes:
        if n.Class() not in ("Write", "WriteGeo", "DeepWrite", "WriteTank") and "file" not in n.knobs():
            raise CommandError("%s is not a Write-type node" % n.fullName())
        if n.hasError():
            raise CommandError("%s has an error: %s" % (n.fullName(), n.error()))
    root = nuke.root()
    first = int(params.get("first_frame", root["first_frame"].value()))
    last = int(params.get("last_frame", root["last_frame"].value()))
    step = max(1, int(params.get("step", 1)))
    frames = list(range(first, last + 1, step))
    task_id = uuid.uuid4().hex[:8]
    task = {
        "task_id": task_id, "kind": "render", "state": "running",
        "write_nodes": [n.fullName() for n in nodes],
        "frame_range": [first, last, step], "frames_total": len(frames), "frames_done": 0,
        "current_frame": None, "failed_frames": [], "started": time.time(), "finished": None,
        "continue_on_error": bool(params.get("continue_on_error", False)),
        "_frames": frames, "_cancel": threading.Event(),
    }
    with _lock:
        _tasks[task_id] = task
    threading.Thread(target=_worker, args=(task_id,), name="nuke-mcp-render-" + task_id,
                     daemon=True).start()
    return _public(task)


@command("task_status")
def task_status(params):
    task = _tasks.get(params["task_id"])
    if task is None:
        raise CommandError("Unknown task '%s'" % params["task_id"])
    return _public(task)


@command("task_cancel", journal=True)
def task_cancel(params):
    task = _tasks.get(params["task_id"])
    if task is None:
        raise CommandError("Unknown task '%s'" % params["task_id"])
    task["_cancel"].set()
    return {"task_id": task["task_id"], "cancelling": task["state"] == "running"}


@command("list_tasks")
def list_tasks(params):
    with _lock:
        tasks = [_public(t) for t in _tasks.values()]
    return {"tasks": sorted(tasks, key=lambda t: -t["started"])}
