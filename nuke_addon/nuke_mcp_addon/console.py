"""Ring buffer of everything Nuke's Python prints, readable by the agent.

sys.stdout / sys.stderr are wrapped once with a tee that keeps forwarding to the
original stream (Nuke's Script Editor redirector or the terminal), so nothing
changes for the user. Output captured inside execute_python is added too.
"""

import collections
import sys
import threading
import time

from .constants import CONSOLE_MAX_LINES

# globals().get(...) keeps the buffer across addon hot reloads.
_lines = globals().get("_lines") or collections.deque(maxlen=CONSOLE_MAX_LINES)
_lock = globals().get("_lock") or threading.Lock()
_partial = globals().get("_partial") or {"stdout": "", "stderr": ""}
_seq = globals().get("_seq", 0)


def record(stream, text, source="nuke"):
    """Append text (possibly several lines) to the buffer."""
    global _seq
    if not text:
        return
    with _lock:
        buf = _partial.get(stream, "") + text
        parts = buf.split("\n")
        _partial[stream] = parts.pop()  # keep an unterminated tail for the next write
        now = time.time()
        for line in parts:
            _seq += 1
            _lines.append({"seq": _seq, "time": now, "stream": stream, "source": source,
                           "text": line})


class _Tee:
    def __init__(self, stream, name):
        self._stream = stream
        self._name = name
        self._nuke_mcp_tee = True

    def write(self, text):
        try:
            record(self._name, text)
        except Exception:
            pass
        return self._stream.write(text)

    def flush(self):
        return self._stream.flush()

    def __getattr__(self, attr):
        return getattr(self._stream, attr)


def install():
    """Wrap sys.stdout/sys.stderr (idempotent)."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None or getattr(stream, "_nuke_mcp_tee", False):
            continue
        setattr(sys, name, _Tee(stream, name))


def read(last_n=200, stream=None, contains=None, since_seq=None):
    with _lock:
        lines = list(_lines)
    if since_seq is not None:
        lines = [ln for ln in lines if ln["seq"] > since_seq]
    if stream:
        lines = [ln for ln in lines if ln["stream"] == stream]
    if contains:
        needle = contains.lower()
        lines = [ln for ln in lines if needle in ln["text"].lower()]
    if last_n:
        lines = lines[-int(last_n):]
    return lines


def clear():
    with _lock:
        _lines.clear()
        _partial["stdout"] = _partial["stderr"] = ""
