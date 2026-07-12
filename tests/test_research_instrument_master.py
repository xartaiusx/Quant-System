from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from trader.cli import app
from trader.data.research_instrument_master import register_research_instrument
from trader.reporting.reports import markdown_summary


def test_instrument_revision_is_immutable_and_idempotent(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path / "spy.json", version=1)
    root = tmp_path / "store"

    first = register_research_instrument(manifest, catalog_root=root)
    replay = register_research_instrument(manifest, catalog_root=root)

    assert first.ok is True
    assert first.active_version == 1
    assert replay.ok is True
    assert replay.idempotent_replay is True
    assert replay.record_fingerprint == first.record_fingerprint

    changed = json.loads(manifest.read_text(encoding="utf-8"))
    changed["security_name"] = "Changed after registration"
    manifest.write_text(json.dumps(changed), encoding="utf-8")
    rejected = register_research_instrument(manifest, catalog_root=root)
    assert rejected.ok is False
    assert "cannot be changed" in rejected.errors[0]


def test_higher_instrument_version_supersedes_active_revision(tmp_path: Path) -> None:
    root = tmp_path / "store"
    v1 = _write_manifest(tmp_path / "v1.json", version=1)
    v2 = _write_manifest(tmp_path / "v2.json", version=2)

    assert register_research_instrument(v1, catalog_root=root).ok is True
    report = register_research_instrument(v2, catalog_root=root)

    assert report.ok is True
    assert report.active_version == 2
    with sqlite3.connect(root / "catalog/research.sqlite3") as connection:
        rows = connection.execute(
            "SELECT version, active FROM instrument_master ORDER BY version"
        ).fetchall()
    assert rows == [(1, 0), (2, 1)]


def test_instrument_report_renders_and_command_is_registered(tmp_path: Path) -> None:
    report = register_research_instrument(
        _write_manifest(tmp_path / "spy.json", version=1),
        catalog_root=tmp_path / "store",
    )

    markdown = markdown_summary(report.model_dump(mode="json"))
    assert "SPY Research Instrument Master" in markdown
    assert "IBKR conId: `756733`" in markdown
    result = CliRunner().invoke(app, ["research-instrument-register", "--help"])
    assert result.exit_code == 0


def test_instrument_registration_module_is_offline_and_order_free() -> None:
    source = Path("src/trader/data/research_instrument_master.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "trader.broker",
        "trader.execution",
        "import ibapi",
        "from ibapi",
        "httpx",
        "placeOrder",
        "cancelOrder",
        "reqGlobalCancel",
    ):
        assert forbidden not in source


def _write_manifest(path: Path, *, version: int) -> Path:
    payload = {
        "internal_id": "spy-us-equity",
        "version": version,
        "symbol": "SPY",
        "security_name": "State Street SPDR S&P 500 ETF Trust",
        "sec_type": "STK",
        "currency": "USD",
        "primary_exchange": "ARCA",
        "routing_exchange": "SMART",
        "min_tick": 0.01,
        "listing_start": "1993-01-22",
        "ibkr_con_id": 756733,
        "composite_figi": "BBG000BDTBL9",
        "cusip": "78462F103",
        "isin": "US78462F1030",
        "vendor_mappings": {"ibkr": "756733"},
        "source_references": [
            "https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/",
            "https://www.openfigi.com/id/BBG000BDTG10",
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
