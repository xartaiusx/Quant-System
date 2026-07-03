from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from tests.fixtures.historical_snapshots import (
    clean_two_symbol_dataset,
    duplicate_timestamps,
    zero_volume_bars,
)
from typer.testing import CliRunner

import trader.cli as cli
from trader.config import ConfigError, load_config
from trader.data.quality_gate import build_data_quality_gate_report
from trader.execution.paper_executor import PaperExecutor
from trader.models import (
    DataQualityGateRequest,
    DataQualityGateStatus,
    ExecutionStatus,
    TradeAction,
    TradePlan,
)
from trader.reporting.reports import markdown_summary


def gate_request(root: Path, *symbols: str, min_bars: int = 3) -> DataQualityGateRequest:
    return DataQualityGateRequest(
        symbols=list(symbols) or ["SPY", "AAPL"],
        bar_size="5 mins",
        what_to_show="TRADES",
        base_data_path=root.as_posix(),
        min_bars=min_bars,
    )


def test_data_quality_gate_passes_clean_fixture(tmp_path: Path) -> None:
    scenario = clean_two_symbol_dataset(tmp_path / "data" / "historical")

    report = build_data_quality_gate_report(
        load_config(load_dotenv_file=False),
        gate_request(scenario.root),
    )

    assert report.ok is True
    assert report.final_status == DataQualityGateStatus.PASSED
    assert [result.status for result in report.results] == [DataQualityGateStatus.PASSED] * 2
    assert report.broker_contacted is False
    assert report.signal_evaluation_enabled is False
    assert report.order_intents_generated is False
    assert report.futures_contracts_enabled is False
    assert report.direct_futures_data_enabled is False


def test_data_quality_gate_fails_zero_volume_by_default(tmp_path: Path) -> None:
    scenario = zero_volume_bars(tmp_path / "data" / "historical")

    report = build_data_quality_gate_report(
        load_config(load_dotenv_file=False),
        gate_request(scenario.root, "DBA"),
    )

    assert report.ok is False
    assert report.final_status == DataQualityGateStatus.FAILED
    assert report.results[0].zero_volume_bars == 1
    assert report.results[0].zero_volume_sample_timestamps == [
        "2026-05-18T21:35:00+00:00"
    ]
    assert [issue.code for issue in report.results[0].issues] == ["zero_volume_bars"]
    assert "sample timestamps: 2026-05-18T21:35:00+00:00" in (
        report.results[0].issues[0].message
    )


def test_data_quality_gate_threshold_can_document_known_partial_data(tmp_path: Path) -> None:
    scenario = zero_volume_bars(tmp_path / "data" / "historical")
    request = gate_request(scenario.root, "DBA")
    request = request.model_copy(update={"max_zero_volume_bars": 1})

    report = build_data_quality_gate_report(load_config(load_dotenv_file=False), request)

    assert report.ok is True
    assert report.final_status == DataQualityGateStatus.PASSED
    assert report.results[0].zero_volume_bars == 1
    assert report.results[0].zero_volume_sample_timestamps == [
        "2026-05-18T21:35:00+00:00"
    ]


def test_data_quality_gate_fails_duplicate_timestamps(tmp_path: Path) -> None:
    scenario = duplicate_timestamps(tmp_path / "data" / "historical")

    report = build_data_quality_gate_report(
        load_config(load_dotenv_file=False),
        gate_request(scenario.root, "SPY"),
    )

    assert report.ok is False
    assert report.results[0].duplicate_timestamps_count == 1
    assert "duplicate_timestamps" in {issue.code for issue in report.results[0].issues}


def test_data_quality_gate_report_serializes_to_markdown(tmp_path: Path) -> None:
    scenario = clean_two_symbol_dataset(tmp_path / "data" / "historical")
    report = build_data_quality_gate_report(
        load_config(load_dotenv_file=False),
        gate_request(scenario.root),
    )

    payload = report.model_dump(mode="json")
    markdown = markdown_summary(payload)

    assert payload["report_type"] == "data_quality_gate"
    assert "Broker-free Data Quality Gate" in markdown
    assert "No order APIs invoked" in markdown


