"""Enumerate the same bounded, single-edit Python candidates for both policies."""
from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass

from ..transform import GuardRule, apply_guard


@dataclass(frozen=True)
class Patch:
    """A proposed full source with one specific edit and its location."""

    kind: str
    function: str
    line: int
    column: int
    source: str


def _function_nodes(function: ast.FunctionDef) -> Iterator[ast.AST]:
    """Enumerate edits within the function's scope, skipping nested scopes."""
    pending: list[ast.AST] = list(reversed(function.body))
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield node
        pending.extend(reversed(list(ast.iter_child_nodes(node))))


def _replace(source: str, node: ast.expr, text: str) -> str:
    """Replace the exact expression span while preserving surrounding source."""
    raw = source.encode('utf-8')
    lines = raw.split(b'\n')
    start = sum(len(line) + 1 for line in lines[:node.lineno - 1]) + node.col_offset
    end = sum(len(line) + 1 for line in lines[:node.end_lineno - 1]) + node.end_col_offset
    return (raw[:start] + text.encode('utf-8') + raw[end:]).decode('utf-8')


def _rewrite(node: ast.AST) -> tuple[str, ast.expr, str] | None:
    """Identify two common truthiness forms that can be restricted to None."""
    if isinstance(node, ast.If) and isinstance(node.test, ast.UnaryOp):
        if isinstance(node.test.op, ast.Not) and isinstance(node.test.operand, ast.Name):
            return 'replace-not', node.test, f'{node.test.operand.id} is None'
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and len(node.values) == 2:
        left, right = node.values
        if isinstance(left, ast.Name):
            condition = ast.Compare(left=left, ops=[ast.Is()], comparators=[ast.Constant(None)])
            replacement = ast.IfExp(test=condition, body=right, orelse=left)
            return 'replace-or', node, f'({ast.unparse(replacement)})'
    return None


def candidates(source: str, rule: GuardRule) -> list[Patch]:
    """Propose one insertion or replacement at each applicable location."""
    functions = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)]
    patches = []
    for function in functions:
        try:
            patched = apply_guard(source, function.name, rule)
        except ValueError:
            pass
        else:
            anchor = function.body[1 if ast.get_docstring(function) is not None else 0]
            patches.append(Patch('insert-guard', function.name, anchor.lineno, -1, patched))
        for node in _function_nodes(function):
            edit = _rewrite(node)
            if edit:
                kind, span, text = edit
                patches.append(Patch(kind, function.name, span.lineno, span.col_offset, _replace(source, span, text)))
    return sorted(patches, key=lambda p: (p.line, p.column, p.kind))
