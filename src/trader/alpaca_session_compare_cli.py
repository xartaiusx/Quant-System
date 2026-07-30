"""Broker-free command line entrypoint for Alpaca session comparison."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from trader.data.alpaca_session_compare import compare_alpaca_sessions
from trader.models import AlpacaSessionCompareRequest
from trader.reporting.reports import markdown_summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alpaca-session-compare",
        description="Compare two immutable Alpaca SPY sessions entirely offline.",
    )
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = compare_alpaca_sessions(
        AlpacaSessionCompareRequest(
            baseline_manifest_path=args.baseline_manifest.as_posix(),
            candidate_manifest_path=args.candidate_manifest.as_posix(),
        )
    )
    payload = json.loads(report.model_dump_json())
    json_path, markdown_path = _write_immutable_reports(args.reports_dir, payload)
    print(
        json.dumps(
            {
                "ok": report.ok,
                "final_status": report.final_status,
                "json_report_path": json_path.resolve().as_posix(),
                "markdown_report_path": markdown_path.resolve().as_posix(),
                "network_accessed": False,
                "broker_contacted": False,
                "order_api_invoked": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report.ok else 1


def _write_immutable_reports(
    reports_dir: Path,
    payload: dict[str, object],
) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    slug = (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        + "_"
        + uuid4().hex[:8]
    )
    json_path = reports_dir / f"alpaca_session_compare_{slug}.json"
    markdown_path = reports_dir / f"alpaca_session_compare_{slug}.md"
    with json_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    with markdown_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(markdown_summary(payload))
    return json_path, markdown_path


if __name__ == "__main__":
    raise SystemExit(main())
