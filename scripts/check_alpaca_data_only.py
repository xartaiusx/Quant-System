"""Enforce that the Alpaca integration remains historical-data-only."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_FILES = (
    Path("src/trader/alpaca_session_compare_cli.py"),
    Path("src/trader/data/alpaca_acquisition.py"),
    Path("src/trader/data/alpaca_rights_gate.py"),
    Path("src/trader/data/alpaca_session_artifacts.py"),
    Path("src/trader/data/alpaca_session_compare.py"),
    Path("scripts/acquire_alpaca_spy.py"),
    Path("scripts/plan_alpaca_spy_eod.py"),
    Path("scripts/validate_alpaca_rights.py"),
    Path("scripts/run-alpaca-spy-eod.ps1"),
    Path("scripts/manage-alpaca-spy-eod-task.ps1"),
    Path("scripts/set-alpaca-spy-credentials.ps1"),
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
    acquisition_path = Path("src/trader/data/alpaca_acquisition.py")
    acquisition = acquisition_path.read_text(encoding="utf-8") if acquisition_path.is_file() else ""
    if 'ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"' not in acquisition:
        errors.append("Alpaca acquisition must pin the official market-data host")
    if 'ALPACA_BARS_PATH = "/v2/stocks/SPY/bars"' not in acquisition:
        errors.append("Alpaca acquisition must pin the SPY historical bars endpoint")
    if "_FailClosedRedirectHandler" not in acquisition or "build_opener" not in acquisition:
        errors.append("Alpaca acquisition must reject HTTP redirects before forwarding headers")
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import trader.alpaca_session_compare_cli; "
                "bad=[name for name in sys.modules if name == 'ibapi' or "
                "name.startswith('ibapi.') or name.startswith('trader.broker') or "
                "name.startswith('trader.execution')]; raise SystemExit(bool(bad))"
            ),
        ],
        check=False,
    )
    if probe.returncode != 0:
        errors.append("Alpaca session comparison entrypoint imported broker/order modules")
    if errors:
        print("Alpaca data-only safety violations:\n" + "\n".join(errors))
        return 1
    print("Alpaca integration is pinned to historical SPY market data only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
