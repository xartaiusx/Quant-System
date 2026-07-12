"""Offline registration for immutable SPY instrument identity revisions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from trader.data.research_store import initialize_research_store
from trader.models import ResearchInstrumentMasterRecord, ResearchInstrumentMasterReport


def register_research_instrument(
    manifest_path: Path,
    *,
    catalog_root: Path,
) -> ResearchInstrumentMasterReport:
    """Register one versioned SPY identity record without external access."""

    resolved_manifest = manifest_path.expanduser().resolve()
    resolved_root = catalog_root.expanduser().resolve()
    try:
        payload = json.loads(resolved_manifest.read_text(encoding="utf-8"))
        record = ResearchInstrumentMasterRecord.model_validate(payload)
        catalog_path = initialize_research_store(resolved_root)
    except (OSError, RuntimeError, sqlite3.Error, ValueError, json.JSONDecodeError) as exc:
        return ResearchInstrumentMasterReport(
            ok=False,
            manifest_path=resolved_manifest.as_posix(),
            errors=[f"instrument manifest could not be registered: {exc}"],
            final_status="failed",
        )

    fingerprint = _fingerprint(record.model_dump(mode="json"))
    try:
        with sqlite3.connect(catalog_path) as connection:
            existing = connection.execute(
                """
                SELECT record_fingerprint, active
                FROM instrument_master
                WHERE internal_id = ? AND version = ?
                """,
                (record.internal_id, record.version),
            ).fetchone()
            if existing is not None:
                if existing[0] != fingerprint:
                    raise ValueError(
                        "an instrument revision cannot be changed after registration"
                    )
                return ResearchInstrumentMasterReport(
                    ok=True,
                    manifest_path=resolved_manifest.as_posix(),
                    catalog_path=catalog_path.as_posix(),
                    record=record,
                    record_fingerprint=fingerprint,
                    active_version=record.version if existing[1] else _active_version(
                        connection, record.internal_id
                    ),
                    idempotent_replay=True,
                    warnings=["Instrument identity is versioned and stored outside Git data"],
                    final_status="completed",
                )

            maximum = connection.execute(
                "SELECT MAX(version) FROM instrument_master WHERE internal_id = ?",
                (record.internal_id,),
            ).fetchone()[0]
            if maximum is not None and record.version <= int(maximum):
                raise ValueError("new instrument revisions must increase the version")

            connection.execute(
                "UPDATE instrument_master SET active = 0 WHERE internal_id = ?",
                (record.internal_id,),
            )
            connection.execute(
                """
                INSERT INTO instrument_master(
                    internal_id, version, symbol, security_name, sec_type, currency,
                    primary_exchange, routing_exchange, min_tick, listing_start,
                    listing_end, ibkr_con_id, composite_figi, cusip, isin,
                    vendor_mappings_json, source_references_json, record_fingerprint,
                    active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    record.internal_id,
                    record.version,
                    record.symbol,
                    record.security_name,
                    record.sec_type,
                    record.currency,
                    record.primary_exchange,
                    record.routing_exchange,
                    str(record.min_tick),
                    record.listing_start,
                    record.listing_end,
                    record.ibkr_con_id,
                    record.composite_figi,
                    record.cusip,
                    record.isin,
                    json.dumps(record.vendor_mappings, sort_keys=True, separators=(",", ":")),
                    json.dumps(record.source_references, separators=(",", ":")),
                    fingerprint,
                    datetime.now(UTC).isoformat(),
                ),
            )
    except (sqlite3.Error, ValueError) as exc:
        return ResearchInstrumentMasterReport(
            ok=False,
            manifest_path=resolved_manifest.as_posix(),
            catalog_path=catalog_path.as_posix(),
            record=record,
            record_fingerprint=fingerprint,
            errors=[f"instrument revision could not be registered: {exc}"],
            final_status="failed",
        )

    return ResearchInstrumentMasterReport(
        ok=True,
        manifest_path=resolved_manifest.as_posix(),
        catalog_path=catalog_path.as_posix(),
        record=record,
        record_fingerprint=fingerprint,
        active_version=record.version,
        warnings=["Instrument identity is versioned and stored outside Git data"],
        final_status="completed",
    )


def _active_version(connection: sqlite3.Connection, internal_id: str) -> int | None:
    row = connection.execute(
        "SELECT version FROM instrument_master WHERE internal_id = ? AND active = 1",
        (internal_id,),
    ).fetchone()
    return int(row[0]) if row is not None else None


def _fingerprint(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


__all__ = ["register_research_instrument"]
