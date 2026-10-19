"""Let the agent see: window/panel captures and rendered node previews."""

import base64
import os
import re
import sys
import time

from .. import hooks
from ..dispatch import command
from ..undo import undo_disabled
from ..util import CommandError, get_nuke, require_node, temp_dir

# -- Qt helpers ---------------------------------------------------------------


def _qt():
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets
    return QtCore, QtGui, QtWidgets


def _main_window(QtWidgets):
    """nuke.mainWindow does not exist (17.1). Floating panels (a torn-off Viewer)
    are QMainWindows too, so prefer Nuke's own object name, then the biggest."""
    tops = [w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()]
    if not tops:
        raise CommandError("No visible Nuke window (terminal mode cannot capture the screen)")
    for w in tops:
        if w.objectName() == "NukeMainWindow":
            return w
    mains = [w for w in tops if isinstance(w, QtWidgets.QMainWindow)] or tops
    return max(mains, key=lambda w: w.width() * w.height())


def _print_window(QtGui, hwnd):
    """Windows only: ask the OS to render a window into a bitmap.

    PW_RENDERFULLCONTENT includes OpenGL/DirectX content (the Viewer image and
    the Node Graph are GL) and works while the window is covered by other
    applications, which a screen grab would capture instead.
    Returns (QImage, window_top_left, client_origin) or None.
    """
    import ctypes
    from ctypes import wintypes

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.IsIconic.argtypes = [wintypes.HWND]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                ctypes.c_void_p, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT]
    hwnd = wintypes.HWND(hwnd)
    if user32.IsIconic(hwnd):
        raise CommandError("The Nuke window is minimized")
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    previous = gdi32.SelectObject(mem_dc, bitmap)
    try:
        if not user32.PrintWindow(hwnd, mem_dc, 2):  # 2 = PW_RENDERFULLCONTENT
            return None
        header = BITMAPINFOHEADER(40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(mem_dc, bitmap, 0, height, pixels, ctypes.byref(header), 0)
    finally:
        gdi32.SelectObject(mem_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)
    image = QtGui.QImage(pixels.raw, width, height, width * 4, QtGui.QImage.Format_RGB32).copy()
    return image, (rect.left, rect.top), (origin.x, origin.y)


def _capture_widget(QtCore, QtGui, QtWidgets, widget):
    """Pixels of one widget, never including other applications (on Windows)."""
    top = widget.window()
    if sys.platform == "win32":
        grabbed = _print_window(QtGui, int(top.winId()))
        if grabbed is not None:
            image, win_pos, client = grabbed
            dpr = widget.devicePixelRatioF()
            offset = QtCore.QPoint(0, 0) if widget is top else widget.mapTo(top, QtCore.QPoint(0, 0))
            x = (client[0] - win_pos[0]) + int(round(offset.x() * dpr))
            y = (client[1] - win_pos[1]) + int(round(offset.y() * dpr))
            w, h = int(round(widget.width() * dpr)), int(round(widget.height() * dpr))
            return QtGui.QPixmap.fromImage(image.copy(x, y, w, h)), "printwindow"
    # Other platforms: physical screen grab (windows on top of Nuke will show).
    app = QtWidgets.QApplication.instance()
    rect = QtCore.QRect(widget.mapToGlobal(QtCore.QPoint(0, 0)), widget.size())
    screen = app.screenAt(rect.center()) or app.primaryScreen()
    sg = screen.geometry()
    pixmap = screen.grabWindow(0, rect.x() - sg.x(), rect.y() - sg.y(), rect.width(), rect.height())
    return pixmap, "screen_grab"


_PANELS = {"dag": ("DAG", "Node Graph"), "viewer": ("Viewer",), "properties": ("Properties",),
           "script_editor": ("Script Editor", "scripteditor"), "curve_editor": ("Curve Editor",),
           "dope_sheet": ("Dope Sheet",)}


def _find_panel(QtWidgets, wanted):
    needles = [n.lower() for n in _PANELS.get(wanted.lower(), (wanted,))]
    best = None
    for w in QtWidgets.QApplication.allWidgets():
        if not w.isVisible() or w.width() < 50 or w.height() < 50:
            continue
        names = ((w.objectName() or "") + " " + (w.windowTitle() or "")).lower()
        if any(n.lower() in names for n in needles):
            area = w.width() * w.height()
            if best is None or area > best[0]:
                best = (area, w)
    if best is None:
        raise CommandError("Panel '%s' not found or not visible" % wanted)
    return best[1]


def _encode(QtCore, pixmap, max_size, fmt):
    if max_size and max(pixmap.width(), pixmap.height()) > max_size:
        pixmap = pixmap.scaled(max_size, max_size, QtCore.Qt.KeepAspectRatio,
                               QtCore.Qt.SmoothTransformation)
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    pixmap.save(buf, fmt.upper(), 85 if fmt.lower() in ("jpg", "jpeg") else -1)
    data = bytes(buf.data())
    return data, pixmap.width(), pixmap.height()


@command("capture_screen")
def capture_screen(params):
    """mode: window (Nuke's main window), a panel name (dag, viewer, properties,
    script_editor, curve_editor, dope_sheet, or any text matched against widget
    names/titles), or screen (the whole monitor, other applications included).

    On Windows, windows and panels are captured with PrintWindow: the result
    contains only Nuke (GL viewer and node graph included) even when other
    applications cover it."""
    QtCore, QtGui, QtWidgets = _qt()
    app = QtWidgets.QApplication.instance()
    if app is None:
        raise CommandError("No Qt application (terminal mode)")
    mode = (params.get("mode") or "window").lower()
    win = _main_window(QtWidgets)
    if mode == "screen":
        # Whole monitor exactly as displayed, other applications included.
        screen = win.screen() if hasattr(win, "screen") else app.primaryScreen()
        pixmap, method, target = screen.grabWindow(0), "screen_grab", "screen"
    else:
        widget = win if mode == "window" else _find_panel(QtWidgets, mode)
        pixmap, method = _capture_widget(QtCore, QtGui, QtWidgets, widget)
        target = widget.objectName() or widget.windowTitle() or mode
    fmt = params.get("format", "png")
    data, w, h = _encode(QtCore, pixmap, int(params.get("max_size", 1600)), fmt)
    return {"image_base64": base64.b64encode(data).decode("ascii"), "format": fmt,
            "width": w, "height": h, "target": target, "method": method}


# -- node preview -------------------------------------------------------------

_VIEW_DISPLAY = re.compile(r"^(?P<view>.+?) \((?P<display>.+)\)$")


def _display_view(nuke):
    """Display/view the active Viewer uses, as a (display, view) pair or None."""
    viewer = nuke.activeViewer() if hasattr(nuke, "activeViewer") else None
    if viewer is None:
        return None
    node = viewer.node()
    if "viewerProcess" not in node.knobs():
        return None
    value = node["viewerProcess"].value()
    match = _VIEW_DISPLAY.match(value or "")
    if match:
        return match.group("display"), match.group("view")
    return None


def _ocio_managed(nuke):
    root = nuke.root()
    if "colorManagement" in root.knobs():
        return root["colorManagement"].value() == "OCIO"
    return False


@command("render_node_preview")
def render_node_preview(params):
    """Render one frame of any node to a small PNG through the viewer's look.

    Temporary nodes are created with undo disabled and the user's callbacks
    suspended, then deleted: nothing is left in the script or the undo stack,
    and pipeline hooks (Write presets, publish-on-render) never fire.

    channels: "rgb" (default) or "alpha" (alpha shown as grey).
    view_transform: true (viewer's OCIO display/view), false (raw values, for
                    data passes), or "Display/View" to force one.
    """
    nuke = get_nuke()
    node = require_node(params["node_name"])
    if node.hasError():
        raise CommandError("%s has an error: %s" % (node.fullName(), node.error()))
    frame = int(params.get("frame", nuke.frame()))
    max_size = int(params.get("max_size", 1024))
    channels = (params.get("channels") or "rgb").lower()
    transform = params.get("view_transform", True)

    path = os.path.join(temp_dir("previews"), "preview_%d_%d.png" % (frame, int(time.time() * 1000)))
    path = path.replace("\\", "/")
    created = []
    display_view = None
    with hooks.suspended(), undo_disabled():
        try:
            current = node
            if channels == "alpha":
                current = nuke.nodes.Expression(inputs=[current], expr0="a", expr1="a", expr2="a")
                created.append(current)
            fmt = node.format()
            longest = max(fmt.width(), fmt.height())
            if longest > max_size:
                scale = float(max_size) / longest
                current = nuke.nodes.Reformat(inputs=[current], type="scale", scale=scale,
                                              filter="Cubic")
                created.append(current)
            raw = True
            if transform and _ocio_managed(nuke) and channels != "alpha":
                if isinstance(transform, str) and "/" in transform:
                    display_view = tuple(transform.split("/", 1))
                else:
                    display_view = _display_view(nuke)
                current = nuke.nodes.OCIODisplay(inputs=[current])
                if display_view:
                    try:
                        current["display"].setValue(display_view[0])
                        current["view"].setValue(display_view[1])
                    except Exception:
                        display_view = None
                created.append(current)
            elif transform and not _ocio_managed(nuke):
                raw = False  # nuke-default: let the PNG writer apply sRGB
            write = nuke.nodes.Write(inputs=[current], file=path, file_type="png",
                                     channels="rgb")
            if "raw" in write.knobs():
                write["raw"].setValue(raw)
            created.append(write)
            nuke.execute(write, frame, frame)
        finally:
            for tmp in reversed(created):
                try:
                    nuke.delete(tmp)
                except Exception:
                    pass
    if not os.path.isfile(path):
        raise CommandError("Preview render produced no file")
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        os.remove(path)
    except OSError:
        pass
    result = {"image_base64": base64.b64encode(data).decode("ascii"), "format": "png",
              "node": node.fullName(), "frame": frame, "channels": channels,
              "source_format": [node.format().width(), node.format().height()]}
    if display_view:
        result["display"], result["view"] = display_view
    elif transform and _ocio_managed(nuke) and channels != "alpha":
        result["display_view"] = "OCIODisplay defaults"
    else:
        result["display_view"] = "raw" if not transform else "nuke-default sRGB"
    return result
