"""Read-only inspection: graph, errors, metadata, channels, classes, digests."""

import glob
import hashlib
import os
import re

from .. import hooks
from ..dispatch import command
from ..undo import undo_disabled
from ..util import CommandError, get_nuke, jsonable, require_node


def _nodes(params):
    nuke = get_nuke()
    nodes = nuke.allNodes(recurseGroups=bool(params.get("recurse_groups", False)))
    cls = params.get("filter_class")
    if cls:
        nodes = [n for n in nodes if n.Class() == cls]
    return nodes


@command("get_node_graph")
def get_node_graph(params):
    nuke = get_nuke()
    nodes = _nodes(params)
    limit = int(params.get("max_nodes", 500))
    out = []
    for node in nodes[:limit]:
        entry = {
            "name": node.fullName(),
            "class": node.Class(),
            "pos": [node.xpos(), node.ypos()],
            "inputs": [(node.input(i).fullName() if node.input(i) else None)
                       for i in range(node.inputs())],
        }
        if node.isSelected():
            entry["selected"] = True
        if "disable" in node.knobs() and node["disable"].value():
            entry["disabled"] = True
        if node.hasError():
            entry["error"] = True
        label = node["label"].value() if "label" in node.knobs() else ""
        if label:
            entry["label"] = label
        out.append(entry)
    outputs = {}
    for entry in out:
        for src in entry["inputs"]:
            if src:
                outputs.setdefault(src, []).append(entry["name"])
    for entry in out:
        entry["outputs"] = outputs.get(entry["name"], [])
    result = {"nodes": out, "count": len(nodes)}
    if len(nodes) > limit:
        result["truncated"] = True
    viewer = nuke.activeViewer() if hasattr(nuke, "activeViewer") else None
    if viewer is not None:
        result["active_viewer"] = viewer.node().fullName()
    return result


@command("get_selection")
def get_selection(params):
    nuke = get_nuke()
    return {"selected": [{"name": n.fullName(), "class": n.Class()} for n in nuke.selectedNodes()]}


@command("get_node_metadata")
def get_node_metadata(params):
    nuke = get_nuke()
    node = require_node(params["node_name"])
    frame = params.get("frame")
    meta = node.metadata("", int(frame)) if frame is not None else node.metadata()
    keys = params.get("keys")
    if keys:
        meta = {k: v for k, v in meta.items() if any(s.lower() in k.lower() for s in keys)}
    return {"node": node.fullName(), "frame": frame if frame is not None else nuke.frame(),
            "metadata": jsonable(meta, max_items=500)}


@command("list_channels")
def list_channels(params):
    node = require_node(params["node_name"])
    channels = node.channels()
    layers = {}
    for ch in channels:
        layer, _, comp = ch.partition(".")
        layers.setdefault(layer, []).append(comp)
    return {"node": node.fullName(), "layers": layers, "channel_count": len(channels)}


def _walk_menu(menu, path, out):
    for item in menu.items():
        name = item.name()
        if hasattr(item, "items"):
            _walk_menu(item, path + [name], out)
            continue
        script = item.script() if hasattr(item, "script") else ""
        match = re.search(r"""create(?:Node|NodeLocal)\(\s*['"]([A-Za-z0-9_]+)['"]""", script or "")
        if match:
            out.append({"class": match.group(1), "label": name, "menu": "/".join(path)})


@command("list_node_classes")
def list_node_classes(params):
    nuke = get_nuke()
    found = []
    _walk_menu(nuke.menu("Nodes"), [], found)
    category = (params.get("category") or "").lower()
    if category:
        found = [f for f in found if category in f["menu"].lower()]
    contains = (params.get("contains") or "").lower()
    if contains:
        found = [f for f in found if contains in f["class"].lower() or contains in f["label"].lower()]
    by_class = {}
    for f in found:
        by_class.setdefault(f["class"], f)
    return {"classes": sorted(by_class.values(), key=lambda f: (f["menu"], f["class"])),
            "count": len(by_class)}


