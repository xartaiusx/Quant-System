"""Acquire historical Alpaca SIP data without broker or execution integration."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from trader.data.alpaca_acquisition import (
    AcquisitionError,
    HistoricalDataRequest,
    SessionDataRequest,
    acquire_historical_spy,
    acquire_spy_session,
    acquisition_result_json,
    plan_monthly_partitions,
    session_plan_payload,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Acquire immutable, historical SPY SIP bars from Alpaca's data API."
    )
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--feed", default="sip")
    parser.add_argument("--timeframe", default="1Min")
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument(
        "--session-date",
        type=date.fromisoformat,
        help="Capture one exact completed XNYS regular session.",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Validate and print monthly ranges without reading credentials or using the network.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    session_mode = args.session_date is not None
    range_mode = args.start is not None or args.end is not None
    if session_mode and range_mode:
        parser.error("--session-date is mutually exclusive with --start/--end")
    if not session_mode and (args.start is None or args.end is None):
        parser.error("bulk mode requires both --start and --end")
    try:
        if session_mode:
            request = SessionDataRequest(
                symbol=args.symbol,
                feed=args.feed,
                timeframe=args.timeframe,
                session_date=args.session_date,
                output_root=args.output_root,
            )
            if args.plan_only:
                print(
                    json.dumps(
                        session_plan_payload(request, now=datetime.now(UTC)),
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0
            result = acquire_spy_session(
                request,
                api_key_id=os.environ.get("APCA_API_KEY_ID", ""),
                api_secret_key=os.environ.get("APCA_API_SECRET_KEY", ""),
            )
            print(acquisition_result_json(result))
            return 0

        request = HistoricalDataRequest(
            symbol=args.symbol,
            feed=args.feed,
            timeframe=args.timeframe,
            start=args.start,
            end=args.end,
            output_root=args.output_root,
        )
        if args.plan_only:
            plans = plan_monthly_partitions(request, now=datetime.now(UTC))
            print(
                json.dumps(
                    {
                        "source": "alpaca_sip",
                        "symbol": "SPY",
                        "feed": "sip",
                        "timeframe": "1Min",
                        "partition_count": len(plans),
                        "partitions": [
                            {"start": plan.start.isoformat(), "end": plan.end.isoformat()}
                            for plan in plans
                        ],
                        "credentials_read": False,
                        "network_accessed": False,
                        "research_eligible": False,
                        "rights_status": "written_rights_unverified",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        api_key_id = os.environ.get("APCA_API_KEY_ID", "")
        api_secret_key = os.environ.get("APCA_API_SECRET_KEY", "")
        result = acquire_historical_spy(
            request,
            api_key_id=api_key_id,
            api_secret_key=api_secret_key,
        )
        print(acquisition_result_json(result))
        return 0
    except AcquisitionError as exc:
        print(f"Acquisition failed closed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
