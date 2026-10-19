"""Animation, expressions and the generic atomic batch."""

from ..dispatch import COMMANDS, META, command
from ..util import CommandError, require_node


def _knob(node, name):
    if name not in node.knobs():
        raise CommandError("Knob '%s' not found on %s" % (name, node.fullName()))
    return node[name]


@command("set_knob_expression", undo=True)
def set_knob_expression(params):
    node = require_node(params["node_name"])
    knob = _knob(node, params["knob_name"])
    expr = params.get("expression") or ""
    index = params.get("field_index")
    if not expr:
        if index is None:
            knob.clearAnimated()
        else:
            knob.clearAnimated(int(index))
        return {"node": node.fullName(), "knob": knob.name(), "expression": None}
    if index is None:
        knob.setExpression(expr)
    else:
        knob.setExpression(expr, int(index))
    return {"node": node.fullName(), "knob": knob.name(), "expression": expr,
            "value_now": knob.value()}


@command("set_knob_keyframes", undo=True)
def set_knob_keyframes(params):
    """Set many keys at once: keys = {frame: value} or {frame: [v0, v1, ...]}.

    Uses setAnimated() before setValueAt(): without it the knob stays static and
    every write silently overwrites the previous one. Verifies the key count.
    """
    node = require_node(params["node_name"])
    knob = _knob(node, params["knob_name"])
    keys = params["keys"]
    index = params.get("field_index")
    if params.get("replace", False):
        if index is None:
            knob.clearAnimated()
        else:
            knob.clearAnimated(int(index))
    fields = set()
    for frame, value in keys.items():
        frame = float(frame)
        if isinstance(value, (list, tuple)):
            for i, v in enumerate(value):
                if i not in fields:
                    knob.setAnimated(i)
                    fields.add(i)
                knob.setValueAt(float(v), frame, i)
        else:
            i = int(index) if index is not None else 0
            if i not in fields:
                knob.setAnimated(i)
                fields.add(i)
            knob.setValueAt(float(value), frame, i)
    counts = {i: knob.getNumKeys(i) for i in sorted(fields)}
    return {"node": node.fullName(), "knob": knob.name(), "keys_per_field": counts}


@command("remove_knob_animation", undo=True)
def remove_knob_animation(params):
    node = require_node(params["node_name"])
    knob = _knob(node, params["knob_name"])
    index = params.get("field_index")
    if index is None:
        knob.clearAnimated()
    else:
        knob.clearAnimated(int(index))
    return {"node": node.fullName(), "knob": knob.name(), "value_now": knob.value()}


@command("batch", undo=True, label="batch")
def batch(params):
    """Run several commands as ONE undo step.

    operations: [{"type": <command>, "params": {...}}, ...]
    The whole batch is atomic by default: if one operation fails, everything
    the batch did is rolled back and the failing operation is reported.
    """
    operations = params.get("operations") or []
    results = []
    for i, op in enumerate(operations):
        name = op.get("type") or op.get("tool")
        if name == "batch":
            raise CommandError("nested batch is not supported")
        handler = COMMANDS.get(name)
        if handler is None:
            raise CommandError("operation %d: unknown command '%s'" % (i, name))
        if not META[name]["undo"] and META[name]["journal"]:
            raise CommandError("operation %d: '%s' cannot run inside a batch" % (i, name))
        try:
            value = handler(op.get("params") or {})
        except CommandError as e:
            raise CommandError("operation %d (%s) failed: %s" % (i, name, e))
        if isinstance(value, dict) and value.get("status") == "error":
            raise CommandError("operation %d (%s) failed: %s" % (i, name, value.get("error")))
        if isinstance(value, dict) and value.get("status") == "ok":
            value = value.get("result")
        results.append({"type": name, "result": value})
    return {"count": len(results), "results": results}
