"""Build a broker-free EOD SPY capture plan from immutable session manifests."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import exchange_calendars as xcals  # type: ignore[import-untyped]

from trader.data.alpaca_session_artifacts import (
    AlpacaSessionArtifactError,
    discover_valid_session_manifests,
    load_alpaca_session,
)
from trader.data.alpaca_session_compare import compare_alpaca_sessions
from trader.models import AlpacaSessionCompareReport


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan unattended Alpaca SPY EOD capture.")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--capture-start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--now", type=datetime.fromisoformat)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    now = args.now or datetime.now(UTC)
    if now.tzinfo is None:
        print("EOD planning failed closed: --now must include a timezone", file=sys.stderr)
        return 1
    try:
        payload = build_eod_plan(
            args.output_root,
            capture_start_date=args.capture_start_date,
            now=now,
        )
    except (OSError, ValueError, AlpacaSessionArtifactError) as exc:
        print(f"EOD planning failed closed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def build_eod_plan(
    output_root: Path,
    *,
    capture_start_date: date,
    now: datetime,
) -> dict[str, object]:
    """Return missing sessions, bounded correction recaptures, and compare pairs."""

    if capture_start_date < date(2016, 1, 1):
        raise ValueError("capture start date must be on or after 2016-01-01")
    calendar = xcals.get_calendar("XNYS")
    latest = _latest_completed_session(calendar, now=now)
    if capture_start_date > latest:
        raise ValueError("capture start date follows the latest completed XNYS session")
    required = [
        value.date()
        for value in calendar.sessions_in_range(capture_start_date, latest)
    ]
    manifests = discover_valid_session_manifests(output_root)
    missing = [session for session in required if not manifests.get(session)]
    correction_candidates: list[date] = []
    cursor = latest
    for _ in range(2):
        cursor = calendar.previous_session(cursor).date()
        if cursor >= capture_start_date:
            correction_candidates.append(cursor)
    latest_close = calendar.session_close(latest).to_pydatetime().astimezone(UTC)
    correction_cutoff = latest_close + timedelta(minutes=20)
    corrections_due = [
        session
        for session in correction_candidates
        if _newest_acquired_at(manifests.get(session, [])) < correction_cutoff
    ]
    capture_dates = sorted(set(missing) | set(corrections_due))
    compare_pairs = []
    for session, paths in manifests.items():
        if len(paths) < 2:
            continue
        baseline = load_alpaca_session(paths[-2])
        candidate = load_alpaca_session(paths[-1])
        if _completed_comparison_exists(
            output_root,
            session_date=session,
            baseline_manifest_path=baseline.manifest_path,
            candidate_manifest_path=candidate.manifest_path,
            baseline_sha256=baseline.manifest_sha256,
            candidate_sha256=candidate.manifest_sha256,
        ):
            continue
        compare_pairs.append(
            {
                "session_date": session.isoformat(),
                "baseline_manifest": paths[-2].as_posix(),
                "candidate_manifest": paths[-1].as_posix(),
                "baseline_manifest_sha256": baseline.manifest_sha256,
                "candidate_manifest_sha256": candidate.manifest_sha256,
            }
        )
    all_manifest_paths = list(
        output_root.expanduser().resolve().glob(
            "symbol=SPY/session_date=*/runs/*/acquisition_manifest.json"
        )
    )
    valid_paths = {path.resolve() for paths in manifests.values() for path in paths}
    invalid_paths = sorted(
        path.resolve().as_posix()
        for path in all_manifest_paths
        if path.resolve() not in valid_paths
    )
    return {
        "plan_version": 1,
        "source": "alpaca_sip",
        "symbol": "SPY",
        "session_calendar": "XNYS",
        "capture_start_date": capture_start_date.isoformat(),
        "latest_completed_session": latest.isoformat(),
        "required_session_count": len(required),
        "valid_session_count": sum(session in manifests for session in required),
        "missing_sessions": [value.isoformat() for value in missing],
        "correction_sessions_due": [value.isoformat() for value in corrections_due],
        "capture_sessions": [value.isoformat() for value in capture_dates],
        "compare_pairs": compare_pairs,
        "invalid_manifest_paths": invalid_paths,
        "credentials_read": False,
        "network_accessed": False,
        "broker_contacted": False,
        "submitted_orders": False,
        "paper_orders_enabled": False,
        "order_api_invoked": False,
        "catalog_activated": False,
        "research_eligible": False,
        "promotion_eligible": False,
        "graduation_eligible": False,
    }


def _latest_completed_session(calendar, *, now: datetime) -> date:
    now_utc = now.astimezone(UTC)
    start = now_utc.date() - timedelta(days=14)
    candidates = calendar.sessions_in_range(start, now_utc.date())
    completed = [
        value.date()
        for value in candidates
        if calendar.session_close(value).to_pydatetime().astimezone(UTC)
        + timedelta(minutes=20)
        <= now_utc
    ]
    if not completed:
        raise ValueError("no completed XNYS session was found")
    return completed[-1]


def _newest_acquired_at(paths: list[Path]) -> datetime:
    if not paths:
        return datetime.min.replace(tzinfo=UTC)
    loaded = load_alpaca_session(paths[-1])
    value = datetime.fromisoformat(str(loaded.manifest["acquired_at"]).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise AlpacaSessionArtifactError("acquired_at must include a timezone")
    return value.astimezone(UTC)


def _completed_comparison_exists(
    output_root: Path,
    *,
    session_date: date,
    baseline_manifest_path: Path,
    candidate_manifest_path: Path,
    baseline_sha256: str,
    candidate_sha256: str,
) -> bool:
    reports_dir = (
        output_root.expanduser().resolve()
        / "orchestration"
        / "comparisons"
        / session_date.isoformat()
    )
    for path in reports_dir.glob("alpaca_session_compare_*.json"):
        try:
            report = AlpacaSessionCompareReport.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue
        try:
            request_paths_match = (
                Path(report.request.baseline_manifest_path).expanduser().resolve()
                == baseline_manifest_path.resolve()
                and Path(report.request.candidate_manifest_path).expanduser().resolve()
                == candidate_manifest_path.resolve()
            )
        except OSError:
            continue
        if not request_paths_match:
            continue
        canonical = compare_alpaca_sessions(report.request, now=report.timestamp)
        if canonical != report:
            continue
        if (
            report.ok
            and report.parameters_compatible
            and report.baseline_manifest_sha256 == baseline_sha256
            and report.candidate_manifest_sha256 == candidate_sha256
            and str(report.final_status) in {"identical", "revised"}
        ):
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
