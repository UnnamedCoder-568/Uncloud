"""Every module resolves the names it uses.

This exists because `output_dir_for` was used in narration_engine and never
imported. Python does not notice until the line runs, and that line only runs
once somebody has installed an optional voice engine and pressed Narrate — so
it shipped, and the first person to reach it got `name 'output_dir_for' is not
defined` where they expected audio.

A static check costs milliseconds and catches the whole class: a typo, a moved
helper, an import dropped during a refactor. It is deliberately conservative —
it reports only names nothing in the file could possibly bind, so a pass means
something rather than nothing.
"""

from __future__ import annotations

import ast
import builtins
import pathlib

import pytest

PACKAGE = pathlib.Path(__file__).resolve().parents[1] / "uncloud_engine"

#: Names Python provides that are not in `builtins`.
IMPLICIT = {"__file__", "__name__", "__doc__", "__package__", "__spec__",
            "__loader__", "__builtins__", "__path__"}


def _bound_names(tree: ast.AST) -> set[str]:
    """Everything the module could bind, anywhere, by any means.

    Generous on purpose: function-local scoping, comprehensions and `global`
    are not modelled. A name bound in one function counts as bound everywhere,
    which can hide a genuine error — but never invents one, and a check that
    cries wolf is a check people learn to skip.
    """
    bound = set(dir(builtins)) | IMPLICIT
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bound |= {(a.asname or a.name.split(".")[0]) for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            bound |= {(a.asname or a.name) for a in node.names}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound |= set(node.names)
    return bound


def _modules() -> list[pathlib.Path]:
    return sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_module_defines_every_name_it_loads(path: pathlib.Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bound = _bound_names(tree)
    unresolved = sorted({
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        and node.id not in bound
    })
    assert not unresolved, (
        f"{path.name} uses names it never binds or imports: {unresolved}. "
        f"Python raises NameError for these only when the line runs, which for "
        f"a rarely-taken branch means it ships.")
