"""Handlers carried over from the original addon (script, project, render,
search, batch, toolsets, trackers, CopyCat, annotations, events)."""

import os

from .. import events
from ..dispatch import command
from ..util import CommandError, get_nuke, require_node


# -- script & project -------------------------------------------------------

@command("load_script", journal=True)
def load_script(params):
    nuke = get_nuke()
    path = params["path"]
    if not os.path.isfile(path):
        raise CommandError("File not found: %s" % path)
    if params.get("dry_run"):
        root = nuke.root()
        return {"would_open": path, "current": root.name(),
                "current_modified": bool(root.modified()) if hasattr(root, "modified") else None}
    nuke.scriptOpen(path)
    return {"loaded": path, "node_count": len(nuke.allNodes())}


@command("merge_script", undo=True)
def merge_script(params):
    """Import the nodes of another .nk into the current script."""
    nuke = get_nuke()
    path = params["path"]
    if not os.path.isfile(path):
        raise CommandError("File not found: %s" % path)
    before = {n.fullName() for n in nuke.allNodes()}
    nuke.nodePaste(path)
    added = sorted({n.fullName() for n in nuke.allNodes()} - before)
    return {"merged": path, "added": added}


@command("save_script", journal=True)
def save_script(params):
    nuke = get_nuke()
    path = params.get("path")
    if path:
        nuke.scriptSaveAs(path, overwrite=1 if params.get("overwrite") else 0)
    else:
        nuke.scriptSave()
        path = nuke.root().name()
    return {"saved": path}


@command("set_project_settings", undo=True)
def set_project_settings(params):
    nuke = get_nuke()
    root = nuke.root()
    modified = []
    if "fps" in params:
        root["fps"].setValue(float(params["fps"]))
        modified.append("fps")
    if "colorspace" in params:
        root["colorManagement"].setValue(params["colorspace"])
        modified.append("colorspace")
    if "resolution" in params:
        w, h = params["resolution"]
        fmt = nuke.addFormat("%d %d nuke_mcp_%dx%d" % (w, h, w, h))
        root["format"].setValue(fmt)
        modified.append("resolution")
    return {"modified": modified}


@command("set_frame_range", undo=True)
def set_frame_range(params):
    nuke = get_nuke()
    first, last = int(params["first"]), int(params["last"])
    if first > last:
        raise CommandError("first (%d) must be <= last (%d)" % (first, last))
    root = nuke.root()
    root["first_frame"].setValue(first)
    root["last_frame"].setValue(last)
    return {"first_frame": first, "last_frame": last}


@command("set_proxy_mode", undo=True)
def set_proxy_mode(params):
    get_nuke().root()["proxy"].setValue(bool(params["enabled"]))
    return {"proxy_mode": bool(params["enabled"])}


@command("render_frames", journal=True)
def render_frames(params):
    """Blocking render. Prefer render_start for anything longer than a few frames."""
    nuke = get_nuke()
    node = require_node(params["write_node"])
    root = nuke.root()
    first = int(params.get("first_frame", root["first_frame"].value()))
    last = int(params.get("last_frame", root["last_frame"].value()))
    nuke.execute(node, first, last)
    return {"rendered": node.fullName(), "first_frame": first, "last_frame": last}


# -- search -------------------------------------------------------------------

@command("find_nodes_by_type")
def find_nodes_by_type(params):
    nuke = get_nuke()
    cls = params["node_class"]
    nodes = nuke.allNodes(recurseGroups=bool(params.get("recurse_groups", False)))
    if cls != "*":
        # Match the exact class, or the class without its version suffix
        # (asking for "Axis" also finds Axis2/Axis3/Axis4 and vice versa).
        base = cls.rstrip("0123456789")
        nodes = [n for n in nodes
                 if n.Class() == cls or n.Class().rstrip("0123456789") == base]
    return {"nodes": [{"name": n.fullName(), "class": n.Class()} for n in nodes]}


@command("find_broken_reads")
def find_broken_reads(params):
    nuke = get_nuke()
    broken = []
    for node in nuke.allNodes("Read", recurseGroups=True):
        path = node["file"].value()
        if not path or node.hasError():
            broken.append({"name": node.fullName(), "file": path,
                           "error": node.error() if node.hasError() else "empty path"})
    return {"broken_reads": broken}


