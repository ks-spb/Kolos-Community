"""Evaluate one restricted Python function without executing submitted source on the host."""
from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import dataclass
from operator import add, sub
from reprlib import repr as short_repr

from .grammar import CMP
from .spec import Example

COMPARE = dict(zip((ast.Gt, ast.Lt, ast.GtE, ast.LtE, ast.Eq, ast.NotEq), CMP.values(), strict=True))
OPERATORS = {ast.Add: add, ast.Sub: sub}
BUILTINS = {'len': len, 'sum': sum}
ALLOWED = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Load, ast.Store,
           ast.Assign, ast.AugAssign, ast.For, ast.If, ast.Return, ast.Expr,
           ast.Name, ast.Constant, ast.List, ast.Dict, ast.Subscript, ast.Call, ast.Attribute,
           ast.BinOp, ast.UnaryOp, ast.USub, ast.Not, ast.Compare, ast.IfExp,
           *COMPARE, *OPERATORS)
PROMPT_RULES = ('One unannotated Python function, one positional argument, no imports. '
                'Use assignments, +=, for loops over a list, if, return, list/dict literals, '
                'indexing, + and -, comparisons, len, sum, dict.get or list.append. '
                'Use simple loops and no comprehensions or generators.')
GROUP_ITERATION = ' You may also loop over dictionary keys with for key in mapping and use mapping[key].'


@dataclass(frozen=True)
class Check:
    """The observed result, or the reason a candidate could not be evaluated."""

    passed: bool
    index: int
    actual: object = None
    expected: object = None
    error: str | None = None


def _function(source: str, function: str, parameter: str) -> ast.FunctionDef:
    """Check the full source before visiting any statement."""
    if len(source) > 8000:
        raise ValueError('Кандидат слишком большой.')
    module = ast.parse(source)
    nodes = list(ast.walk(module))
    if len(nodes) > 400 or any(not isinstance(node, ALLOWED) for node in nodes):
        raise ValueError('Кандидат использует неподдерживаемые конструкции Python.')
    if len(module.body) != 1 or not isinstance(module.body[0], ast.FunctionDef):
        raise ValueError('Кандидат должен содержать одну функцию.')
    definition = module.body[0]
    args = definition.args
    if (definition.name != function or args.posonlyargs or len(args.args) != 1 or
            args.args[0].arg != parameter or args.args[0].annotation or args.defaults or
            args.vararg or args.kwonlyargs or args.kwarg or definition.decorator_list or
            definition.returns or getattr(definition, 'type_params', ())):
        raise ValueError('Сигнатура кандидата отличается от задания.')
    return definition


class _Interpreter:
    """Interpret a closed set of operations on copies of JSON values."""

    def __init__(self, parameter: str, example: Example) -> None:
        self.names = {parameter: deepcopy(example.input)}
        self.fuel = 1000 + len(example.input) * 80

    def tick(self) -> None:
        """Bound the work of nested loops and expressions per example."""
        self.fuel -= 1
        if self.fuel < 0:
            raise ValueError('Превышен лимит операций кандидата.')

    def value(self, node: ast.expr) -> object:
        """Evaluate supported expressions from the current local variables."""
        self.tick()
        match node:
            case ast.Name(id=name):
                return self.names[name]
            case ast.Constant(value=value) if type(value) in (str, int, bool) or value is None:
                return value
            case ast.List(elts=items):
                return [self.value(item) for item in items]
            case ast.Dict(keys=keys, values=values) if all(key is not None for key in keys):
                return {self.value(key): self.value(value) for key, value in zip(keys, values, strict=True)}
            case ast.Subscript(value=value, slice=index):
                return self.value(value)[self.value(index)]
            case ast.BinOp(left=left, op=op, right=right):
                return self.arithmetic(self.value(left), op, self.value(right))
            case ast.UnaryOp(op=ast.USub(), operand=value):
                return self.arithmetic(0, ast.Sub(), self.value(value))
            case ast.UnaryOp(op=ast.Not(), operand=value):
                return not self.value(value)
            case ast.Compare(left=left, ops=[op], comparators=[right]):
                return COMPARE[type(op)](self.value(left), self.value(right))
            case ast.IfExp(test=test, body=yes, orelse=no):
                return self.value(yes if self.value(test) else no)
            case ast.Call() as call:
                return self.call(call)
            case _:
                raise ValueError('Неподдерживаемое выражение Python.')

    @staticmethod
    def arithmetic(left: object, op: ast.operator, right: object) -> int:
        """Avoid overloaded or potentially unbounded arithmetic on containers."""
        if type(left) is not int or type(right) is not int:
            raise ValueError('Арифметика поддерживается только для целых чисел.')
        return OPERATORS[type(op)](left, right)

    def call(self, node: ast.Call) -> object:
        """Dispatch only the explicit built-in operations used by both solvers."""
        args = [self.value(arg) for arg in node.args]
        target = node.func
        if isinstance(target, ast.Name) and target.id in BUILTINS and target.id not in self.names:
            if target.id == 'sum' and (not args or type(args[0]) is not list):
                raise ValueError('sum ожидает список.')
            return BUILTINS[target.id](*args)
        if isinstance(target, ast.Attribute):
            owner = self.value(target.value)
            if target.attr == 'get' and type(owner) is dict:
                return owner.get(*args)
            if target.attr == 'append' and type(owner) is list and len(args) == 1:
                if args[0] is owner:
                    raise ValueError('Циклический список не поддерживается.')
                return owner.append(args[0])
        raise ValueError('Неподдерживаемый вызов Python.')

    def assign(self, target: ast.expr, value: object) -> None:
        """Set a local name or an entry in an ordinary JSON container."""
        if isinstance(target, ast.Name):
            self.names[target.id] = value
        elif isinstance(target, ast.Subscript):
            self.value(target.value)[self.value(target.slice)] = value
        else:
            raise ValueError('Неподдерживаемое присваивание.')

    def block(self, statements: list[ast.stmt]) -> tuple[bool, object]:
        """Execute a suite, propagating an explicit return out of nested blocks."""
        for node in statements:
            self.tick()
            match node:
                case ast.Return(value=value) if value is not None:
                    return True, self.value(value)
                case ast.Assign(targets=[target], value=value):
                    self.assign(target, self.value(value))
                case ast.AugAssign(target=target, op=op, value=value):
                    self.assign(target, self.arithmetic(self.value(target), op, self.value(value)))
                case ast.If(test=test, body=yes, orelse=no):
                    done, value = self.block(yes if self.value(test) else no)
                    if done:
                        return done, value
                case ast.For(target=target, iter=expression, body=body, orelse=[]):
                    values = self.value(expression)
                    if type(values) not in (list, dict):
                        raise ValueError('Цикл for поддерживается по списку или ключам словаря.')
                    for item in values:
                        self.tick()
                        self.assign(target, item)
                        done, value = self.block(body)
                        if done:
                            return done, value
                case ast.Expr(value=value):
                    self.value(value)
                case _:
                    raise ValueError('Неподдерживаемая инструкция Python.')
        return False, None


def same(actual: object, expected: object) -> bool:
    """Compare JSON-shaped results without conflating bool with int."""
    if type(actual) is not type(expected):
        return False
    if type(expected) is list:
        return len(actual) == len(expected) and all(same(a, b) for a, b in zip(actual, expected))
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(same(actual[k], v) for k, v in expected.items())
    return actual == expected


def apply(source: str, function: str, parameter: str, inputs: list) -> object:
    """Use the restricted interpreter to apply a checked recipe to new data."""
    definition = _function(source, function, parameter)
    returned, result = _Interpreter(parameter, Example(inputs, [])).block(definition.body)
    if not returned:
        raise ValueError('Кандидат не вернул результат.')
    return result


def evaluate(source: str, function: str, parameter: str, examples: tuple[Example, ...]) -> Check:
    """Return the first failing example, or confirmation that all examples agree."""
    try:
        definition = _function(source, function, parameter)
    except (ValueError, SyntaxError, RecursionError) as exc:
        return Check(False, -1, error=str(exc))
    for index, example in enumerate(examples):
        try:
            _, actual = _Interpreter(parameter, example).block(definition.body)
            if not same(actual, example.expected):
                return Check(False, index, actual=short_repr(actual), expected=example.expected)
        except (ValueError, TypeError, LookupError, OverflowError, RuntimeError) as exc:
            return Check(False, index, expected=example.expected, error=str(exc))
    return Check(True, len(examples))
