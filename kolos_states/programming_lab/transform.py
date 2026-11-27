"""Learn one insertion from a code diff and rebind it to a new function."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from io import StringIO


@dataclass(frozen=True)
class GuardRule:
    """One demonstrated statement and its index among executable statements."""

    index: int
    statement: str


def _function(module: ast.Module, name: str) -> ast.FunctionDef:
    """Select a unique, top-level synchronous function named in the task."""
    matches = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(matches) != 1:
        raise ValueError('Expected one top-level function with the requested name')
    return matches[0]


def _parameter(function: ast.FunctionDef) -> str:
    """Bind only signatures with a single required positional parameter."""
    args = function.args
    positional = args.posonlyargs + args.args
    if len(positional) != 1 or args.defaults or args.kwonlyargs or args.vararg or args.kwarg:
        raise ValueError('Expected one required positional parameter')
    return positional[0].arg


def _body(function: ast.FunctionDef) -> list[ast.stmt]:
    """Exclude the docstring from the executable anchor indices."""
    return function.body[1:] if ast.get_docstring(function) is not None else function.body


def _operand(statement: ast.stmt) -> ast.Name:
    """Identify the bindable operand in a bounded comparison-and-return grammar."""
    if (isinstance(statement, ast.If) and not statement.orelse and len(statement.body) == 1
            and isinstance(statement.body[0], ast.Return)
            and isinstance(statement.body[0].value, ast.Constant)
            and isinstance(statement.test, ast.Compare) and isinstance(statement.test.left, ast.Name)
            and len(statement.test.ops) == 1
            and isinstance(statement.test.ops[0], (ast.Is, ast.IsNot, ast.Eq, ast.NotEq))
            and isinstance(statement.test.comparators[0], ast.Constant)):
        return statement.test.left
    raise ValueError('Expected an if comparing a parameter with a literal and returning a literal')


def learn_guard(before: str, after: str, name: str) -> GuardRule:
    """Infer the statement and anchor from a single observed insertion."""
    original, edited = ast.parse(before), ast.parse(after)
    base, changed = _function(original, name), _function(edited, name)
    parameter = _parameter(base)
    base_body, changed_body = _body(base), _body(changed)
    if len(changed_body) != len(base_body) + 1:
        raise ValueError('The demonstration must insert one statement')
    expected = [ast.dump(stmt) for stmt in base_body]
    observed = [ast.dump(stmt) for stmt in changed_body]
    matches = [i for i in range(len(base_body)) if observed[:i] + observed[i + 1:] == expected]
    if len(matches) != 1:
        raise ValueError('The insertion must have one unambiguous anchor before an existing statement')
    index = matches[0]
    statement = changed_body[index]
    changed.body.remove(statement)
    if ast.dump(original) != ast.dump(edited) or _operand(statement).id != parameter:
        raise ValueError('The demonstration must only insert a guard on the observed parameter')
    return GuardRule(index, ast.unparse(statement))


def apply_guard(source: str, name: str, rule: GuardRule) -> str:
    """Insert the rebound statement while preserving the original source bytes as text."""
    function = _function(ast.parse(source), name)
    parameter = _parameter(function)
    body = _body(function)
    if type(rule.index) is not int or not 0 <= rule.index < len(body):
        raise ValueError('The learned anchor is missing')
    statements = ast.parse(rule.statement).body
    if len(statements) != 1:
        raise ValueError('The stored rule must contain a single statement')
    statement = statements[0]
    _operand(statement).id = parameter
    if any(ast.dump(existing) == ast.dump(statement) for existing in body):
        raise ValueError('The learned guard already exists')
    return _insert(source, body[rule.index], ast.unparse(statement), function.lineno)


def _insert(source: str, anchor: ast.stmt, statement: str, header_line: int) -> str:
    """Insert before the anchor's physical block without rewriting the surrounding code."""
    decorators = anchor.decorator_list if isinstance(anchor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else []
    line_index = (decorators[0].lineno if decorators else anchor.lineno) - 1
    lines = StringIO(source).readlines()
    line = lines[line_index]
    indent = line[:len(line) - len(line.lstrip(' \t'))]
    if line_index + 1 <= header_line or not indent or len(indent) != anchor.col_offset:
        raise ValueError('The learned anchor needs its own indented line')
    newline = '\r\n' if line.endswith('\r\n') else '\n'
    condition, result = statement.split('\n')
    insertion = f'{indent}{condition}{newline}{indent}{indent}{result.removeprefix("    ")}{newline}'
    return ''.join(lines[:line_index]) + insertion + ''.join(lines[line_index:])
