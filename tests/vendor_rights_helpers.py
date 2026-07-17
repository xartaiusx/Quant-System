from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import exchange_calendars as xcals  # type: ignore[import-untyped]

from trader.data.research_bakeoff import run_research_data_bakeoff
from trader.data.research_vendor_decision import run_research_vendor_decision

EVIDENCE_HASH = "sha256:" + "a" * 64
SCORE_WEIGHTS = {
    "rights_and_permitted_use": 20,
    "data_quality": 20,
    "coverage": 10,
    "corporate_actions": 10,
    "corrections": 10,
    "timestamp_sessions": 10,
    "delivery_operations": 10,
    "total_cost_storage": 10,
}


def write_authoritative_vendor_decision(
    root: Path,
    *,
    vendor: str,
    evidence_reference: str = EVIDENCE_HASH,
    written_evidence_sha256: str = EVIDENCE_HASH,
) -> Path:
    """Build a complete deterministic decision chain for offline tests."""

    root.mkdir(parents=True, exist_ok=True)
    decision_report_path = root / "decision-report.json"
    if decision_report_path.is_file():
        return decision_report_path.resolve()

    sample_specs = [
        (
            f"{vendor}-normal-pre-dst",
            root / f"{vendor}-normal-pre-dst.csv",
            date(2025, 3, 7),
            ["normal_session", "dst_transition", "intraday_overlap"],
            None,
        ),
        (
            f"{vendor}-normal-post-dst",
            root / f"{vendor}-normal-post-dst.csv",
            date(2025, 3, 10),
            ["normal_session", "dst_transition"],
            None,
        ),
        (
            f"{vendor}-early-close",
            root / f"{vendor}-early-close.csv",
            date(2025, 11, 28),
            ["early_close"],
            None,
        ),
        (
            f"{vendor}-correction-before",
            root / f"{vendor}-correction-before.csv",
            date(2025, 3, 11),
            ["correction_before"],
            None,
        ),
        (
            f"{vendor}-correction-after",
            root / f"{vendor}-correction-after.csv",
            date(2025, 3, 11),
            ["correction_after"],
            10,
        ),
    ]
    for _sample_id, path, session_date, _case_tags, changed_index in sample_specs:
        _write_minute_sample(
            path,
            session_date=session_date,
            changed_index=changed_index,
        )

    reference_vendor = "reference_vendor"
    reference_path = root / "reference-overlap.csv"
    _write_minute_sample(reference_path, session_date=date(2025, 3, 7))

    bakeoff_manifest_path = root / "bakeoff-manifest.json"
    bakeoff_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "symbol": "SPY",
                "required_case_tags": [
                    "normal_session",
                    "early_close",
                    "dst_transition",
                    "correction_before",
                    "correction_after",
                    "intraday_overlap",
                ],
                "samples": [
                    *[
                        {
                            "sample_id": sample_id,
                            "vendor": vendor,
                            "path": path.name,
                            "kind": "minute_bars",
                            "source_format": "canonical_ohlcv",
                            "case_tags": case_tags,
                        }
                        for sample_id, path, _date, case_tags, _change in sample_specs
                    ],
                    {
                        "sample_id": "reference-overlap",
                        "vendor": reference_vendor,
                        "path": reference_path.name,
                        "kind": "minute_bars",
                        "source_format": "canonical_ohlcv",
                        "case_tags": ["intraday_overlap"],
                    },
                ],
                "rights": [
                    _rights_payload(vendor, evidence_reference),
                    _rights_payload(reference_vendor, "sha256:" + "c" * 64),
                ],
            }
        ),
        encoding="utf-8",
    )
    bakeoff_report = run_research_data_bakeoff(bakeoff_manifest_path)
    assert bakeoff_report.ok is True
    bakeoff_report_path = root / "bakeoff-report.json"
    bakeoff_report_path.write_text(
        bakeoff_report.model_dump_json(),
        encoding="utf-8",
    )

    decision_manifest_path = root / "decision-manifest.json"
    decision_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "symbol": "SPY",
                "score_weights": SCORE_WEIGHTS,
                "candidates": [
                    {
                        "vendor": vendor,
                        "bakeoff_report_path": bakeoff_report_path.name,
                        "monthly_cost_usd": 100,
                        "estimated_storage_gb": 20,
                        "written_evidence_sha256": [written_evidence_sha256],
                        "technical_scores": {key: 100 for key in SCORE_WEIGHTS},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    decision_report = run_research_vendor_decision(decision_manifest_path)
    assert decision_report.ok is True
    decision_report_path.write_text(
        decision_report.model_dump_json(),
        encoding="utf-8",
    )
    return decision_report_path.resolve()


def write_authoritative_daily_vendor_decision(root: Path, *, vendor: str) -> Path:
    """Build selected-vendor and cross-vendor daily-overlap evidence."""

    root.mkdir(parents=True, exist_ok=True)
    sample_path = root / f"{vendor}-daily.csv"
    with sample_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "symbol",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "symbol": "SPY",
                "timestamp": "2025-01-02",
                "open": "500",
                "high": "501",
                "low": "499",
                "close": "500.5",
                "volume": "1000000",
            }
        )
    reference_vendor = "reference_vendor"
    reference_path = root / "reference-daily.csv"
    reference_path.write_text(sample_path.read_text(encoding="utf-8"), encoding="utf-8")
    bakeoff_manifest_path = root / "bakeoff-manifest.json"
    bakeoff_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "symbol": "SPY",
                "required_case_tags": ["daily_overlap"],
                "samples": [
                    {
                        "sample_id": f"{vendor}-daily",
                        "vendor": vendor,
                        "path": sample_path.name,
                        "kind": "daily_bars",
                        "source_format": "canonical_ohlcv",
                        "case_tags": ["daily_overlap"],
                    },
                    {
                        "sample_id": "reference-daily",
                        "vendor": reference_vendor,
                        "path": reference_path.name,
                        "kind": "daily_bars",
                        "source_format": "canonical_ohlcv",
                        "case_tags": ["daily_overlap"],
                    },
                ],
                "rights": [
                    _rights_payload(vendor, EVIDENCE_HASH),
                    _rights_payload(reference_vendor, "sha256:" + "c" * 64),
                ],
            }
        ),
        encoding="utf-8",
    )
    bakeoff_report = run_research_data_bakeoff(bakeoff_manifest_path)
    assert bakeoff_report.ok is True
    bakeoff_report_path = root / "bakeoff-report.json"
    bakeoff_report_path.write_text(
        bakeoff_report.model_dump_json(),
        encoding="utf-8",
    )
    decision_manifest_path = root / "decision-manifest.json"
    decision_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "symbol": "SPY",
                "score_weights": SCORE_WEIGHTS,
                "candidates": [
                    {
                        "vendor": vendor,
                        "bakeoff_report_path": bakeoff_report_path.name,
                        "monthly_cost_usd": 100,
                        "estimated_storage_gb": 20,
                        "written_evidence_sha256": [EVIDENCE_HASH],
                        "technical_scores": {key: 100 for key in SCORE_WEIGHTS},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    decision_report = run_research_vendor_decision(decision_manifest_path)
    assert decision_report.ok is True
    decision_report_path = root / "decision-report.json"
    decision_report_path.write_text(
        decision_report.model_dump_json(),
        encoding="utf-8",
    )
    return decision_report_path.resolve()


def write_authoritative_action_vendor_decision(root: Path, *, vendor: str) -> Path:
    """Build a complete corporate-action decision chain for offline tests."""

    root.mkdir(parents=True, exist_ok=True)
    sample_path = root / f"{vendor}-actions.csv"
    with sample_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "symbol",
                "ex_date",
                "event_type",
                "factor",
                "cash_amount",
                "currency",
                "revision",
            ),
        )
        writer.writeheader()
        writer.writerows(
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
            ]
        )
    bakeoff_manifest_path = root / "bakeoff-manifest.json"
    bakeoff_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "symbol": "SPY",
                "required_case_tags": ["ex_dividend", "synthetic_split"],
                "samples": [
                    {
                        "sample_id": f"{vendor}-actions",
                        "vendor": vendor,
                        "path": sample_path.name,
                        "kind": "corporate_actions",
                        "source_format": "canonical_actions",
                        "case_tags": ["ex_dividend", "synthetic_split"],
                    }
                ],
                "rights": [_rights_payload(vendor, EVIDENCE_HASH)],
            }
        ),
        encoding="utf-8",
    )
    bakeoff_report = run_research_data_bakeoff(bakeoff_manifest_path)
    assert bakeoff_report.ok is True
    bakeoff_report_path = root / "bakeoff-report.json"
    bakeoff_report_path.write_text(
        bakeoff_report.model_dump_json(),
        encoding="utf-8",
    )
    decision_manifest_path = root / "decision-manifest.json"
    decision_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "symbol": "SPY",
                "score_weights": SCORE_WEIGHTS,
                "candidates": [
                    {
                        "vendor": vendor,
                        "bakeoff_report_path": bakeoff_report_path.name,
                        "monthly_cost_usd": 100,
                        "estimated_storage_gb": 20,
                        "written_evidence_sha256": [EVIDENCE_HASH],
                        "technical_scores": {key: 100 for key in SCORE_WEIGHTS},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    decision_report = run_research_vendor_decision(decision_manifest_path)
    assert decision_report.ok is True
    decision_report_path = root / "decision-report.json"
    decision_report_path.write_text(
        decision_report.model_dump_json(),
        encoding="utf-8",
    )
    return decision_report_path.resolve()


def _write_minute_sample(
    path: Path,
    *,
    session_date: date,
    changed_index: int | None = None,
) -> None:
    calendar = xcals.get_calendar("XNYS")
    rows: list[dict[str, str]] = []
    for index, timestamp in enumerate(calendar.session_minutes(session_date)):
        open_ = Decimal("500") + Decimal(index) / Decimal("100")
        close = open_ + Decimal("0.02")
        if index == changed_index:
            close += Decimal("0.01")
        rows.append(
            {
                "symbol": "SPY",
                "timestamp": timestamp.to_pydatetime().isoformat(),
                "open": str(open_),
                "high": str(max(open_, close) + Decimal("0.01")),
                "low": str(min(open_, close) - Decimal("0.01")),
                "close": str(close),
                "volume": str(1000 + index),
            }
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "symbol",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ),
        )
        writer.writeheader()
        writer.writerows(rows)


def _rights_payload(vendor: str, evidence_reference: str) -> dict[str, object]:
    return {
        "vendor": vendor,
        "evidence_reference": evidence_reference,
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


__all__ = [
    "EVIDENCE_HASH",
    "SCORE_WEIGHTS",
    "write_authoritative_action_vendor_decision",
    "write_authoritative_daily_vendor_decision",
    "write_authoritative_vendor_decision",
]
