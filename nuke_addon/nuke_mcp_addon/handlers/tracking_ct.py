"""CameraTracker user tracks: list, import (headless-safe), export to Axis nodes,
and reprojection QC.

Gotchas these handlers encode (each one fails silently if ignored):
1. ``addUserTrack`` does nothing until the node's control panel has been built:
   call ``showControlPanel()`` first.
2. ``setValueAt`` on a table cell needs ``setAnimated(index)`` first, otherwise
   every write overwrites one static value.
3. ``setAnimated`` drops a stray key at the current frame: remove it unless it
   is one of the real keys. And close the panel before bulk writes: with it
   open, the table redraws on every write (minutes instead of seconds).
4. The Solve button has no Python entry point: solving stays in the GUI.

User-track data lives in the ``userTracks`` table: XY at indices (2,3) + 15*i,
solved XYZ at (9,10,11) + 15*i. They are addressed through linkableKnobs, as
Foundry's own importTracker does, instead of hard-coding the stride.
"""

import math
import re
import statistics

from ..dispatch import command
from ..util import CommandError, get_nuke, require_node


def _cameratracker(name):
    node = require_node(name)
    if node.Class() != "CameraTracker":
        raise CommandError("%s is a %s, not a CameraTracker" % (node.fullName(), node.Class()))
    return node


def _user_tracks(ct):
    nuke = get_nuke()
    xy = [k for k in ct.linkableKnobs(nuke.KnobType.eXYKnob) if len(k.indices()) == 2]
    xyz = {k.displayName(): k for k in ct.linkableKnobs(nuke.KnobType.eXYZKnob)
           if len(k.indices()) == 3}
    tracks = []
    for i, lk in enumerate(xy):
        name = lk.displayName()
        tracks.append({"index": i, "name": name, "xy": lk, "xyz": xyz.get(name)})
    return tracks


def _xyz_value(lk):
    table = lk.knob()
    return [table.getValue(int(j)) for j in lk.indices()]


def _key_range(lk):
    table = lk.knob()
    ix = int(lk.indices()[0])
    n = table.getNumKeys(ix)
    if n == 0:
        return 0, None
    return n, [table.getKeyTime(0, ix), table.getKeyTime(n - 1, ix)]


@command("cameratracker_list_user_tracks")
def cameratracker_list_user_tracks(params):
    ct = _cameratracker(params["node_name"])
    out = []
    for t in _user_tracks(ct):
        n_keys, rng = _key_range(t["xy"])
        entry = {"index": t["index"], "name": t["name"], "keys": n_keys, "range": rng}
        if t["xyz"] is not None:
            xyz = _xyz_value(t["xyz"])
            entry["xyz"] = [round(v, 6) for v in xyz]
            entry["solved"] = any(v != 0.0 for v in xyz)  # the origin point sits at ~1e-9
        out.append(entry)
    return {"node": ct.fullName(), "user_tracks": out, "count": len(out)}


@command("cameratracker_import_user_tracks", undo=True)
def cameratracker_import_user_tracks(params):
    """tracks: [{"keys": {frame: [x, y], ...}}, ...] in plate pixel coordinates.

    Returns the verified key count per new track (read back from the knob).
    The camera still has to be solved from the GUI (Solve has no Python hook).
    """
    nuke = get_nuke()
    ct = _cameratracker(params["node_name"])
    tracks = params["tracks"]
    ct.showControlPanel()  # gotcha 1
    before = len(_user_tracks(ct))
    for _ in tracks:
        ct["addUserTrack"].execute()
    created = _user_tracks(ct)[before:]
    ct.hideControlPanel()  # gotcha 3 (speed)
    if len(created) != len(tracks):
        raise CommandError("addUserTrack created %d tracks for %d requested"
                           % (len(created), len(tracks)))
    report = []
    current = nuke.frame()
    for spec, track in zip(tracks, created):
        lk = track["xy"]
        table = lk.knob()
        ix, iy = int(lk.indices()[0]), int(lk.indices()[1])
        keys = {float(f): v for f, v in spec["keys"].items()}
        table.clearAnimated(ix)
        table.clearAnimated(iy)
        table.setAnimated(ix)  # gotcha 2
        table.setAnimated(iy)
        for frame, (x, y) in keys.items():
            table.setValueAt(float(x), frame, ix)
            table.setValueAt(float(y), frame, iy)
        if float(current) not in keys:  # gotcha 3: stray key from setAnimated
            for idx in (ix, iy):
                try:
                    table.removeKeyAt(float(current), idx)
                except Exception:
                    pass
        written = table.getNumKeys(ix)
        report.append({"track": track["name"], "requested_keys": len(keys), "written_keys": written})
        if written != len(keys):
            raise CommandError("track %s: wrote %d keys, expected %d"
                               % (track["name"], written, len(keys)))
    return {"node": ct.fullName(), "imported": report,
            "next_step": "Press Solve in the CameraTracker panel (no Python entry point)."}


_CAMERA_CLASS = re.compile(r"^Camera\d*$")  # not CameraTracker / CameraTrackerPointCloud


def _find_camera(ct, wanted):
    nuke = get_nuke()
    if wanted:
        return require_node(wanted)
    cams = [n for n in nuke.allNodes(recurseGroups=True) if _CAMERA_CLASS.match(n.Class())]
    linked = []
    for cam in cams:
        for knob_name in ("translate", "rotate", "focal"):
            if knob_name in cam.knobs():
                try:
                    if ct.name() in cam[knob_name].toScript():
                        linked.append(cam)
                        break
                except Exception:
                    pass
    if len(linked) == 1:
        return linked[0]
    if len(cams) == 1:
        return cams[0]
    raise CommandError("Cannot tell which camera is the solve; pass camera_node "
                       "(candidates: %s)" % [c.fullName() for c in cams])


def _qc(ct, camera, pairs, n_frames):
    """Reproject each (track, xyz) through the camera; px error vs the 2D track."""
    import nukescripts.snap3d as snap3d

    nuke = get_nuke()
    root = nuke.root()
    first, last = int(root["first_frame"].value()), int(root["last_frame"].value())
    frames = sorted({int(round(first + (last - first) * a / max(1, n_frames - 1)))
                     for a in range(n_frames)})
    errors = {}
    current = nuke.frame()
    try:
        for f in frames:
            nuke.frame(f)
            for track, xyz in pairs:
                lk = track["xy"]
                table = lk.knob()
                ix, iy = int(lk.indices()[0]), int(lk.indices()[1])
                n = table.getNumKeys(ix)
                if n == 0 or not (table.getKeyTime(0, ix) <= f <= table.getKeyTime(n - 1, ix)):
                    continue
                p = next(snap3d.projectPoints(camera, (xyz,)))
                err = math.hypot(p.x - table.getValueAt(f, ix), p.y - table.getValueAt(f, iy))
                errors.setdefault(track["name"], []).append([f, round(err, 2)])
    finally:
        nuke.frame(current)
    flat = [e for v in errors.values() for _, e in v]
    summary = {}
    if flat:
        summary = {"median_px": round(statistics.median(flat), 2), "max_px": round(max(flat), 2),
                   "samples": len(flat)}
    return frames, errors, summary


@command("cameratracker_user_tracks_to_axes", undo=True)
def cameratracker_user_tracks_to_axes(params):
    """One Axis per solved user track, placed at its 3D position.

    The GUI's right-click 'create > axis' places ONE object at the average of
    the selection; this makes one per track. Tracks that already have an Axis
    at the same position are skipped, so it can finish a half-done export.
    verify=True reprojects every Axis through the solved camera and reports the
    pixel error against its 2D track.
    """
    nuke = get_nuke()
    ct = _cameratracker(params["node_name"])
    wanted = params.get("tracks")
    tracks = [t for t in _user_tracks(ct) if t["xyz"] is not None
              and (not wanted or t["name"] in wanted or t["index"] in wanted)]
    if not tracks:
        raise CommandError("No user tracks with a 3D position on %s" % ct.fullName())

    # Resolve the camera before creating anything, so a missing camera fails fast.
    camera = _find_camera(ct, params.get("camera_node")) if params.get("verify", True) else None
    existing = [n for n in nuke.allNodes(recurseGroups=False)
                if n.Class() in ("Axis", "Axis2", "Axis3", "Axis4")]
    axis_class = params.get("axis_class") or (existing[0].Class() if existing else "Axis")
    factory = getattr(nuke.nodes, axis_class, None)
    if factory is None:
        raise CommandError("Unknown Axis class '%s'" % axis_class)

    def matches(node, xyz):
        try:
            t = node["translate"].value()
            return all(abs(a - b) < 1e-4 * max(1.0, abs(b)) for a, b in zip(t, xyz))
        except Exception:
            return False

    created, skipped, pairs = [], [], []
    x0 = int(params.get("x", ct.xpos() + 150))
    y0 = int(params.get("y", ct.ypos() + 100))
    per_row = int(params.get("per_row", 7))
    slot = 0
    for t in tracks:
        xyz = _xyz_value(t["xyz"])
        if all(v == 0.0 for v in xyz):
            skipped.append({"track": t["name"], "reason": "no 3D position (solve or Update User Track XYZ)"})
            continue
        twin = next((n for n in existing if matches(n, xyz)), None)
        if twin is not None and params.get("skip_existing", True):
            skipped.append({"track": t["name"], "reason": "already exported as %s" % twin.fullName()})
            pairs.append((t, xyz))
            continue
        ax = factory()
        ax["translate"].setValue(xyz)
        if "label" in ax.knobs():
            ax["label"].setValue(t["name"])
        ax.setXYpos(x0 + (slot % per_row) * 90, y0 + (slot // per_row) * 90)
        slot += 1
        created.append({"axis": ax.fullName(), "track": t["name"],
                        "translate": [round(v, 5) for v in xyz]})
        pairs.append((t, xyz))

    result = {"node": ct.fullName(), "axis_class": axis_class, "created": created,
              "skipped": skipped}
    if camera is not None and pairs:
        frames, errors, summary = _qc(ct, camera, pairs, int(params.get("qc_frames", 5)))
        result["qc"] = {"camera": camera.fullName(), "frames": frames,
                        "summary": summary, "errors_px": errors,
                        "note": "Pinhole reprojection vs 2D tracks; if the solve includes lens "
                                "distortion, errors grow towards the frame edges."}
    return result


@command("cameratracker_reprojection_qc")
def cameratracker_reprojection_qc(params):
    """Reprojection error of every solved user track through the camera."""
    ct = _cameratracker(params["node_name"])
    pairs = []
    for t in _user_tracks(ct):
        if t["xyz"] is not None:
            xyz = _xyz_value(t["xyz"])
            if any(v != 0.0 for v in xyz):
                pairs.append((t, xyz))
    camera = _find_camera(ct, params.get("camera_node"))
    frames, errors, summary = _qc(ct, camera, pairs, int(params.get("qc_frames", 5)))
    worst = sorted(((max(e for _, e in v), k) for k, v in errors.items()), reverse=True)[:5]
    return {"camera": camera.fullName(), "frames": frames, "summary": summary,
            "worst_tracks": [{"track": k, "max_px": m} for m, k in worst], "errors_px": errors}