@command("get_node_default_knobs")
def get_node_default_knobs(params):
    """Create a throw-away node, read its knobs, roll it back. Leaves no trace."""
    nuke = get_nuke()
    cls = params["node_class"]
    factory = getattr(nuke.nodes, cls, None)
    if factory is None:
        raise CommandError("Unknown node class '%s'" % cls)
    knobs = {}
    with hooks.suspended(hooks.CREATE_DESTROY), undo_disabled():
        node = factory()
        for name, knob in node.knobs().items():
            if knob.Class() in ("Tab_Knob", "Text_Knob", "PyScript_Knob", "Script_Knob"):
                continue
            try:
                knobs[name] = {"class": knob.Class(), "default": jsonable(knob.value(), max_items=32)}
            except Exception:
                knobs[name] = {"class": knob.Class()}
        nuke.delete(node)
    return {"node_class": cls, "knobs": knobs}


# -- digest / delta ------------------------------------------------------------

_snapshots = {}


def _node_signature(node):
    try:
        body = node.writeKnobs(get_nuke().WRITE_NON_DEFAULT_ONLY | get_nuke().TO_SCRIPT)
    except Exception:
        body = ""
    inputs = ",".join((node.input(i).fullName() if node.input(i) else "-")
                      for i in range(node.inputs()))
    return hashlib.sha1(("%s|%s|%s" % (node.Class(), inputs, body)).encode("utf-8")).hexdigest()[:12]


@command("scene_digest")
def scene_digest(params):
    """Compact overview of the script plus a token for scene_delta."""
    nuke = get_nuke()
    root = nuke.root()
    nodes = nuke.allNodes(recurseGroups=True)
    classes = {}
    for n in nodes:
        classes[n.Class()] = classes.get(n.Class(), 0) + 1
    reads = []
    for n in nodes:
        if n.Class() in ("Read", "DeepRead", "ReadGeo2", "ReadGeo", "Camera3", "Camera4"):
            entry = {"name": n.fullName(), "class": n.Class()}
            if "file" in n.knobs():
                entry["file"] = n["file"].value()
            if "colorspace" in n.knobs():
                entry["colorspace"] = n["colorspace"].value()
            if "raw" in n.knobs() and n["raw"].value():
                entry["raw"] = True
            if n.hasError():
                entry["error"] = n.error()
            reads.append(entry)
    writes = []
    for n in nuke.allNodes("Write", recurseGroups=True):
        writes.append({"name": n.fullName(), "file": n["file"].value(),
                       "file_type": n["file_type"].value() if "file_type" in n.knobs() else None,
                       "colorspace": n["colorspace"].value() if "colorspace" in n.knobs() else None,
                       "disabled": bool(n["disable"].value())})
    errors = [{"name": n.fullName(), "error": n.error()} for n in nodes if n.hasError()]
    signatures = {n.fullName(): _node_signature(n) for n in nodes}
    token = hashlib.sha1("".join(sorted(k + v for k, v in signatures.items())).encode()).hexdigest()[:10]
    _snapshots[token] = signatures
    return {
        "script": root.name(),
        "frame_range": [int(root["first_frame"].value()), int(root["last_frame"].value())],
        "fps": root["fps"].value(),
        "format": "%dx%d" % (root.format().width(), root.format().height()),
        "node_count": len(nodes),
        "classes": dict(sorted(classes.items(), key=lambda kv: -kv[1])),
        "sources": reads,
        "writes": writes,
        "errors": errors,
        "selected": [n.fullName() for n in nuke.selectedNodes()],
        "token": token,
    }


