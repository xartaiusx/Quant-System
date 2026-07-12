from __future__ import annotations

import csv
import json
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]
from typer.testing import CliRunner

from trader.cli import app
from trader.data.research_bakeoff import run_research_data_bakeoff
from trader.reporting.reports import markdown_summary


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _minute_rows(session_date: date) -> list[dict[str, object]]:
    timestamps = [
        value.to_pydatetime().astimezone(UTC)
        for value in xcals.get_calendar("XNYS").session_minutes(session_date)
    ]
    return [
        {
            "ticker": "SPY",
            "volume": 1000 + index,
            "open": "500.00",
            "close": "500.01",
            "high": "500.02",
            "low": "499.99",
            "window_start": int(timestamp.timestamp() * 1_000_000_000),
            "transactions": 10,
        }
        for index, timestamp in enumerate(timestamps)
    ]


def _alpaca_minute_rows(session_date: date) -> list[dict[str, object]]:
    rows = _minute_rows(session_date)
    return [
        {
            **row,
            "timestamp": datetime.fromtimestamp(
                int(row["window_start"]) / 1_000_000_000,
                tz=UTC,
            ),
        }
        for row in rows
    ]


def _write_ibkr_five_minute_snapshot(path: Path, session_date: date) -> Path:
    minute_rows = _alpaca_minute_rows(session_date)
    eastern = ZoneInfo("America/New_York")
    bars = []
    for index in range(0, len(minute_rows), 5):
        group = minute_rows[index : index + 5]
        timestamp = group[0]["timestamp"]
        assert isinstance(timestamp, datetime)
        bars.append(
            {
                "symbol": "SPY",
                "timestamp": f"{timestamp.astimezone(eastern):%Y%m%d %H:%M:%S} US/Eastern",
                "open": "500.00",
                "high": "500.02",
                "low": "499.99",
                "close": "500.01",
                "volume": sum(int(row["volume"]) for row in group),
                "wap": "500.005",
                "bar_count": 50,
                "source": "ibkr",
                "duration": "1 D",
                "bar_size": "5 mins",
                "what_to_show": "TRADES",
                "use_rth": 1,
            }
        )
    path.write_text(
        "".join(json.dumps(bar, sort_keys=True) + "\n" for bar in bars),
        encoding="utf-8",
    )
    return path


def _passing_rights(vendor: str) -> dict[str, object]:
    return {
        "vendor": vendor,
        "evidence_reference": f"operator-reviewed-{vendor}-terms",
        "internal_storage_allowed": True,
        "cloud_backup_allowed": True,
        "automated_research_allowed": True,
        "model_training_allowed": True,
        "derived_data_allowed": True,
        "correction_replay_available": True,
        "paper_trading_use_allowed": True,
        "live_trading_use_allowed": True,
        "retention_after_termination_allowed": True,
        "derived_retention_after_termination_allowed": True,
    }


def _bar_rows(*, changed: bool = False) -> list[dict[str, object]]:
    return [
        {
            "symbol": "SPY",
            "timestamp": "2025-01-02",
            "open": "500.00",
            "high": "502.00",
            "low": "499.00",
            "close": "501.01" if changed else "501.00",
            "volume": "1000000",
        },
        {
            "symbol": "SPY",
            "timestamp": "2025-01-03",
            "open": "501.00",
            "high": "503.00",
            "low": "500.00",
            "close": "502.00",
            "volume": "1100000",
        },
    ]


