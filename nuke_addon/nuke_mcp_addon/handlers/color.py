"""Colour-pipeline audit for ACES/OCIO scripts. Reports only; never changes anything.

Checks the mistakes that silently corrupt pixels in a colour-managed comp:
- Data passes (depth, normals, position, motion, IDs, crypto) read through a
  colour transform. Their values get remapped, which shows up as banding in
  the viewer and as wrong numbers in ZDefocus / relight / Z-merges.
- Display-referred 8-bit files (JPEG/PNG/...) read as scene-linear.
- EXRs read with a display transform (sRGB/Rec.709 curves) as input.
- Writes whose colorspace does not fit the file type.
"""

import os
import re

from ..dispatch import command
from ..util import get_nuke

_DATA_HINT = re.compile(
    r"(^|[._\-/\\])(z|depth|zdepth|n|normals?|nrm|p|pos|position|pworld|pref|"
    r"motion|mv|vector|velocity|vel|crypto\w*|id|objectid|matid|uv|st|stmap)([._\-/\\]|\d|$)",
    re.IGNORECASE)
_DATA_LAYERS = re.compile(
    r"^(depth|z|n|normals?|p|position|pworld|pref|motion|forward|backward|velocity|"
    r"crypto\w*|id\w*|uv|stmap)$", re.IGNORECASE)
_RAW_NAMES = re.compile(r"raw|data|utility - raw|non-color|^none$", re.IGNORECASE)
_LINEAR_NAMES = re.compile(r"linear|acescg|aces2065|scene_linear|lin_|acescct?$", re.IGNORECASE)
_DISPLAY_NAMES = re.compile(r"srgb|rec\.?709|gamma|output -|display|bt\.?1886|texture",
                            re.IGNORECASE)
_EIGHT_BIT = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tga", ".webp"}


def _colorspace(node):
    if "raw" in node.knobs() and node["raw"].value():
        return "RAW"
    if "colorspace" in node.knobs():
        return node["colorspace"].value()
    return ""


def _is_raw(cs):
    return cs == "RAW" or bool(_RAW_NAMES.search(cs or ""))


@command("audit_color")
def audit_color(params):
    nuke = get_nuke()
    root = nuke.root()
    findings = []
    summary = {}
    if "colorManagement" in root.knobs():
        summary["color_management"] = root["colorManagement"].value()
    for key in ("OCIO_config", "customOCIOConfigPath", "workingSpaceLUT"):
        if key in root.knobs():
            summary[key] = root[key].value()

    reads = nuke.allNodes("Read", recurseGroups=True)
    by_cs = {}
    for node in reads:
        path = node["file"].value()
        if not path:
            continue
        ext = os.path.splitext(path)[1].lower()  # "shot.%04d.exr" -> ".exr"
        cs = _colorspace(node)
        by_cs.setdefault(cs or "?", []).append(node.fullName())
        base = os.path.basename(path)
        if _DATA_HINT.search(base) and not _is_raw(cs):
            findings.append({
                "severity": "high", "node": node.fullName(), "file": path, "colorspace": cs,
                "issue": "Looks like a data pass but is read through a colour transform.",
                "why": "Depth/normal/position/vector/ID values get remapped: banding in the "
                       "viewer and wrong numbers in ZDefocus, relight or Z-merges.",
                "fix": "Enable 'raw' (Raw Data) on this Read, or set colorspace to Utility - Raw.",
            })
        if ext == ".exr" and not _is_raw(cs):
            try:
                layers = {c.split(".")[0] for c in node.channels()}
            except Exception:
                layers = set()
            data_layers = sorted(layer for layer in layers if _DATA_LAYERS.match(layer))
            if data_layers:
                findings.append({
                    "severity": "medium", "node": node.fullName(), "file": path,
                    "colorspace": cs, "layers": data_layers,
                    "issue": "Multi-layer EXR with data layers read through '%s'." % cs,
                    "why": "Shuffled-out data layers inherit the Read's input transform.",
                    "fix": "Read the data layers with a second Read set to raw, "
                           "keep this one for the beauty.",
                })
            if cs and _DISPLAY_NAMES.search(cs) and not _LINEAR_NAMES.search(cs):
                findings.append({
                    "severity": "medium", "node": node.fullName(), "file": path, "colorspace": cs,
                    "issue": "EXR read with a display-referred colorspace.",
                    "why": "EXRs are normally scene-linear; a display curve as input "
                           "transform distorts the values.",
                    "fix": "Check the file's real encoding (metadata colorInteropID / "
                           "exr/chromaticities) and set the matching linear space.",
                })
        if ext in _EIGHT_BIT and cs and _LINEAR_NAMES.search(cs) and not _is_raw(cs):
            findings.append({
                "severity": "medium", "node": node.fullName(), "file": path, "colorspace": cs,
                "issue": "8-bit display-referred file read as scene-linear.",
                "why": "JPEG/PNG carry an sRGB curve; treating them as linear makes them "
                       "look washed out and breaks merges.",
                "fix": "Use Utility - sRGB - Texture (sRGB Encoded Rec.709) and seat it with "
                       "a Grade; inverse Output-sRGB only for emissive elements.",
            })

    for node in nuke.allNodes("Write", recurseGroups=True):
        ftype = node["file_type"].value() if "file_type" in node.knobs() else ""
        cs = _colorspace(node)
        if ftype == "exr" and cs and cs != "RAW" and _DISPLAY_NAMES.search(cs) \
                and not _LINEAR_NAMES.search(cs):
            findings.append({
                "severity": "medium", "node": node.fullName(), "file_type": ftype,
                "colorspace": cs, "issue": "EXR written with a display-referred colorspace.",
                "fix": "Write EXRs scene-linear (ACEScg or ACES2065-1 per the show spec).",
            })
        if ftype in ("jpeg", "png", "tiff") and cs and _LINEAR_NAMES.search(cs) and cs != "RAW":
            findings.append({
                "severity": "low", "node": node.fullName(), "file_type": ftype, "colorspace": cs,
                "issue": "Display format written as scene-linear (will look dark/flat).",
                "fix": "Use an output/display transform for review formats.",
            })

    summary["reads_by_colorspace"] = by_cs
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: order.get(f["severity"], 3))
    return {"summary": summary, "findings": findings, "count": len(findings)}