@command("find_error_nodes")
def find_error_nodes(params):
    nuke = get_nuke()
    errors = []
    for node in nuke.allNodes(recurseGroups=bool(params.get("recurse_groups", True))):
        if node.hasError():
            errors.append({"name": node.fullName(), "class": node.Class(),
                           "error": node.error()})
    return {"nodes": errors}


# -- batch --------------------------------------------------------------------

@command("batch_set_knob", undo=True)
def batch_set_knob(params):
    knob, value = params["knob_name"], params["value"]
    modified, skipped = [], []
    for name in params["node_names"]:
        node = require_node(name)
        if knob in node.knobs():
            node[knob].setValue(value)
            modified.append(node.fullName())
        else:
            skipped.append(node.fullName())
    return {"modified": modified, "skipped_no_knob": skipped, "knob": knob}


@command("batch_reconnect", undo=True)
def batch_reconnect(params):
    source = require_node(params["new_input"])
    index = int(params.get("input_index", 0))
    done = []
    for name in params["node_names"]:
        node = require_node(name)
        node.setInput(index, source)
        done.append(node.fullName())
    return {"reconnected": done}


# -- toolsets & live groups ---------------------------------------------------

@command("list_toolsets")
def list_toolsets(params):
    folder = os.path.join(os.path.expanduser("~"), ".nuke", "ToolSets")
    names = []
    if os.path.isdir(folder):
        for base, _dirs, files in os.walk(folder):
            for f in files:
                if f.endswith(".nk"):
                    rel = os.path.relpath(os.path.join(base, f), folder)
                    names.append(rel[:-3].replace(os.sep, "/"))
    return {"toolsets": sorted(names)}


@command("load_toolset", undo=True)
def load_toolset(params):
    nuke = get_nuke()
    name = params["name"]
    path = name if name.endswith(".nk") else os.path.join(
        os.path.expanduser("~"), ".nuke", "ToolSets", name + ".nk")
    if not os.path.isfile(path):
        raise CommandError("Toolset not found: %s" % path)
    nuke.loadToolset(path)
    return {"loaded": path}


@command("save_toolset", journal=True)
def save_toolset(params):
    nuke = get_nuke()
    nodes = [require_node(n) for n in params["node_names"]]
    previous = nuke.selectedNodes()
    for n in nuke.allNodes():
        n.setSelected(False)
    for n in nodes:
        n.setSelected(True)
    folder = os.path.join(os.path.expanduser("~"), ".nuke", "ToolSets")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, params["name"] + ".nk")
    nuke.nodeCopy(path)
    for n in nodes:
        n.setSelected(False)
    for n in previous:
        n.setSelected(True)
    return {"saved": path, "nodes": [n.fullName() for n in nodes]}


@command("create_live_group", undo=True)
def create_live_group(params):
    nuke = get_nuke()
    nodes = [require_node(n) for n in params["node_names"]]
    for n in nuke.allNodes():
        n.setSelected(False)
    for n in nodes:
        n.setSelected(True)
    lg = nuke.collapseToLiveGroup() if hasattr(nuke, "collapseToLiveGroup") \
        else nuke.createNode("LiveGroup", inpanel=False)
    lg.setName(params["name"])
    if params.get("file_path"):
        lg["file"].setValue(params["file_path"])
    return {"name": lg.fullName(), "nodes": [n.name() for n in nodes]}


# -- trackers & ML --------------------------------------------------------------

@command("create_tracker", undo=True)
def create_tracker(params):
    nuke = get_nuke()
    source = require_node(params["source_node"])
    tracker = nuke.nodes.Tracker4(inputs=[source])
    if params.get("name"):
        tracker.setName(params["name"])
    nuke.autoplace(tracker)
    return {"name": tracker.fullName(), "class": "Tracker4", "source": source.fullName()}


