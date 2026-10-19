"""Static safety scan for Python sent to Nuke (execute_python / query_python).

AST-based, so it sees through aliases like ``import os as o; o.remove(...)``
and ``from shutil import rmtree``. It is a guard rail against accidents, not a
sandbox: anything flagged needs an explicit allow_unsafe=True.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

# module -> functions that destroy data, end the session or leave Nuke.
_DANGEROUS = {
    "nuke": {"scriptClose", "scriptClear", "scriptExit", "scriptNew", "exit", "scriptSave",
             "scriptSaveAs", "scriptSaveAndClear", "removeFromMenu"},
    "os": {"remove", "unlink", "rmdir", "removedirs", "rename", "renames", "replace", "system",
           "popen", "startfile", "kill", "_exit", "truncate", "chmod"},
    "shutil": {"rmtree", "move", "copy", "copy2", "copyfile", "copytree", "make_archive"},
    "subprocess": {"run", "call", "check_call", "check_output", "Popen", "getoutput",
                   "getstatusoutput"},
    "sys": {"exit"},
    "pathlib": set(),
}
# Methods that destroy or write files whatever object they are called on.
# ("replace" is left out on purpose: str.replace is everywhere.)
_DANGEROUS_METHODS = {"unlink", "rmdir", "write_text", "write_bytes", "rename", "touch", "chmod"}
_WRITE_MODES = set("wax+")


@dataclass
class Finding:
    line: int
    what: str

    def as_dict(self) -> dict:
        return {"line": self.line, "what": self.what}


class _Scanner(ast.NodeVisitor):
    def __init__(self):
        self.aliases: dict[str, str] = {}  # local name -> "module" or "module.attr"
        self.findings: list[Finding] = []

    def visit_Import(self, node):
        for a in node.names:
            self.aliases[a.asname or a.name.split(".")[0]] = a.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        mod = node.module or ""
        for a in node.names:
            self.aliases[a.asname or a.name] = "%s.%s" % (mod, a.name)
            if a.name == "*" and mod.split(".")[0] in _DANGEROUS:
                self.findings.append(Finding(node.lineno, "from %s import *" % mod))
        self.generic_visit(node)

    def _qualified(self, func) -> str | None:
        parts = []
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if not isinstance(func, ast.Name):
            return None
        base = self.aliases.get(func.id, func.id)
        return ".".join([base] + list(reversed(parts)))

    def visit_Call(self, node):
        name = self._qualified(node.func)
        if name:
            module, _, attr = name.rpartition(".")
            root = module.split(".")[0] if module else ""
            if root in _DANGEROUS and attr in _DANGEROUS[root]:
                self.findings.append(Finding(node.lineno, name))
            elif name in ("exec", "eval", "compile", "__import__") and node.args \
                    and not isinstance(node.args[0], ast.Constant):
                self.findings.append(Finding(node.lineno, "%s() of dynamic code" % name))
            elif name == "open" or name.endswith(".open"):
                mode = None
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    mode = node.args[1].value
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = kw.value.value
                if isinstance(mode, str) and _WRITE_MODES & set(mode):
                    self.findings.append(Finding(node.lineno, "open(..., %r) writes a file" % mode))
        if isinstance(node.func, ast.Attribute) and node.func.attr in _DANGEROUS_METHODS:
            self.findings.append(Finding(node.lineno, ".%s() on a path/file" % node.func.attr))
        self.generic_visit(node)


def scan(code: str) -> list[Finding]:
    """Return the risky operations found in ``code`` (empty list = nothing flagged)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []  # Nuke will report the syntax error with the exact line
    scanner = _Scanner()
    scanner.visit(tree)
    return scanner.findings
