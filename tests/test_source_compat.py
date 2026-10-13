"""Python 3.12 accepts f-string syntax that 3.10/3.11 reject; the app must run on 3.10+.
This catches the problem even when the tests themselves run on 3.12."""
import ast
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def find_fstring_problems(source: str) -> list[str]:
    problems = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FormattedValue):
            seg = ast.get_source_segment(source, node.value) or ""
            if "\\" in seg:
                problems.append(f"line {node.value.lineno}: backslash inside an f-string expression: {seg!r}")
    return problems


def test_checker_detects_the_known_bug():
    bad = "x = f\"{a.split(' \\u2014 ')[0]}\"\n"
    if sys.version_info < (3, 12):
        with pytest.raises(SyntaxError):   # this interpreter itself rejects the bad code: the bug is visible
            ast.parse(bad)
    else:
        assert find_fstring_problems(bad)
    assert not find_fstring_problems("sep = ' \\u2014 '\nx = f\"{a.split(sep)[0]}\"\n")


def test_no_py312_only_fstrings_in_project():
    problems = []
    for path in list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").rglob("*.py")):
        for p in find_fstring_problems(path.read_text(encoding="utf-8")):
            problems.append(f"{path.relative_to(ROOT)} {p}")
    assert not problems, "\n".join(problems)
