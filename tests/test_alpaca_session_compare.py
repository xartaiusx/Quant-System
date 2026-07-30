from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, date, timedelta
from decimal import Decimal
from pathlib import Path

import exchange_calendars as xcals  # type: ignore[import-untyped]

from trader import alpaca_session_compare_cli as compare_cli
from trader.data import alpaca_session_compare as compare_module
from trader.data.alpaca_acquisition import (
    HttpResponse,
    SessionDataRequest,
    acquire_spy_session,
)
from trader.data.alpaca_session_artifacts import LoadedAlpacaSession
from trader.data.alpaca_session_compare import compare_alpaca_sessions
from trader.models import (
    AlpacaSessionCompareRequest,
    AlpacaSessionCompareStatus,
)
from trader.reporting.reports import markdown_summary


def _bars(session_date: date, *, first_close: float = 500.5) -> list[dict[str, object]]:
    bars = []
    for index, value in enumerate(xcals.get_calendar("XNYS").session_minutes(session_date)):
        bars.append(
            {
                "t": value.to_pydatetime().astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "o": 500,
                "h": 501,
                "l": 499,
                "c": first_close if index == 0 else 500.5,
                "v": 1000 + index,
                "n": 20 + index,
                "vw": 500.25,
            }
        )
    return bars


def _capture(tmp_path: Path, slug: str, session_date: date, *, first_close: float) -> Path:
    close = xcals.get_calendar("XNYS").session_close(session_date).to_pydatetime()
    response = HttpResponse(
        status=200,
        headers={},
        body=json.dumps(
            {"bars": _bars(session_date, first_close=first_close), "symbol": "SPY"},
            separators=(",", ":"),
        ).encode(),
    )
    result = acquire_spy_session(
        SessionDataRequest(
            symbol="SPY",
            feed="sip",
            timeframe="1Min",
            session_date=session_date,
            output_root=tmp_path / slug,
        ),
        api_key_id="key",
        api_secret_key="secret",
        transport=lambda _url, _headers: response,
        now=lambda: close + timedelta(days=2),
        sleep=lambda _: None,
        monotonic=lambda: 100.0,
    )
    return Path(result.manifest_paths[0])


def _request(baseline: Path, candidate: Path) -> AlpacaSessionCompareRequest:
    return AlpacaSessionCompareRequest(
        baseline_manifest_path=baseline.as_posix(),
        candidate_manifest_path=candidate.as_posix(),
    )


def test_identical_and_revised_session_comparisons(tmp_path: Path) -> None:
    session_date = date(2025, 1, 2)
    baseline = _capture(tmp_path, "baseline", session_date, first_close=500.5)
    identical = _capture(tmp_path, "identical", session_date, first_close=500.5)
    revised = _capture(tmp_path, "revised", session_date, first_close=500.75)

    identical_report = compare_alpaca_sessions(_request(baseline, identical))
    revised_report = compare_alpaca_sessions(_request(baseline, revised))

    assert identical_report.ok is True
    assert identical_report.final_status == AlpacaSessionCompareStatus.IDENTICAL
    assert identical_report.matching_bar_count == 390
    assert revised_report.ok is True
    assert revised_report.final_status == AlpacaSessionCompareStatus.REVISED
    assert revised_report.revised_bar_count == 1
    assert revised_report.revisions[0].classification == "revised"
    assert revised_report.revisions[0].changed_fields == ["c"]
    assert revised_report.network_accessed is False
    assert revised_report.broker_contacted is False
    assert revised_report.order_api_invoked is False


def test_different_sessions_are_incompatible(tmp_path: Path) -> None:
    baseline = _capture(tmp_path, "baseline", date(2025, 1, 2), first_close=500.5)
    candidate = _capture(tmp_path, "candidate", date(2025, 1, 3), first_close=500.5)

    report = compare_alpaca_sessions(_request(baseline, candidate))

    assert report.ok is False
    assert report.final_status == AlpacaSessionCompareStatus.INCOMPATIBLE
    assert any("session_date" in error for error in report.errors)


def test_checksum_drift_fails_closed(tmp_path: Path) -> None:
    session_date = date(2025, 1, 2)
    baseline = _capture(tmp_path, "baseline", session_date, first_close=500.5)
    candidate = _capture(tmp_path, "candidate", session_date, first_close=500.5)
    manifest = json.loads(candidate.read_text(encoding="utf-8"))
    data_path = candidate.parent / manifest["data_file"]
    data_path.write_bytes(data_path.read_bytes() + b"drift")

    report = compare_alpaca_sessions(_request(baseline, candidate))

    assert report.ok is False
    assert report.final_status == AlpacaSessionCompareStatus.FAILED
    assert "checksum mismatch" in report.errors[0]


