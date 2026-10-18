"""Safe evaluation of the rule expressions Component-02 sends as data.

Allowed: names, `prior.x` / `child.x` / `parent.x`, number and text literals,
+ - * / %, unary +/-, abs/min/max, comparisons, and/or/not. No eval(), no other
calls or attributes. Anything else raises ExpressionError. The LLM never writes
these expressions.
"""
import ast
import operator

SCOPES = frozenset({"prior", "child", "parent"})
_ARITH = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.Mod: operator.mod}
_ORDER = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
_FUNCS = {"abs": abs, "min": min, "max": max}
_MAX_LEN = 300

Value = float | str


class ExpressionError(ValueError):
    """The expression is malformed, not allowed, or cannot be computed."""


def _parse(expression: str) -> ast.expr:
    if not isinstance(expression, str) or not expression.strip():
        raise ExpressionError("expression must be a non-empty string")
    if len(expression) > _MAX_LEN:
        raise ExpressionError("expression too long")
    try:
        return ast.parse(expression.strip(), mode="eval").body
    except SyntaxError as exc:
        raise ExpressionError(f"cannot parse expression: {exc.msg}") from exc


def _key(node: ast.AST) -> str | None:
    """`assets` -> 'assets'; `prior.assets` -> 'prior.assets'; else None."""
    if isinstance(node, ast.Name):
        return node.id
    if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id in SCOPES):
        return f"{node.value.id}.{node.attr}"
    return None


def names(expression: str) -> list[str]:
    """Input names the expression needs, in first-seen order."""
    out: list[str] = []

    def walk(node: ast.AST) -> None:
        key = _key(node)
        if key is not None:
            if key not in out:
                out.append(key)
            return
        if isinstance(node, ast.Call):
            for arg in node.args:
                walk(arg)
            return
        for child in ast.iter_child_nodes(node):
            walk(child)

    walk(_parse(expression))
    return out


def _value(node: ast.AST, values: dict[str, Value]) -> Value:
    key = _key(node)
    if key is not None:
        if key not in values:
            raise ExpressionError(f"unknown input {key!r}")
        v = values[key]
        if isinstance(v, str):
            return v
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ExpressionError(f"input {key!r} is not a number or text")
        return float(v)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExpressionError(f"literal {node.value!r} not allowed")
        return float(node.value)
    if isinstance(node, ast.BinOp):
        op = _ARITH.get(type(node.op))
        if op is None:
            raise ExpressionError(f"operator {type(node.op).__name__} not allowed")
        try:
            return op(_num(node.left, values), _num(node.right, values))
        except (ZeroDivisionError, OverflowError) as exc:
            raise ExpressionError(f"arithmetic error: {exc}") from exc
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _num(node.operand, values)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.Call):
        fn = _FUNCS.get(node.func.id) if isinstance(node.func, ast.Name) else None
        if fn is None or node.keywords or not node.args:
            raise ExpressionError("only abs(), min() and max() calls are allowed")
        args = [_num(a, values) for a in node.args]
        if fn is abs and len(args) != 1:
            raise ExpressionError("abs() takes one argument")
        return fn(*args)
    raise ExpressionError(f"{type(node).__name__} not allowed here")


def _num(node: ast.AST, values: dict[str, Value]) -> float:
    v = _value(node, values)
    if isinstance(v, str):
        raise ExpressionError(f"text {v!r} used in arithmetic")
    return v


def _compare(op: ast.cmpop, left: Value, right: Value, tolerance: float) -> bool:
    if isinstance(left, str) or isinstance(right, str):
        if not (isinstance(left, str) and isinstance(right, str)):
            raise ExpressionError("cannot compare text with a number")
        same = left.strip().lower() == right.strip().lower()
        if isinstance(op, ast.Eq):
            return same
        if isinstance(op, ast.NotEq):
            return not same
        raise ExpressionError("text can only be compared with == or !=")
    if isinstance(op, ast.Eq):
        return abs(left - right) <= tolerance
    if isinstance(op, ast.NotEq):
        return abs(left - right) > tolerance
    fn = _ORDER.get(type(op))
    if fn is None:
        raise ExpressionError(f"comparison {type(op).__name__} not allowed")
    return fn(left, right)


def _truth(node: ast.AST, values: dict[str, Value], tolerance: float) -> bool:
    if isinstance(node, ast.Compare):
        left = _value(node.left, values)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _value(comparator, values)
            if not _compare(op, left, right, tolerance):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        results = [_truth(v, values, tolerance) for v in node.values]
        return all(results) if isinstance(node.op, ast.And) else any(results)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _truth(node.operand, values, tolerance)
    raise ExpressionError("expression must be a comparison")


def evaluate(expression: str, values: dict[str, Value], tolerance: float = 0.0) -> bool:
    """True when the rule holds. Raises ExpressionError when it cannot be computed."""
    return _truth(_parse(expression), values, tolerance)
