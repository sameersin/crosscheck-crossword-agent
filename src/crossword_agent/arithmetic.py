"""Exact, bounded arithmetic for numeric crossword clues; no model call required.

Only integer literals, parentheses, unary signs, and +, -, *, / are accepted.
AST nodes are interpreted through an explicit allowlist, never executed as code.
Fraction arithmetic avoids floating-point rounding and rejects noninteger final
answers. Unsupported clues are omitted so the caller can handle them explicitly.
"""

import ast
import re
from fractions import Fraction

from .domain import Entry
from .models import Candidate

_MAX_SOURCE_LENGTH = 256
_MAX_AST_NODES = 96
_MAX_DEPTH = 20
_MAX_LITERAL = 10**25 - 1
_MAX_INTERMEDIATE = 10**50 - 1
_SYMBOLS = str.maketrans({"×": "*", "÷": "/", "−": "-", "–": "-", "—": "-"})
_EXPRESSION_CHARACTERS = re.compile(r"[0-9+*/()\-\s]+", flags=re.ASCII)


def _bounded(value: Fraction) -> Fraction:
    if abs(value.numerator) > _MAX_INTERMEDIATE or value.denominator > _MAX_INTERMEDIATE:
        raise ValueError("Arithmetic intermediate exceeds the supported bound.")
    return value


def _interpret(node: ast.AST, depth: int = 0) -> Fraction:
    if depth > _MAX_DEPTH:
        raise ValueError("Arithmetic nesting exceeds the supported bound.")
    if isinstance(node, ast.Constant) and type(node.value) is int:
        if abs(node.value) > _MAX_LITERAL:
            raise ValueError("Integer literal exceeds the supported bound.")
        return Fraction(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _interpret(node.operand, depth + 1)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        left, right = _interpret(node.left, depth + 1), _interpret(node.right, depth + 1)
        if isinstance(node.op, ast.Add):
            return _bounded(left + right)
        if isinstance(node.op, ast.Sub):
            return _bounded(left - right)
        if isinstance(node.op, ast.Mult):
            return _bounded(left * right)
        return _bounded(left / right)
    raise ValueError("Unsupported arithmetic expression.")


def _integer_answer(clue: str) -> str | None:
    if not clue or len(clue) > _MAX_SOURCE_LENGTH:
        return None
    expression = clue.translate(_SYMBOLS).strip()
    if not _EXPRESSION_CHARACTERS.fullmatch(expression):
        return None
    try:
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > _MAX_AST_NODES:
            return None
        value = _interpret(tree.body)
        if value.denominator != 1 or value.numerator < 0:
            return None
        return str(value.numerator)
    except (SyntaxError, ValueError, ArithmeticError, RecursionError):
        return None


def evaluate_expression(clue: str) -> str | None:
    """Return a bounded nonnegative integer result, or None for unsupported expressions."""
    return _integer_answer(clue)


def arithmetic_candidates(entries: list[Entry]) -> dict[str, list[Candidate]]:
    """Return one exact candidate for each supported, correctly sized digit clue.

    Missing IDs mean the clue is unsupported, unsafe, nonintegral, negative, or
    does not fit its entry. Leading zeroes are never invented to pad an answer.
    """
    candidates: dict[str, list[Candidate]] = {}
    for entry in entries:
        if entry.answer_type != "digits":
            continue
        answer = _integer_answer(entry.clue)
        if answer is not None and len(answer) == entry.length:
            candidates[entry.id] = [Candidate(answer=answer, score=1.0)]
    return candidates
