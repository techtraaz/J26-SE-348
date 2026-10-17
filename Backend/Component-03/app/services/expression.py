"""Safe evaluation of the simple arithmetic comparisons the KG sends.

No eval(), no attribute access, no calls, no imports: only names, number
literals, the operators + - * / %, unary +/-, and comparisons == != < <= > >=.
Anything else raises ExpressionError. The LLM never writes these expressions;
they come from the knowledge graph as data.
"""
import ast
import operator

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Mod: operator.mod}
_CMP = {ast.Lt: operator.lt, ast.LtE: operator.le,
        ast.Gt: operator.gt, ast.GtE: operator.ge}
_MAX_LEN = 200


class ExpressionError(ValueError):
    """The rule expression is missing an input, malformed, or not simple enough."""


def _number(node, values: dict) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExpressionError(f"only number literals allowed, got {node.value!r}")
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise ExpressionError(f"unknown input {node.id!r}")
        v = values[node.id]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ExpressionError(f"input {node.id!r} is not a number")
        return float(v)
    if isinstance(node, ast.BinOp):
        op = _OPS.get(type(node.op))
        if op is None:
            raise ExpressionError(f"operator {type(node.op).__name__} not allowed")
        return op(_number(node.left, values), _number(node.right, values))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _number(node.operand, values)
        return -v if isinstance(node.op, ast.USub) else v
    raise ExpressionError(f"{type(node).__name__} not allowed")


def _compare(op_node, left: float, right: float, tolerance: float) -> bool:
    if isinstance(op_node, ast.Eq):
        return abs(left - right) <= tolerance
    if isinstance(op_node, ast.NotEq):
        return abs(left - right) > tolerance
    fn = _CMP.get(type(op_node))
    if fn is None:
        raise ExpressionError(f"comparison {type(op_node).__name__} not allowed")
    return fn(left, right)


def evaluate(expression: str, values: dict[str, float],
             tolerance: float = 0.0) -> bool:
    """True when the comparison holds. Raises ExpressionError otherwise."""
    if not isinstance(expression, str) or not expression.strip():
        raise ExpressionError("expression must be a non-empty string")
    if len(expression) > _MAX_LEN:
        raise ExpressionError("expression too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"cannot parse expression: {exc}") from exc

    node = tree.body
    if not isinstance(node, ast.Compare):
        raise ExpressionError("expression must be a comparison")
    left = _number(node.left, values)
    for op, comparator in zip(node.ops, node.comparators):
        right = _number(comparator, values)
        if not _compare(op, left, right, tolerance):
            return False
        left = right
    return True
