import pytest

from app.services.expression import ExpressionError, evaluate, names


def test_names_include_scopes_and_skip_function_names():
    assert names("abs(assets - prior.assets) / abs(prior.assets) <= 0.30") == ["assets", "prior.assets"]
    assert names("child.amount == parent.amount") == ["child.amount", "parent.amount"]


@pytest.mark.parametrize("expr,values,ok", [
    ("assets == liabilities + capital", {"assets": 50, "liabilities": 30, "capital": 20}, True),
    ("assets == liabilities + capital", {"assets": 50, "liabilities": 30, "capital": 25}, False),
    ("abs(a - prior.a) / abs(prior.a) <= 0.30", {"a": 130, "prior.a": 100}, True),
    ("abs(a - prior.a) / abs(prior.a) <= 0.30", {"a": 131, "prior.a": 100}, False),
    ("not (c > 0 and b == 'credit' and i == 0)", {"c": 5, "b": "Credit", "i": 0}, False),
    ("not (c > 0 and b == 'credit' and i == 0)", {"c": 5, "b": "cash", "i": 0}, True),
    ("inv <= max(nrv, 0)", {"inv": 5, "nrv": 6}, True),
])
def test_evaluate(expr, values, ok):
    assert evaluate(expr, values, 0.01) is ok


def test_equality_uses_tolerance():
    assert evaluate("a == b", {"a": 10.0, "b": 10.005}, 0.01)


@pytest.mark.parametrize("expr,values", [
    ("required fields present and confidence >= 0.5", {}),  # prose, not an expression
    ("__import__('os') == 1", {}),
    ("a.b == 1", {"a": 1}),
    ("a / b == 1", {"a": 1, "b": 0}),
    ("a + 'x' == 1", {"a": 1}),
    ("a == 'x'", {"a": 1}),
    ("a + 1", {"a": 1}),
    ("missing == 1", {}),
])
def test_rejects_unsafe_or_uncomputable(expr, values):
    with pytest.raises(ExpressionError):
        evaluate(expr, values)
