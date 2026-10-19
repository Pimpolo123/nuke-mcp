"""Undo groups, atomic transactions and walking back the agent's own steps.

Nuke facts this relies on (checked on 15.1 and 17.x):
- ``nuke.Undo.begin(label)`` / ``nuke.Undo.end()`` group actions into one step.
  ``nuke.UndoGroup`` does not exist on every version, so it is not used.
- ``nuke.Undo.cancel()`` undoes what was recorded since ``begin`` and discards
  the group: a failed command leaves no half-built graph behind.
- Groups that record nothing (read-only work) are dropped by Nuke, so the
  user's undo stack only shows steps that changed something.
- Undoing *inside* an open group corrupts the stack, so walking back is never
  done from within a transaction.
- Terminal sessions (nuke -t) keep no undo stack: ``cancel`` reverts nothing.
  There the transaction falls back to deleting the nodes it created, and says
  so ("rolled_back": "created_nodes_only"); knob edits cannot be reverted.
"""

import contextlib

from .constants import UNDO_PREFIX
from .util import get_nuke

_depth = 0  # only the outermost transaction opens/closes a Nuke undo group


def _undo_api():
    try:
        return getattr(get_nuke(), "Undo", None)
    except ImportError:
        return None


class Transaction:
    """Group everything inside into one labelled undo step.

    atomic=True rolls back (``Undo.cancel``) when an exception escapes, so the
    script is left exactly as it was. Nested transactions join the outer one.
    """

    def __init__(self, label, atomic=True, enabled=True):
        self.label = UNDO_PREFIX + label
        self.atomic = atomic
        self.enabled = enabled
        self.rolled_back = False
        self._owner = False
        self._nodes_before = None

    def __enter__(self):
        global _depth
        if not self.enabled:
            return self
        api = _undo_api()
        if _depth == 0 and api is not None:
            try:
                api.begin(self.label)
                self._owner = True
            except Exception:
                self._owner = False
            if self._owner and self.atomic and not _gui():
                self._nodes_before = _node_ids()
        _depth += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        global _depth
        if not self.enabled:
            return False
        _depth -= 1
        if not self._owner:
            return False
        api = _undo_api()
        if exc_type is not None and self.atomic:
            if self._nodes_before is not None:
                self.rolled_back = _delete_new_nodes(self._nodes_before)
            try:
                api.cancel()
                if self._nodes_before is None:
                    self.rolled_back = True
                return False
            except Exception:
                pass
        try:
            api.end()
        except Exception:
            pass
        return False


def _gui():
    try:
        return bool(get_nuke().GUI)
    except Exception:
        return False


def _node_ids():
    return {n.fullName() for n in get_nuke().allNodes(recurseGroups=True)}


def _delete_new_nodes(before):
    nuke = get_nuke()
    new = [n for n in nuke.allNodes(recurseGroups=True) if n.fullName() not in before]
    # Children first, so deleting a new Group does not invalidate its members.
    for node in sorted(new, key=lambda n: -n.fullName().count(".")):
        try:
            nuke.delete(node)
        except Exception:
            pass
    return "created_nodes_only"


def in_transaction():
    return _depth > 0


def describe(index=0):
    """Label of the undo step ``index`` places back from the top ('' if none)."""
    api = _undo_api()
    if api is None:
        return ""
    try:
        return api.undoDescribe(index) or ""
    except Exception:
        return ""


def history(limit=20):
    api = _undo_api()
    steps = []
    if api is None:
        return steps
    try:
        size = api.undoSize()
    except Exception:
        size = limit
    for i in range(min(limit, size)):
        label = describe(i)
        if not label:
            break
        steps.append({"index": i, "label": label, "agent": label.startswith(UNDO_PREFIX)})
    return steps


def undo_agent_steps(max_steps=200):
    """Undo consecutive agent steps from the top of the stack.

    Stops at the first step that does not carry the agent prefix, so work the
    user did by hand is never touched. Redo (Ctrl+Shift+Z) brings it all back.
    """
    if in_transaction():
        raise RuntimeError("cannot walk the undo stack from inside a transaction")
    nuke = get_nuke()
    api = _undo_api()
    undone = []
    stopped_at = None
    for _ in range(max_steps):
        label = describe(0)
        if not label:
            break
        if not label.startswith(UNDO_PREFIX):
            stopped_at = label
            break
        if hasattr(api, "undo"):
            api.undo()
        else:
            nuke.undo()
        undone.append(label)
    return {"undone": undone, "count": len(undone), "stopped_at_user_step": stopped_at}


@contextlib.contextmanager
def undo_disabled():
    """Run without recording anything (temporary helper nodes for previews)."""
    api = _undo_api()
    disabled = False
    if api is not None and not in_transaction():
        try:
            api.disable()
            disabled = True
        except Exception:
            disabled = False
    try:
        yield
    finally:
        if disabled:
            try:
                api.enable()
            except Exception:
                pass
