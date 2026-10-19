"""Small helpers shared by the handlers: lazy imports, errors, JSON conversion."""

import math
import os
import tempfile


class CommandError(Exception):
    """A user-facing failure. The message is returned as-is, without a traceback."""


def get_nuke():
    """Import nuke lazily so this package can be imported outside Nuke for testing."""
    import nuke
    return nuke


def get_nukescripts():
    try:
        import nukescripts
        return nukescripts
    except ImportError:
        return None


def temp_dir(*parts):
    """A per-user scratch directory under the system temp folder."""
    path = os.path.join(tempfile.gettempdir(), "nuke_mcp", *parts)
    os.makedirs(path, exist_ok=True)
    return path


def require_node(name):
    """Resolve a node by full name; 'Root' resolves to the root node."""
    nuke = get_nuke()
    if name in ("Root", "root"):
        return nuke.root()
    node = nuke.toNode(name)
    if node is None:
        raise CommandError("Node '%s' not found" % name)
    return node


def jsonable(value, depth=0, max_items=2000, max_str=20000):
    """Convert Nuke and Python values into something json.dumps accepts.

    Unknown objects become their str(); NaN/inf become None; containers are
    walked recursively and capped so a huge table knob cannot blow up a reply.
    """
    if depth > 8:
        return str(value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value if len(value) <= max_str else value[:max_str] + "...[truncated]"
    if isinstance(value, bytes):
        return "<%d bytes>" % len(value)
    if isinstance(value, dict):
        out = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= max_items:
                out["..."] = "%d more items" % (len(value) - max_items)
                break
            out[str(k)] = jsonable(v, depth + 1, max_items, max_str)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        out = [jsonable(v, depth + 1, max_items, max_str) for v in items[:max_items]]
        if len(items) > max_items:
            out.append("... %d more items" % (len(items) - max_items))
        return out
    # Nuke objects with a useful name (nodes, knobs, formats)
    for attr in ("fullName", "name"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return "<%s %s>" % (type(value).__name__, fn())
            except Exception:
                pass
    s = str(value)
    return s if len(s) <= max_str else s[:max_str] + "...[truncated]"


def node_brief(node):
    return {"name": node.fullName(), "class": node.Class()}
