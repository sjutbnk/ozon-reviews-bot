import ast
from pathlib import Path


def _calls(tree, name):
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == name]


def test_polling_starts_before_ozon_initialization():
    tree = ast.parse(Path('main.py').read_text())
    polling = _calls(tree, 'start_polling')[0].lineno
    ozon_start = [n for n in _calls(tree, 'start') if isinstance(n.func.value, ast.Name) and n.func.value.id == 'ozon'][0].lineno
    assert polling < ozon_start