@command("scene_delta")
def scene_delta(params):
    """What changed since a scene_digest token: added, removed and edited nodes."""
    nuke = get_nuke()
    token = params["token"]
    before = _snapshots.get(token)
    if before is None:
        raise CommandError("Unknown token '%s' (tokens live until Nuke restarts)" % token)
    now = {n.fullName(): _node_signature(n) for n in nuke.allNodes(recurseGroups=True)}
    added = sorted(set(now) - set(before))
    removed = sorted(set(before) - set(now))
    changed = sorted(k for k in set(now) & set(before) if now[k] != before[k])
    new_token = hashlib.sha1("".join(sorted(k + v for k, v in now.items())).encode()).hexdigest()[:10]
    _snapshots[new_token] = now
    return {"added": added, "removed": removed, "changed": changed, "token": new_token}


# -- files ------------------------------------------------------------------------

_HASHES = re.compile(r"#+")
_PRINTF = re.compile(r"%0?(\d*)d")


def _frame_path(pattern, frame):
    def printf(m):
        width = int(m.group(1) or 1)
        return str(frame).zfill(width)
    path = _PRINTF.sub(printf, pattern)
    return _HASHES.sub(lambda m: str(frame).zfill(len(m.group(0))), path)


@command("find_missing_frames")
def find_missing_frames(params):
    """Check every frame of every Read on disk. Reports gaps per node."""
    nuke = get_nuke()
    names = params.get("node_names")
    nodes = [require_node(n) for n in names] if names else nuke.allNodes("Read", recurseGroups=True)
    max_frames = int(params.get("max_frames_per_node", 20000))
    report = []
    for node in nodes:
        pattern = node["file"].value() if "file" in node.knobs() else ""
        if not pattern:
            continue
        if not (_HASHES.search(pattern) or _PRINTF.search(pattern)):
            if not os.path.exists(pattern):
                report.append({"name": node.fullName(), "file": pattern, "missing": ["<file>"]})
            continue
        first, last = int(node["first"].value()), int(node["last"].value())
        missing = []
        for frame in range(first, min(last, first + max_frames - 1) + 1):
            if not os.path.exists(_frame_path(pattern, frame)):
                missing.append(frame)
        if missing:
            report.append({"name": node.fullName(), "file": pattern, "range": [first, last],
                           "missing_count": len(missing), "missing": _ranges(missing)})
    return {"nodes_checked": len(nodes), "with_missing_frames": report}


def _ranges(frames):
    out = []
    start = prev = frames[0]
    for f in frames[1:]:
        if f == prev + 1:
            prev = f
            continue
        out.append(str(start) if start == prev else "%d-%d" % (start, prev))
        start = prev = f
    out.append(str(start) if start == prev else "%d-%d" % (start, prev))
    return out


_PATH_KNOBS = ("file", "proxy", "vfield_file", "font")


@command("replace_filepaths", undo=True)
def replace_filepaths(params):
    """Search/replace in file knobs (Read, Write, ReadGeo, Camera, ...). dry_run by default."""
    nuke = get_nuke()
    find, replace = params["find"], params["replace"]
    use_regex = bool(params.get("regex", False))
    dry_run = params.get("dry_run", True)
    classes = params.get("node_classes")
    changes = []
    for node in nuke.allNodes(recurseGroups=True):
        if classes and node.Class() not in classes:
            continue
        for knob_name in _PATH_KNOBS:
            if knob_name not in node.knobs():
                continue
            old = node[knob_name].value()
            if not isinstance(old, str) or not old:
                continue
            new = re.sub(find, replace, old) if use_regex else old.replace(find, replace)
            if new != old:
                changes.append({"node": node.fullName(), "knob": knob_name, "old": old, "new": new})
                if not dry_run:
                    node[knob_name].setValue(new)
    return {"dry_run": dry_run, "changes": changes, "count": len(changes)}


@command("glob_files")
def glob_files(params):
    """List files on disk (e.g. to check a render folder) without leaving Nuke."""
    pattern = params["pattern"]
    files = sorted(glob.glob(pattern))
    limit = int(params.get("limit", 500))
    return {"pattern": pattern, "count": len(files), "files": files[:limit]}
