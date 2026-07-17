"""Validate a vendor-decision report without credentials or network access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from trader.data.alpaca_rights_gate import (
    AlpacaRightsGateError,
    load_passing_alpaca_rights_decision,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Alpaca written-rights evidence.")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        evidence = load_passing_alpaca_rights_decision(args.report)
    except AlpacaRightsGateError as exc:
        print(f"Alpaca rights validation failed closed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "report_path": evidence.report_path.as_posix(),
                "report_sha256": evidence.report_sha256,
                "selected_vendor": evidence.selected_vendor,
                "report_timestamp": evidence.report_timestamp,
                "credentials_read": False,
                "network_accessed": False,
                "broker_contacted": False,
                "order_api_invoked": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
