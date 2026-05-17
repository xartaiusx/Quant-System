from __future__ import annotations


def test_cli_imports_successfully() -> None:
    import trader.cli as cli

    assert cli.app is not None