def _passing_manifest(tmp_path: Path) -> Path:
    massive_normal = tmp_path / "massive-normal.csv"
    massive_early = tmp_path / "massive-early.csv"
    massive_daily = tmp_path / "massive-daily.csv"
    norgate_daily = tmp_path / "norgate-daily.csv"
    correction_before = tmp_path / "correction-before.csv"
    correction_after = tmp_path / "correction-after.csv"
    actions = tmp_path / "actions.csv"
    massive_fields = [
        "ticker",
        "volume",
        "open",
        "close",
        "high",
        "low",
        "window_start",
        "transactions",
    ]
    bar_fields = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]
    _write_csv(massive_normal, massive_fields, _minute_rows(date(2025, 11, 26)))
    _write_csv(massive_early, massive_fields, _minute_rows(date(2025, 11, 28)))
    _write_csv(massive_daily, bar_fields, _bar_rows())
    _write_csv(norgate_daily, bar_fields, _bar_rows())
    _write_csv(correction_before, bar_fields, _bar_rows())
    _write_csv(correction_after, bar_fields, _bar_rows(changed=True))
    _write_csv(
        actions,
        ["symbol", "ex_date", "event_type", "factor", "cash_amount", "currency", "revision"],
        [
            {
                "symbol": "SPY",
                "ex_date": "2025-03-21",
                "event_type": "dividend",
                "factor": "",
                "cash_amount": "1.70",
                "currency": "USD",
                "revision": "1",
            },
            {
                "symbol": "SPY",
                "ex_date": "2025-06-01",
                "event_type": "split",
                "factor": "2",
                "cash_amount": "",
                "currency": "USD",
                "revision": "synthetic-1",
            },
        ],
    )
    manifest = {
        "manifest_version": 1,
        "symbol": "SPY",
        "samples": [
            {
                "sample_id": "massive-normal",
                "vendor": "massive",
                "path": massive_normal.name,
                "kind": "minute_bars",
                "source_format": "massive_minute",
                "case_tags": ["normal_session"],
                "expected_rows": 390,
            },
            {
                "sample_id": "massive-early",
                "vendor": "massive",
                "path": massive_early.name,
                "kind": "minute_bars",
                "source_format": "massive_minute",
                "case_tags": ["early_close"],
                "expected_rows": 210,
            },
            {
                "sample_id": "massive-daily",
                "vendor": "massive",
                "path": massive_daily.name,
                "kind": "daily_bars",
                "source_format": "canonical_ohlcv",
                "case_tags": ["daily_overlap"],
            },
            {
                "sample_id": "norgate-daily",
                "vendor": "norgate",
                "path": norgate_daily.name,
                "kind": "daily_bars",
                "source_format": "canonical_ohlcv",
                "case_tags": ["daily_overlap"],
            },
            {
                "sample_id": "correction-before",
                "vendor": "massive",
                "path": correction_before.name,
                "kind": "daily_bars",
                "source_format": "canonical_ohlcv",
                "case_tags": ["correction_before"],
            },
            {
                "sample_id": "correction-after",
                "vendor": "massive",
                "path": correction_after.name,
                "kind": "daily_bars",
                "source_format": "canonical_ohlcv",
                "case_tags": ["correction_after"],
            },
            {
                "sample_id": "actions",
                "vendor": "norgate",
                "path": actions.name,
                "kind": "corporate_actions",
                "source_format": "canonical_actions",
                "case_tags": ["ex_dividend", "synthetic_split"],
            },
        ],
        "rights": [
            {
                "vendor": vendor,
                "evidence_reference": f"operator-reviewed-{vendor}-terms",
                "internal_storage_allowed": True,
                "cloud_backup_allowed": True,
                "automated_research_allowed": True,
                "model_training_allowed": True,
                "derived_data_allowed": True,
                "correction_replay_available": True,
                "paper_trading_use_allowed": True,
                "live_trading_use_allowed": True,
                "retention_after_termination_allowed": True,
                "derived_retention_after_termination_allowed": True,
            }
            for vendor in ("massive", "norgate")
        ],
    }
    manifest_path = tmp_path / "bakeoff.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_passing_bakeoff_is_procurement_ready(tmp_path: Path) -> None:
    report = run_research_data_bakeoff(_passing_manifest(tmp_path))

    assert report.ok is True
    assert report.final_status == "completed"
    assert report.missing_case_tags == []
    assert report.procurement_ready_vendors == ["massive", "norgate"]
    assert all(item.ok for item in report.sample_results)
    assert all(item.ok for item in report.comparisons)
    assert report.broker_contacted is False
    assert report.credentials_read is False
    assert report.network_accessed is False
    assert report.order_api_invoked is False


def test_bakeoff_fails_closed_on_rights_gap(tmp_path: Path) -> None:
    manifest_path = _passing_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["rights"][0]["retention_after_termination_allowed"] = False
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    report = run_research_data_bakeoff(manifest_path)

    assert report.ok is False
    assert report.rights_failed_vendors == ["massive"]
    assert "vendor rights evidence failed: massive" in report.errors


