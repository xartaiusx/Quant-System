"""Enforce that the Alpaca integration remains historical-data-only."""

from __future__ import annotations

from pathlib import Path

_FILES = (
    Path("src/trader/data/alpaca_acquisition.py"),
    Path("scripts/acquire_alpaca_spy.py"),
)
_FORBIDDEN = (
    "api.alpaca.markets",
    "/v2/orders",
    "/v2/account",
    "submit_order",
    "cancel_order",
    "TradingClient",
    "trader.broker",
    "trader.execution",
    "placeOrder",
    "cancelOrder",
    "reqGlobalCancel",
    "--api-key",
    "--api-secret",
)


def main() -> int:
    errors: list[str] = []
    for path in _FILES:
        if not path.is_file():
            errors.append(f"missing Alpaca data-only path: {path.as_posix()}")
            continue
        source = path.read_text(encoding="utf-8")
        for forbidden in _FORBIDDEN:
            if forbidden in source:
                errors.append(f"{path.as_posix()}: forbidden text {forbidden!r}")
    acquisition = _FILES[0].read_text(encoding="utf-8") if _FILES[0].is_file() else ""
    if 'ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"' not in acquisition:
        errors.append("Alpaca acquisition must pin the official market-data host")
    if 'ALPACA_BARS_PATH = "/v2/stocks/SPY/bars"' not in acquisition:
        errors.append("Alpaca acquisition must pin the SPY historical bars endpoint")
    if errors:
        print("Alpaca data-only safety violations:\n" + "\n".join(errors))
        return 1
    print("Alpaca integration is pinned to historical SPY market data only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
