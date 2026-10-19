"""Viewer and timeline control."""

from ..dispatch import command
from ..util import CommandError, get_nuke, require_node


def _viewer():
    nuke = get_nuke()
    viewer = nuke.activeViewer() if hasattr(nuke, "activeViewer") else None
    if viewer is None:
        raise CommandError("No active Viewer (open one in the GUI first)")
    return viewer


@command("get_viewer_info")
def get_viewer_info(params):
    nuke = get_nuke()
    viewer = _viewer()
    node = viewer.node()
    info = {
        "viewer": node.fullName(),
        "frame": int(nuke.frame()),
        "active_input": viewer.activeInput(),
        "inputs": [(node.input(i).fullName() if node.input(i) else None)
                   for i in range(node.inputs())],
    }
    for knob in ("viewerProcess", "monitorOutOutputTransform", "gain", "gamma", "channels",
                 "input_process", "frame_range"):
        if knob in node.knobs():
            try:
                info[knob] = node[knob].value()
            except Exception:
                pass
    return info


@command("set_viewer_input", undo=True)
def set_viewer_input(params):
    viewer = _viewer()
    node = viewer.node()
    target = require_node(params["node_name"])
    index = int(params.get("input_index", 0))
    node.setInput(index, target)
    viewer.activateInput(index)
    return {"viewer": node.fullName(), "input_index": index, "showing": target.fullName()}


@command("set_current_frame")
def set_current_frame(params):
    nuke = get_nuke()
    nuke.frame(int(params["frame"]))
    return {"frame": int(nuke.frame())}


@command("zoom_to_node")
def zoom_to_node(params):
    nuke = get_nuke()
    node = require_node(params["node_name"])
    scale = float(params.get("scale", 1.0))
    nuke.zoom(scale, [node.xpos() + node.screenWidth() / 2, node.ypos() + node.screenHeight() / 2])
    return {"centered_on": node.fullName(), "scale": scale}


@command("viewer_playback")
def viewer_playback(params):
    nuke = get_nuke()
    viewer = _viewer()
    action = params["action"]
    if action == "play":
        viewer.play(1)
    elif action == "backward":
        viewer.play(-1)
    elif action == "stop":
        viewer.stop()
    elif action in ("next", "prev"):
        nuke.frame(int(nuke.frame()) + (1 if action == "next" else -1))
    elif action == "goto":
        nuke.frame(int(params["frame"]))
    else:
        raise CommandError("action must be play, backward, stop, next, prev or goto")
    return {"action": action, "frame": int(nuke.frame())}
