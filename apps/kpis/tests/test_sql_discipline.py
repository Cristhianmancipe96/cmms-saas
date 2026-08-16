"""The rule that cannot be enforced by review alone: no SQL is ever built.

A reviewer reading `queries.py` today sees eight hand-written statements with
bound parameters. The risk is the fourteenth query, written in a hurry in six
months, that interpolates a sort column or a LIMIT "because it is not user
input". This test parses the module and refuses that shape outright, so the
mistake fails the build instead of the audit.

It checks the *syntax tree*, not the text: a grep for "f\"" is fooled by a
string that contains one, and misses `"…" % params` and `.format()`.
"""

import ast
import inspect
from pathlib import Path

from django.test import SimpleTestCase

from apps.kpis import queries

SOURCE = Path(inspect.getfile(queries)).read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _sql_constants() -> dict[str, ast.expr]:
    """Every module-level `SQL_* = …` assignment, as its raw AST node."""
    found = {}
    for node in TREE.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.startswith("SQL_"):
                    found[target.id] = node.value
    return found


class SqlIsNeverBuiltTests(SimpleTestCase):
    def test_there_are_query_constants_to_check(self):
        """Guards the guard: a renamed prefix would make every other test in
        this file pass by checking nothing at all."""
        assert len(_sql_constants()) >= 6

    def test_every_query_is_a_plain_string_literal(self):
        for name, value in _sql_constants().items():
            with self.subTest(query=name):
                assert isinstance(value, ast.Constant), f"{name} is assembled, not written"
                assert isinstance(value.value, str)

    def test_the_module_contains_no_f_strings(self):
        offenders = [node for node in ast.walk(TREE) if isinstance(node, ast.JoinedStr)]

        assert offenders == []

    def test_the_module_never_formats_or_concatenates_a_string(self):
        """`%`, `+` and `.format()` on anything in this module. There is no
        legitimate use for them here: every value travels as a parameter."""
        for node in ast.walk(TREE):
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
                self.fail(f"string arithmetic at line {node.lineno}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"format", "format_map", "join"}, (
                    f".{node.func.attr}() on a string at line {node.lineno}"
                )

    def test_execute_is_always_called_with_parameters(self):
        """`cursor.execute(sql)` with the values already inside the string is
        the exact shape this whole file exists to prevent."""
        calls = [
            node
            for node in ast.walk(TREE)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
        ]

        assert calls, "no cursor.execute() found — has the module moved?"
        for call in calls:
            assert len(call.args) == 2, f"execute() without params at line {call.lineno}"


class EveryQueryIsScopedTests(SimpleTestCase):
    def test_each_query_filters_by_company(self):
        """`company_id = %s` in every statement, including the ones that only
        touch work orders. There is no manager behind a cursor."""
        for name, node in _sql_constants().items():
            with self.subTest(query=name):
                assert "company_id = %s" in node.value

    def test_each_ratio_guards_its_denominator(self):
        """Every query that divides does it through NULLIF: an empty period
        must render «—», never a 500."""
        for name, node in _sql_constants().items():
            with self.subTest(query=name):
                # Comment lines are prose — «abierta/asignada» is not a
                # division, and reading it as one would demand a NULLIF that
                # protects nothing.
                statement = "\n".join(
                    line for line in node.value.splitlines() if not line.strip().startswith("--")
                )
                if "/" not in statement:
                    continue
                # AVG() is the other honest answer: over zero rows it is NULL,
                # not an error, so it needs no explicit guard.
                assert "NULLIF" in node.value or "AVG(" in node.value, (
                    f"{name} divides without a zero guard"
                )