def test_comparison_classifies_missing_and_added_bars(monkeypatch, tmp_path: Path) -> None:
    shared_manifest = {
        "source": "alpaca_sip",
        "capture_mode": "session",
        "session_calendar": "XNYS",
        "session_date": "2025-01-02",
        "session_open": "2025-01-02T14:30:00Z",
        "session_close": "2025-01-02T21:00:00Z",
        "last_minute_start": "2025-01-02T20:59:00Z",
        "expected_bar_count": 390,
        "expected_timestamp_sha256": "hash",
        "acquired_at": "2025-01-03T00:00:00Z",
        "data_sha256": "data",
        "request": {
            "symbol": "SPY",
            "feed": "sip",
            "timeframe": "1Min",
            "adjustment": "raw",
            "sort": "asc",
            "start": "2025-01-02T14:30:00Z",
            "end": "2025-01-02T20:59:00Z",
        },
    }
    values = {
        "o": Decimal("500"),
        "h": Decimal("501"),
        "l": Decimal("499"),
        "c": Decimal("500.5"),
        "v": 1000,
        "n": 20,
        "vw": Decimal("500.25"),
    }
    baseline = LoadedAlpacaSession(
        tmp_path / "baseline.json",
        "baseline-hash",
        dict(shared_manifest),
        [],
        {"2025-01-02T14:30:00Z": values, "2025-01-02T14:31:00Z": values},
    )
    candidate = LoadedAlpacaSession(
        tmp_path / "candidate.json",
        "candidate-hash",
        dict(shared_manifest),
        [],
        {"2025-01-02T14:31:00Z": values, "2025-01-02T14:32:00Z": values},
    )
    monkeypatch.setattr(
        compare_module,
        "load_alpaca_session",
        lambda path: baseline if path.name.startswith("baseline") else candidate,
    )

    report = compare_alpaca_sessions(
        AlpacaSessionCompareRequest(
            baseline_manifest_path="baseline.json",
            candidate_manifest_path="candidate.json",
        )
    )

    assert report.missing_bar_count == 1
    assert report.added_bar_count == 1
    assert {item.classification for item in report.revisions} == {"missing", "added"}


def test_markdown_and_cli_write_offline_evidence(tmp_path: Path, monkeypatch, capsys) -> None:
    session_date = date(2025, 1, 2)
    baseline = _capture(tmp_path, "baseline", session_date, first_close=500.5)
    candidate = _capture(tmp_path, "candidate", session_date, first_close=500.75)
    report = compare_alpaca_sessions(_request(baseline, candidate))
    rendered = markdown_summary(report.model_dump(mode="json"))
    assert "# Alpaca Session Comparison" in rendered
    assert "Revised bars: `1`" in rendered
    assert "Network accessed: `False`" in rendered

    monkeypatch.chdir(tmp_path)
    exit_code = compare_cli.main(
        [
            "--baseline-manifest",
            baseline.as_posix(),
            "--candidate-manifest",
            candidate.as_posix(),
            "--reports-dir",
            (tmp_path / "reports").as_posix(),
        ],
    )
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["network_accessed"] is False
    assert list((tmp_path / "reports").glob("alpaca_session_compare_*.json"))


def test_offline_artifact_and_compare_modules_have_no_network_or_order_path() -> None:
    for source_path in (
        Path("src/trader/data/alpaca_session_artifacts.py"),
        Path("src/trader/data/alpaca_session_compare.py"),
        Path("src/trader/alpaca_session_compare_cli.py"),
    ):
        source = source_path.read_text(encoding="utf-8")
        for forbidden in (
            "urllib",
            "httpx",
            "requests",
            "trader.broker",
            "trader.execution",
            "placeOrder",
            "cancelOrder",
            "reqGlobalCancel",
        ):
            assert forbidden not in source

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import trader.alpaca_session_compare_cli; "
                "bad=[name for name in sys.modules if name == 'ibapi' or "
                "name.startswith('ibapi.') or name.startswith('trader.broker') or "
                "name.startswith('trader.execution')]; "
                "print('\\n'.join(bad)); raise SystemExit(bool(bad))"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr
