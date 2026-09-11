import ast
from pathlib import Path


def test_domain_and_application_do_not_import_infrastructure():
    for root in (Path("src/trading_bot/domain"), Path("src/trading_bot/application")):
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = [
                node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            ]
            assert not any(name.startswith("trading_bot.infrastructure") for name in imported)


def test_source_contains_no_exchange_or_network_client():
    forbidden = ("import requests", "import httpx", "import socket", "import ccxt", "import okx")
    source = "\n".join(
        path.read_text(encoding="utf-8").lower() for path in Path("src").rglob("*.py")
    )
    assert not any(token in source for token in forbidden)