def test_bakeoff_maps_alpaca_sip_sample_but_still_requires_rights(tmp_path: Path) -> None:
    manifest_path = _passing_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    alpaca_path = tmp_path / "alpaca-sip-SPY-202511.json"
    alpaca_path.write_text(
        json.dumps(
            {
                "source": "alpaca_sip",
                "symbol": "SPY",
                "feed": "sip",
                "timeframe": "1Min",
                "adjustment": "raw",
                "sort": "asc",
                "bars": [
                    {
                        "t": row["timestamp"].isoformat().replace("+00:00", "Z"),
                        "o": row["open"],
                        "h": row["high"],
                        "l": row["low"],
                        "c": row["close"],
                        "v": row["volume"],
                        "n": row["transactions"],
                        "vw": "500.005",
                    }
                    for row in _alpaca_minute_rows(date(2025, 11, 26))
                ],
            }
        ),
        encoding="utf-8",
    )
    payload["samples"].append(
        {
            "sample_id": "alpaca-normal",
            "vendor": "alpaca_sip",
            "path": alpaca_path.name,
            "kind": "minute_bars",
            "source_format": "alpaca_sip_json",
            "case_tags": ["normal_session", "intraday_overlap"],
            "expected_rows": 390,
        }
    )
    ibkr_path = _write_ibkr_five_minute_snapshot(
        tmp_path / "ibkr-SPY-20251126.jsonl",
        date(2025, 11, 26),
    )
    payload["samples"].append(
        {
            "sample_id": "ibkr-normal",
            "vendor": "ibkr",
            "path": ibkr_path.name,
            "kind": "five_minute_bars",
            "source_format": "ibkr_snapshot_jsonl",
            "case_tags": ["normal_session", "intraday_overlap"],
            "expected_rows": 78,
        }
    )
    payload["rights"].append(
        {
            "vendor": "alpaca_sip",
            "evidence_reference": "written-rights-not-yet-received",
        }
    )
    payload["rights"].append(_passing_rights("ibkr"))
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    report = run_research_data_bakeoff(manifest_path)

    result = next(item for item in report.sample_results if item.vendor == "alpaca_sip")
    assert result.ok is True
    assert result.row_count == 390
    assert report.ok is False
    assert report.rights_failed_vendors == ["alpaca_sip"]
    assert "alpaca_sip" not in report.procurement_ready_vendors
    comparison = next(
        item for item in report.comparisons if item.comparison_type == "intraday_overlap"
    )
    assert comparison.ok is True
    assert comparison.overlap_count == 78


def test_bakeoff_fails_closed_on_vendor_overlap_mismatch(tmp_path: Path) -> None:
    manifest_path = _passing_manifest(tmp_path)
    norgate_path = tmp_path / "norgate-daily.csv"
    rows = _bar_rows()
    rows[0]["close"] = "510.00"
    rows[0]["high"] = "511.00"
    _write_csv(
        norgate_path,
        ["symbol", "timestamp", "open", "high", "low", "close", "volume"],
        rows,
    )

    report = run_research_data_bakeoff(manifest_path)

    assert report.ok is False
    assert any("daily overlap price mismatches" in error for error in report.errors)


def test_bakeoff_rejects_count_correct_but_misaligned_minute_grid(tmp_path: Path) -> None:
    manifest_path = _passing_manifest(tmp_path)
    sample_path = tmp_path / "massive-normal.csv"
    rows = _minute_rows(date(2025, 11, 26))
    rows[10]["window_start"] = rows[9]["window_start"]
    _write_csv(
        sample_path,
        [
            "ticker",
            "volume",
            "open",
            "close",
            "high",
            "low",
            "window_start",
            "transactions",
        ],
        rows,
    )

    report = run_research_data_bakeoff(manifest_path)

    assert report.ok is False
    assert any("intraday timestamps do not match XNYS grid" in error for error in report.errors)


def test_bakeoff_does_not_approve_rights_only_vendor(tmp_path: Path) -> None:
    manifest_path = _passing_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["rights"].append(
        {
            "vendor": "rights-only",
            "evidence_reference": "operator-reviewed-rights-only-terms",
            "internal_storage_allowed": True,
            "cloud_backup_allowed": True,
            "automated_research_allowed": True,
            "model_training_allowed": True,
            "derived_data_allowed": True,
            "correction_replay_available": True,
            "paper_trading_use_allowed": True,
            "live_trading_use_allowed": True,
            "retention_after_termination_allowed": True,
            "derived_retention_after_termination_allowed": True,
        }
    )
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    report = run_research_data_bakeoff(manifest_path)

    assert report.ok is True
    assert "rights-only" not in report.procurement_ready_vendors


def test_bakeoff_serializes_and_renders_markdown(tmp_path: Path) -> None:
    report = run_research_data_bakeoff(_passing_manifest(tmp_path))
    payload = report.model_dump(mode="json")
    rendered = markdown_summary(payload)

    assert payload["report_type"] == "research_data_bakeoff"
    assert "SPY Research Data Vendor Bake-off" in rendered
    assert "Credentials read: `False`" in rendered
    assert "Procurement-ready vendors: `massive, norgate`" in rendered


def test_bakeoff_module_stays_broker_and_credential_free() -> None:
    source = Path("src/trader/data/research_bakeoff.py").read_text()

    for forbidden in (
        "trader.broker",
        "trader.execution",
        "ibapi",
        "requests",
        "httpx",
        "placeOrder",
        "cancelOrder",
        "reqGlobalCancel",
        "load_config",
        "os.environ",
    ):
        assert forbidden not in source


def test_cli_exposes_research_data_bakeoff() -> None:
    result = CliRunner().invoke(app, ["research-data-bakeoff", "--help"])

    assert result.exit_code == 0
    assert "operator-supplied SPY vendor samples" in result.output