@command("solve_tracker", journal=True)
def solve_tracker(params):
    nuke = get_nuke()
    node = require_node(params["tracker_node"])
    root = nuke.root()
    first = int(params.get("first_frame", root["first_frame"].value()))
    last = int(params.get("last_frame", root["last_frame"].value()))
    if node.Class() == "Tracker4":
        # Tracker4 tracks through its own button, not nuke.execute.
        node["track_all_forward"].execute() if "track_all_forward" in node.knobs() else \
            nuke.execute(node, first, last)
    else:
        nuke.execute(node, first, last)
    return {"solved": node.fullName(), "frames": [first, last]}


@command("setup_stabilize", undo=True)
def setup_stabilize(params):
    source = require_node(params["source_node"])
    tracker = require_node(params["tracker_node"])
    tracker["transform"].setValue("stabilize")
    tracker.setInput(0, source)
    return {"name": tracker.fullName(), "source": source.fullName()}


@command("create_camera_tracker", undo=True)
def create_camera_tracker(params):
    nuke = get_nuke()
    source = require_node(params["source_node"])
    ct = nuke.nodes.CameraTracker(inputs=[source])
    if params.get("name"):
        ct.setName(params["name"])
    nuke.autoplace(ct)
    return {"name": ct.fullName(), "class": "CameraTracker", "source": source.fullName()}


@command("train_copycat", journal=True)
def train_copycat(params):
    node = require_node(params["copycat_node"])
    epochs = int(params.get("epochs", 1000))
    for knob in ("epochs", "numIterations"):
        if knob in node.knobs():
            node[knob].setValue(epochs)
            break
    for button in ("startTraining", "trainButton", "train"):
        if button in node.knobs():
            node[button].execute()
            return {"training": node.fullName(), "epochs": epochs, "button": button}
    raise CommandError("No training button found on %s" % node.fullName())


# -- annotations --------------------------------------------------------------

@command("create_annotation", undo=True)
def create_annotation(params):
    nuke = get_nuke()
    note = nuke.nodes.StickyNote(label=params["text"])
    if params.get("name"):
        note.setName(params["name"])
    if params.get("position"):
        note.setXYpos(int(params["position"][0]), int(params["position"][1]))
    if params.get("color"):
        r, g, b = params["color"]
        note["tile_color"].setValue(int(r * 255) << 24 | int(g * 255) << 16 | int(b * 255) << 8 | 255)
    return {"name": note.fullName(), "text": params["text"]}


@command("list_annotations")
def list_annotations(params):
    nuke = get_nuke()
    notes = [{"name": n.fullName(), "text": n["label"].value()}
             for n in nuke.allNodes("StickyNote", recurseGroups=True)]
    return {"annotations": notes}


# -- events -----------------------------------------------------------------------

_registered = set()


def _on_node_created():
    node = get_nuke().thisNode()
    events.push("node_created", {"name": node.fullName(), "class": node.Class()})


def _on_node_destroyed():
    node = get_nuke().thisNode()
    events.push("node_deleted", {"name": node.fullName(), "class": node.Class()})


def _on_knob_changed():
    nuke = get_nuke()
    knob = nuke.thisKnob()
    if knob is not None:
        events.push("knob_changed", {"node": nuke.thisNode().fullName(), "knob": knob.name()})


def _on_script_loaded():
    events.push("script_loaded", {"script": get_nuke().root().name()})


def _on_script_saved():
    events.push("script_saved", {"script": get_nuke().root().name()})


@command("subscribe_events")
def subscribe_events(params):
    nuke = get_nuke()
    hooks = {
        "node_created": (nuke.addOnCreate, _on_node_created),
        "node_deleted": (nuke.addOnDestroy, _on_node_destroyed),
        "knob_changed": (nuke.addKnobChanged, _on_knob_changed),
        "script_loaded": (nuke.addOnScriptLoad, _on_script_loaded),
        "script_saved": (nuke.addOnScriptSave, _on_script_saved),
    }
    subscribed = []
    for name in params.get("event_types", []):
        if name not in hooks:
            continue
        if name not in _registered:
            add, fn = hooks[name]
            add(fn)
            _registered.add(name)
        subscribed.append(name)
    return {"subscribed": subscribed}
