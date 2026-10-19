"""execute_python: run arbitrary Python inside Nuke.

Fixes over the original handler:
- One namespace (globals == locals). With separate dicts, comprehensions,
  generator expressions and functions defined in the snippet cannot see the
  snippet's own variables and die with NameError.
- A single expression is evaluated and its value returned, so
  ``nuke.toNode('Blur1')['size'].value()`` needs no ``result =``.
- stdout/stderr are captured and returned (and kept in the console buffer).
- Errors report the failing line of the snippet, not the addon's internals.
- The dispatcher wraps the call in an atomic undo transaction: if the snippet
  raises half way, everything it changed is rolled back.
- ``persist=True`` keeps one namespace across calls, like a REPL session.
"""

import builtins
import contextlib
import io
import sys
import traceback

from .. import console
from ..dispatch import command
from ..util import get_nuke, get_nukescripts, jsonable

FILENAME = "<nuke-mcp>"
_session_ns = {}


def _fresh_namespace():
    ns = {"__name__": "__nuke_mcp__", "__builtins__": builtins, "nuke": get_nuke()}
    nukescripts = get_nukescripts()
    if nukescripts is not None:
        ns["nukescripts"] = nukescripts
    return ns


def _snippet_traceback(exc_type, exc, tb, code):
    frames = [f for f in traceback.extract_tb(tb) if f.filename == FILENAME]
    lines = code.splitlines()
    report = []
    for f in frames:
        text = lines[f.lineno - 1].strip() if 0 < f.lineno <= len(lines) else ""
        report.append({"line": f.lineno, "function": f.name, "code": text})
    if isinstance(exc, SyntaxError) and exc.lineno:
        report.append({"line": exc.lineno, "code": (exc.text or "").strip()})
    return report


@command("execute_python", undo=True, label="execute_python")
def execute_python(params):
    code = params["code"]
    if params.get("persist"):
        if not _session_ns or params.get("reset"):
            _session_ns.clear()
            _session_ns.update(_fresh_namespace())
        ns = _session_ns
    else:
        ns = _fresh_namespace()

    out, err = io.StringIO(), io.StringIO()
    value, mode = None, "exec"
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                compiled = compile(code, FILENAME, "eval")
                mode = "eval"
            except SyntaxError:
                compiled = compile(code, FILENAME, "exec")
            if mode == "eval":
                value = eval(compiled, ns)  # noqa: S307 - this tool exists to run code
            else:
                exec(compiled, ns)  # noqa: S102
                value = ns.get("result")
    except Exception as e:
        exc_type, exc, tb = sys.exc_info()
        console.record("stdout", out.getvalue(), source="execute_python")
        console.record("stderr", err.getvalue(), source="execute_python")
        return {
            "status": "error",
            "error": "%s: %s" % (type(e).__name__, e),
            "where": _snippet_traceback(exc_type, exc, tb, code),
            "stdout": out.getvalue()[-20000:],
            "stderr": err.getvalue()[-20000:],
        }
    console.record("stdout", out.getvalue(), source="execute_python")
    console.record("stderr", err.getvalue(), source="execute_python")
    response = {"status": "ok", "result": jsonable(value), "mode": mode}
    if out.getvalue():
        response["stdout"] = out.getvalue()[-20000:]
    if err.getvalue():
        response["stderr"] = err.getvalue()[-20000:]
    return response
