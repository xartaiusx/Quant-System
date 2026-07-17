from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import exchange_calendars as xcals  # type: ignore[import-untyped]
from scripts.plan_alpaca_spy_eod import build_eod_plan

from trader.data.alpaca_acquisition import (
    HttpResponse,
    SessionDataRequest,
    acquire_spy_session,
)
from trader.data.alpaca_session_compare import compare_alpaca_sessions
from trader.models import AlpacaSessionCompareRequest
from trader.reporting.journal import Journal


def _capture(output_root: Path, session_date: date, *, acquired_at: datetime) -> Path:
    bars = [
        {
            "t": value.to_pydatetime().astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "o": 500,
            "h": 501,
            "l": 499,
            "c": 500.5,
            "v": 1000,
            "n": 20,
            "vw": 500.25,
        }
        for value in xcals.get_calendar("XNYS").session_minutes(session_date)
    ]
    response = HttpResponse(
        status=200,
        headers={},
        body=json.dumps({"bars": bars, "symbol": "SPY"}).encode(),
    )
    result = acquire_spy_session(
        SessionDataRequest(
            symbol="SPY",
            feed="sip",
            timeframe="1Min",
            session_date=session_date,
            output_root=output_root,
        ),
        api_key_id="key",
        api_secret_key="secret",
        transport=lambda _url, _headers: response,
        now=lambda: acquired_at,
        sleep=lambda _: None,
        monotonic=lambda: 100.0,
    )
    return Path(result.manifest_paths[0])


def test_eod_plan_backfills_all_missing_xnys_sessions(tmp_path: Path) -> None:
    calendar = xcals.get_calendar("XNYS")
    latest = date(2025, 1, 8)
    now = calendar.session_close(latest).to_pydatetime() + timedelta(minutes=20)

    plan = build_eod_plan(
        tmp_path / "market-data",
        capture_start_date=date(2025, 1, 2),
        now=now,
    )

    assert plan["latest_completed_session"] == "2025-01-08"
    assert plan["missing_sessions"] == [
        "2025-01-02",
        "2025-01-03",
        "2025-01-06",
        "2025-01-07",
        "2025-01-08",
    ]
    assert plan["capture_sessions"] == plan["missing_sessions"]
    assert "2025-01-04" not in plan["capture_sessions"]
    assert plan["network_accessed"] is False
    assert plan["broker_contacted"] is False


def test_eod_plan_reacquires_prior_two_once_per_latest_session(tmp_path: Path) -> None:
    output_root = tmp_path / "market-data"
    calendar = xcals.get_calendar("XNYS")
    latest = date(2025, 1, 8)
    latest_close = calendar.session_close(latest).to_pydatetime()
    initial_acquisition = datetime(2025, 1, 8, 12, tzinfo=UTC)
    sessions = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6), date(2025, 1, 7)]
    for session in sessions:
        _capture(output_root, session, acquired_at=initial_acquisition)
    _capture(output_root, latest, acquired_at=latest_close + timedelta(minutes=20))

    before = build_eod_plan(
        output_root,
        capture_start_date=date(2025, 1, 2),
        now=latest_close + timedelta(minutes=20),
    )
    assert before["missing_sessions"] == []
    assert before["correction_sessions_due"] == ["2025-01-07", "2025-01-06"]

    after_cutoff = latest_close + timedelta(minutes=21)
    _capture(output_root, date(2025, 1, 6), acquired_at=after_cutoff)
    _capture(output_root, date(2025, 1, 7), acquired_at=after_cutoff)
    after = build_eod_plan(
        output_root,
        capture_start_date=date(2025, 1, 2),
        now=after_cutoff,
    )
    assert after["correction_sessions_due"] == []
    assert after["capture_sessions"] == []
    pairs = {item["session_date"] for item in after["compare_pairs"]}
    assert {"2025-01-06", "2025-01-07"} <= pairs

    for pair in after["compare_pairs"]:
        report = compare_alpaca_sessions(
            AlpacaSessionCompareRequest(
                baseline_manifest_path=pair["baseline_manifest"],
                candidate_manifest_path=pair["candidate_manifest"],
            )
        )
        Journal(
            output_root
            / "orchestration"
            / "comparisons"
            / pair["session_date"]
        ).write_cycle("alpaca_session_compare", report.model_dump(mode="json"))
    completed = build_eod_plan(
        output_root,
        capture_start_date=date(2025, 1, 2),
        now=after_cutoff,
    )
    assert completed["compare_pairs"] == []


def test_eod_plan_uses_early_close_and_close_plus_twenty(tmp_path: Path) -> None:
    session = date(2025, 11, 28)
    close = xcals.get_calendar("XNYS").session_close(session).to_pydatetime()
    just_before = close + timedelta(minutes=20) - timedelta(microseconds=1)
    plan_before = build_eod_plan(
        tmp_path / "before",
        capture_start_date=date(2025, 11, 26),
        now=just_before,
    )
    plan_after = build_eod_plan(
        tmp_path / "after",
        capture_start_date=date(2025, 11, 26),
        now=close + timedelta(minutes=20),
    )
    assert plan_before["latest_completed_session"] == "2025-11-26"
    assert plan_after["latest_completed_session"] == "2025-11-28"


def test_eod_plan_rejects_skeletal_completed_comparison(tmp_path: Path) -> None:
    output_root = tmp_path / "market-data"
    session = date(2025, 1, 8)
    close = xcals.get_calendar("XNYS").session_close(session).to_pydatetime()
    _capture(output_root, session, acquired_at=close + timedelta(minutes=20))
    _capture(output_root, session, acquired_at=close + timedelta(minutes=21))
    now = close + timedelta(minutes=22)

    initial = build_eod_plan(
        output_root,
        capture_start_date=session,
        now=now,
    )
    pair = initial["compare_pairs"][0]
    reports_dir = output_root / "orchestration" / "comparisons" / session.isoformat()
    reports_dir.mkdir(parents=True)
    (reports_dir / "alpaca_session_compare_forged.json").write_text(
        json.dumps(
            {
                "ok": True,
                "request": {
                    "baseline_manifest_path": pair["baseline_manifest"],
                    "candidate_manifest_path": pair["candidate_manifest"],
                },
                "symbol": "SPY",
                "session_date": session.isoformat(),
                "parameters_compatible": True,
                "baseline_manifest_sha256": pair["baseline_manifest_sha256"],
                "candidate_manifest_sha256": pair["candidate_manifest_sha256"],
                "final_status": "identical",
                "timestamp": now.isoformat(),
            }
        ),
        encoding="utf-8",
    )

    replanned = build_eod_plan(
        output_root,
        capture_start_date=session,
        now=now,
    )

    assert len(replanned["compare_pairs"]) == 1
    assert replanned["compare_pairs"][0]["session_date"] == session.isoformat()