def test_data_quality_gate_markdown_includes_zero_volume_samples(tmp_path: Path) -> None:
    scenario = zero_volume_bars(tmp_path / "data" / "historical")
    report = build_data_quality_gate_report(
        load_config(load_dotenv_file=False),
        gate_request(scenario.root, "DBA"),
    )

    markdown = markdown_summary(report.model_dump(mode="json"))

    assert "zero_samples=`2026-05-18T21:35:00+00:00`" in markdown


def test_data_quality_gate_handles_relative_manifest_paths_from_other_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = clean_two_symbol_dataset(tmp_path / "repo" / "data" / "historical")
    for bars_path, manifest_path in zip(
        scenario.bars_paths,
        scenario.manifest_paths,
        strict=True,
    ):
        payload = json.loads(manifest_path.read_text())
        payload["snapshot_path"] = (
            Path("data")
            / "historical"
            / bars_path.parent.relative_to(scenario.root)
            / bars_path.name
        ).as_posix()
        payload["manifest_path"] = (
            Path("data")
            / "historical"
            / manifest_path.parent.relative_to(scenario.root)
            / manifest_path.name
        ).as_posix()
        manifest_path.write_text(json.dumps(payload))
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    report = build_data_quality_gate_report(
        load_config(load_dotenv_file=False),
        gate_request(scenario.root),
    )

    assert report.ok is True
    assert report.final_status == DataQualityGateStatus.PASSED


def test_data_quality_gate_cli_fails_closed_for_zero_volume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = zero_volume_bars(tmp_path / "data" / "historical")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli.app,
        [
            "data-quality-gate",
            "--symbols",
            "DBA",
            "--base-path",
            scenario.root.as_posix(),
            "--min-bars",
            "3",
        ],
    )

    assert result.exit_code == 1
    assert "Broker contacted: false" in result.output
    assert "zero-volume bars observed 1" in result.output
    assert "sample timestamps: 2026-05-18T21:35:00+00:00" in result.output
    payload = json.loads(Path("reports/latest_data_quality_gate.json").read_text())
    assert payload["ok"] is False
    assert payload["results"][0]["zero_volume_sample_timestamps"] == [
        "2026-05-18T21:35:00+00:00"
    ]
    assert payload["broker_contacted"] is False
    assert payload["order_routing_enabled"] is False


def test_data_quality_gate_path_has_no_socket_dependencies() -> None:
    source = Path("src/trader/data/quality_gate.py").read_text()

    assert "trader." + "broker" not in source
    assert "IBKR" + "ReadOnlyClient" not in source
    assert "ib" + "api" not in source


def test_data_quality_gate_path_has_no_order_api_names() -> None:
    source = "\n".join(
        path.read_text()
        for path in [
            Path("src/trader/data/quality_gate.py"),
            Path("scripts/run-data-quality-gate.sh"),
        ]
        if path.exists()
    )

    assert "place" + "Order" not in source
    assert "cancel" + "Order" not in source
    assert "req" + "GlobalCancel" not in source


def test_live_ports_remain_rejected_for_data_quality_gate() -> None:
    with pytest.raises(ConfigError):
        load_config(env={"IBKR_PORT": "7496"}, load_dotenv_file=False)


def test_paper_executor_remains_blocked_for_data_quality_gate() -> None:
    config = load_config(env={"ALLOW_PAPER_ORDERS": "true"}, load_dotenv_file=False)
    plan = TradePlan(
        symbol="DBA",
        action=TradeAction.BUY,
        quantity=1,
        limit_price=Decimal("25"),
        notional=Decimal("25"),
        strategy="unit",
        source_signal_id="unit",
    )

    result = PaperExecutor(config).submit(plan)

    assert result.status == ExecutionStatus.BLOCKED
    assert result.submitted_to_broker is False
