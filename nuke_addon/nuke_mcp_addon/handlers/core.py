"""Script info and basic node graph editing."""

from ..dispatch import command
from ..util import CommandError, get_nuke, jsonable, require_node

# Knobs that are pure UI furniture and only add noise to a node dump.
_NOISE_CLASSES = {"Tab_Knob", "Text_Knob", "PyScript_Knob", "Script_Knob", "Help_Knob",
                  "Obsolete_Knob", "BeginTabGroup_Knob", "EndTabGroup_Knob"}


def _format_dict(fmt):
    return {"name": fmt.name() or "", "width": fmt.width(), "height": fmt.height(),
            "pixel_aspect": fmt.pixelAspect()}


@command("ping")
def ping(params):
    return "pong"


@command("get_script_info")
def get_script_info(params):
    nuke = get_nuke()
    root = nuke.root()
    info = {
        "name": root.name(),
        "modified": bool(root.modified()) if hasattr(root, "modified") else None,
        "frame_range": [int(root["first_frame"].value()), int(root["last_frame"].value())],
        "current_frame": int(nuke.frame()),
        "fps": root["fps"].value(),
        "format": _format_dict(root.format()),
        "proxy": bool(root["proxy"].value()) if "proxy" in root.knobs() else None,
        "colorspace": root["colorManagement"].value() if "colorManagement" in root.knobs() else None,
        "node_count": len(nuke.allNodes(recurseGroups=True)),
        "selected": [n.fullName() for n in nuke.selectedNodes()],
    }
    for key in ("OCIO_config", "customOCIOConfigPath", "workingSpaceLUT", "monitorLut",
                "int8Lut", "int16Lut", "logLut", "floatLut"):
        if key in root.knobs():
            try:
                info.setdefault("color", {})[key] = root[key].value()
            except Exception:
                pass
    try:
        info["views"] = list(nuke.views())
    except Exception:
        pass
    return info


def _knob_entry(knob, max_chars):
    entry = {}
    try:
        value = knob.value()
    except Exception:
        try:
            value = knob.toScript()
        except Exception:
            value = "<unavailable>"
    value = jsonable(value, max_str=max_chars, max_items=64)
    text = str(value)
    if len(text) > max_chars:
        value = text[:max_chars] + "...[truncated, %d chars]" % len(text)
    entry["value"] = value
    try:
        if knob.isAnimated():
            entry["animated"] = True
    except Exception:
        pass
    try:
        if knob.hasExpression():
            entry["expression"] = knob.toScript()
    except Exception:
        pass
    return entry


@command("get_node_info")
def get_node_info(params):
    nuke = get_nuke()
    node = require_node(params["node_name"])
    wanted = params.get("knobs")
    non_default_only = params.get("non_default_only", False)
    max_chars = int(params.get("max_value_chars", 500))
    knobs = {}
    skipped = 0
    for name, knob in node.knobs().items():
        if wanted and name not in wanted:
            continue
        if not wanted:
            if knob.Class() in _NOISE_CLASSES:
                continue
            if non_default_only:
                try:
                    if not knob.notDefault():
                        skipped += 1
                        continue
                except Exception:
                    pass
        knobs[name] = _knob_entry(knob, max_chars)
    is_root = node is nuke.root()
    result = {"name": "Root" if is_root else node.fullName(), "class": node.Class(),
              "knobs": knobs}
    if non_default_only:
        result["default_knobs_skipped"] = skipped
    if not is_root:
        result.update({
            "xpos": node.xpos(),
            "ypos": node.ypos(),
            "inputs": [(node.input(i).fullName() if node.input(i) else None)
                       for i in range(node.inputs())],
            "outputs": sorted({d.fullName() for d in node.dependent(nuke.INPUTS | nuke.HIDDEN_INPUTS, False)})
            if hasattr(nuke, "INPUTS") else [],
            "disabled": bool(node["disable"].value()) if "disable" in node.knobs() else False,
        })
        if node.hasError():
            result["error"] = node.error() if hasattr(node, "error") else True
        try:
            result["frame_range"] = [node.firstFrame(), node.lastFrame()]
            result["format"] = _format_dict(node.format())
        except Exception:
            pass
    return result


def _apply_knobs(node, knobs):
    """Set knob values; returns {knob: error} for the ones that failed."""
    errors = {}
    for name, value in (knobs or {}).items():
        if name not in node.knobs():
            errors[name] = "no such knob on %s (%s)" % (node.fullName(), node.Class())
            continue
        try:
            knob = node[name]
            if isinstance(value, (list, tuple)) and hasattr(knob, "setValue"):
                try:
                    knob.setValue(list(value))
                except Exception:
                    for i, v in enumerate(value):
                        knob.setValue(v, i)
            else:
                knob.setValue(value)
        except Exception as e:
            errors[name] = "%s: %s" % (type(e).__name__, e)
    return errors


