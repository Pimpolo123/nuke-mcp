"""Temporarily silence the user's Nuke callbacks.

Previews and helper renders create, execute and delete temporary nodes. Studio
pipelines hang a lot off those events (Write presets on creation, version-up
and publish hooks on render, cleanup on destroy), and none of it should fire
for a throw-away preview. The registries are plain dicts in Nuke's callbacks
module (``nuke_internal.callbacks`` on 17.x, ``nuke.callbacks`` on 15.x), so
they can be emptied and restored around the work.
"""

import contextlib

CREATE_DESTROY = ("onUserCreates", "onCreates", "onDestroys")
RENDER = ("beforeRenders", "beforeFrameRenders", "afterFrameRenders", "afterRenders",
          "renderProgresses")
ALL = CREATE_DESTROY + RENDER + ("knobChangeds", "updateUIs", "autolabels")


def _callbacks_module():
    for name in ("nuke_internal.callbacks", "nuke.callbacks"):
        try:
            module = __import__(name, fromlist=["_"])
        except ImportError:
            continue
        if hasattr(module, "onCreates"):
            return module
    return None


@contextlib.contextmanager
def suspended(kinds=ALL):
    module = _callbacks_module()
    saved = {}
    if module is not None:
        for kind in kinds:
            registry = getattr(module, kind, None)
            if isinstance(registry, dict):
                saved[kind] = dict(registry)
                registry.clear()
    try:
        yield
    finally:
        for kind, content in saved.items():
            registry = getattr(module, kind)
            registry.clear()
            registry.update(content)