@command("create_node", undo=True)
def create_node(params):
    nuke = get_nuke()
    node_class = params["node_class"]
    if params.get("connect_to_selected"):
        node = nuke.createNode(node_class, inpanel=False)
    else:
        factory = getattr(nuke.nodes, node_class, None)
        if factory is None:
            raise CommandError("Unknown node class '%s'" % node_class)
        node = factory()
    if params.get("name"):
        node.setName(params["name"])
    errors = _apply_knobs(node, params.get("knobs"))
    if errors and params.get("strict", True):
        raise CommandError("Could not set knobs: %s" % errors)
    for index, input_name in enumerate(params.get("inputs") or []):
        if input_name:
            node.setInput(index, require_node(input_name))
    position = params.get("position")
    if position:
        node.setXYpos(int(position[0]), int(position[1]))
    elif not params.get("connect_to_selected"):
        nuke.autoplace(node)
    result = {"name": node.fullName(), "class": node.Class(), "xpos": node.xpos(),
              "ypos": node.ypos()}
    if errors:
        result["knob_errors"] = errors
    return result


@command("modify_node", undo=True)
def modify_node(params):
    node = require_node(params["node_name"])
    knobs = params["knobs"]
    missing = [k for k in knobs if k not in node.knobs()]
    if missing:
        raise CommandError("Knob(s) %s not found on node '%s'" % (missing, node.fullName()))
    errors = _apply_knobs(node, knobs)
    if errors:
        raise CommandError("Could not set knobs: %s" % errors)
    return {"name": node.fullName(), "modified_knobs": list(knobs)}


@command("delete_node", undo=True)
def delete_node(params):
    nuke = get_nuke()
    node = require_node(params["node_name"])
    info = {"deleted": node.fullName(), "class": node.Class()}
    nuke.delete(node)
    return info


@command("connect_nodes", undo=True)
def connect_nodes(params):
    out_node = require_node(params["output_node"])
    in_node = require_node(params["input_node"])
    index = int(params.get("input_index", 0))
    if index >= in_node.maxInputs() and in_node.maxInputs() >= 0:
        raise CommandError("%s accepts at most %d inputs" % (in_node.fullName(), in_node.maxInputs()))
    in_node.setInput(index, out_node)
    return {"output": out_node.fullName(), "input": in_node.fullName(), "input_index": index}


@command("disconnect_input", undo=True)
def disconnect_input(params):
    node = require_node(params["node_name"])
    index = int(params.get("input_index", 0))
    previous = node.input(index)
    node.setInput(index, None)
    return {"node": node.fullName(), "input_index": index,
            "was": previous.fullName() if previous else None}


@command("position_node", undo=True)
def position_node(params):
    node = require_node(params["node_name"])
    node.setXYpos(int(params["x"]), int(params["y"]))
    return {"name": node.fullName(), "xpos": node.xpos(), "ypos": node.ypos()}


@command("auto_layout", undo=True)
def auto_layout(params):
    nuke = get_nuke()
    names = params.get("node_names")
    nodes = [require_node(n) for n in names] if names else nuke.allNodes()
    if not nodes:
        raise CommandError("No nodes to lay out")
    for n in nodes:
        nuke.autoplace(n)
    return {"laid_out": len(nodes)}


@command("select_nodes", undo=False)
def select_nodes(params):
    nuke = get_nuke()
    if not params.get("additive", False):
        for n in nuke.selectedNodes():
            n.setSelected(False)
    names = params.get("node_names") or []
    for name in names:
        require_node(name).setSelected(True)
    return {"selected": [n.fullName() for n in nuke.selectedNodes()]}


@command("duplicate_node", undo=True)
def duplicate_node(params):
    """Copy a node through a temp .nk file (never touches the user's clipboard)."""
    import os
    from ..util import temp_dir
    nuke = get_nuke()
    node = require_node(params["node_name"])
    path = os.path.join(temp_dir("clip"), "duplicate.nk")
    previous = nuke.selectedNodes()
    for n in previous:
        n.setSelected(False)
    node.setSelected(True)
    nuke.nodeCopy(path)
    node.setSelected(False)
    nuke.nodePaste(path)
    copy = nuke.selectedNodes()[0]
    copy.setXYpos(node.xpos() + int(params.get("x_offset", 100)),
                  node.ypos() + int(params.get("y_offset", 0)))
    for n in nuke.selectedNodes():
        n.setSelected(False)
    for n in previous:
        n.setSelected(True)
    return {"original": node.fullName(), "copy": copy.fullName()}
