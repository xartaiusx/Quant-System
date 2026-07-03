"""Synthetic historical snapshot fixtures for broker-free stress tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from trader.models import (
    HistoricalSnapshotIndexEntry,
    HistoricalSnapshotLoadRequest,
    HistoricalSnapshotManifest,
)

BASE_TIME = datetime(2026, 5, 18, 21, 30, tzinfo=UTC)
SNAPSHOT_TIMESTAMP = "20260519T040000Z"
BAR_SIZE = "5 mins"
WHAT_TO_SHOW = "TRADES"


@dataclass(frozen=True)
class SnapshotFixture:
    """Paths and request metadata for a synthetic fixture scenario."""

    name: str
    root: Path
    symbols: list[str]
    bars_paths: list[Path]
    manifest_paths: list[Path]
    missing_entry: HistoricalSnapshotIndexEntry | None = None

    def load_request(self, *, strict: bool = False) -> HistoricalSnapshotLoadRequest:
        return HistoricalSnapshotLoadRequest(
            symbols=self.symbols,
            bar_size=BAR_SIZE,
            what_to_show=WHAT_TO_SHOW,
            strict=strict,
            base_data_path=self.root.as_posix(),
        )


def clean_two_symbol_dataset(root: Path) -> SnapshotFixture:
    paths = [
        _write_snapshot(root, symbol="SPY", offsets=[0, 5, 10]),
        _write_snapshot(root, symbol="AAPL", offsets=[0, 5, 10]),
    ]
    return _fixture("clean_two_symbol_dataset", root, ["SPY", "AAPL"], paths)


def long_two_symbol_dataset(root: Path, *, bar_count: int = 30) -> SnapshotFixture:
    offsets = [5 * index for index in range(bar_count)]
    paths = [
        _write_snapshot(root, symbol="SPY", offsets=offsets),
        _write_snapshot(root, symbol="AAPL", offsets=offsets),
    ]
    return _fixture("long_two_symbol_dataset", root, ["SPY", "AAPL"], paths)


def single_symbol_missing_bars(root: Path) -> SnapshotFixture:
    paths = [_write_snapshot(root, symbol="SPY", offsets=[0, 15])]
    return _fixture("single_symbol_missing_bars", root, ["SPY"], paths)


def multi_symbol_partial_overlap(root: Path) -> SnapshotFixture:
    paths = [
        _write_snapshot(root, symbol="SPY", offsets=[0, 5, 10, 15]),
        _write_snapshot(root, symbol="AAPL", offsets=[5, 10]),
    ]
    return _fixture("multi_symbol_partial_overlap", root, ["SPY", "AAPL"], paths)


def duplicate_timestamps(root: Path) -> SnapshotFixture:
    paths = [_write_snapshot(root, symbol="SPY", offsets=[0, 0, 5])]
    return _fixture("duplicate_timestamps", root, ["SPY"], paths)


def invalid_ohlc(root: Path) -> SnapshotFixture:
    paths = [
        _write_snapshot(
            root,
            symbol="SPY",
            offsets=[0, 5],
            invalid_ohlc_offsets={5},
        )
    ]
    return _fixture("invalid_ohlc", root, ["SPY"], paths)


def negative_volume(root: Path) -> SnapshotFixture:
    paths = [
        _write_snapshot(
            root,
            symbol="SPY",
            offsets=[0, 5],
            negative_volume_offsets={5},
        )
    ]
    return _fixture("negative_volume", root, ["SPY"], paths)


def zero_volume_bars(root: Path) -> SnapshotFixture:
    paths = [
        _write_snapshot(
            root,
            symbol="DBA",
            offsets=[0, 5, 10],
            zero_volume_offsets={5},
        )
    ]
    return _fixture("zero_volume_bars", root, ["DBA"], paths)


def malformed_jsonl_line(root: Path) -> SnapshotFixture:
    paths = [_write_snapshot(root, symbol="SPY", offsets=[0, 5], malformed_line=True)]
    return _fixture("malformed_jsonl_line", root, ["SPY"], paths)


def missing_manifest(root: Path) -> SnapshotFixture:
    bars_path, manifest_path = _write_snapshot(root, symbol="SPY", offsets=[0, 5])
    manifest_path.unlink()
    entry = HistoricalSnapshotIndexEntry(
        symbol="SPY",
        bar_size=BAR_SIZE,
        what_to_show=WHAT_TO_SHOW,
        snapshot_timestamp=SNAPSHOT_TIMESTAMP,
        bars_path=bars_path.as_posix(),
        manifest_path=manifest_path.as_posix(),
    )
    return SnapshotFixture(
        name="missing_manifest",
        root=root,
        symbols=["SPY"],
        bars_paths=[bars_path],
        manifest_paths=[manifest_path],
        missing_entry=entry,
    )


def missing_bars_file(root: Path) -> SnapshotFixture:
    bars_path, manifest_path = _write_snapshot(root, symbol="SPY", offsets=[0, 5])
    bars_path.unlink()
    return SnapshotFixture(
        name="missing_bars_file",
        root=root,
        symbols=["SPY"],
        bars_paths=[bars_path],
        manifest_paths=[manifest_path],
    )


def empty_dataset(root: Path) -> SnapshotFixture:
    paths = [_write_snapshot(root, symbol="SPY", offsets=[])]
    return _fixture("empty_dataset", root, ["SPY"], paths)


def _fixture(
    name: str,
    root: Path,
    symbols: list[str],
    paths: list[tuple[Path, Path]],
) -> SnapshotFixture:
    return SnapshotFixture(
        name=name,
        root=root,
        symbols=symbols,
        bars_paths=[bars_path for bars_path, _manifest_path in paths],
        manifest_paths=[manifest_path for _bars_path, manifest_path in paths],
    )


def _write_snapshot(
    root: Path,
    *,
    symbol: str,
    offsets: list[int],
    timestamp_slug: str = SNAPSHOT_TIMESTAMP,
    invalid_ohlc_offsets: set[int] | None = None,
    negative_volume_offsets: set[int] | None = None,
    zero_volume_offsets: set[int] | None = None,
    malformed_line: bool = False,
) -> tuple[Path, Path]:
    invalid_ohlc_offsets = invalid_ohlc_offsets or set()
    negative_volume_offsets = negative_volume_offsets or set()
    zero_volume_offsets = zero_volume_offsets or set()
    snapshot_dir = root / symbol / "5_mins" / WHAT_TO_SHOW
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    bars_path = snapshot_dir / f"{timestamp_slug}_bars.jsonl"
    manifest_path = snapshot_dir / f"{timestamp_slug}_manifest.json"

    bars = [
        _bar_payload(
            symbol,
            offset,
            invalid_ohlc=offset in invalid_ohlc_offsets,
            negative_volume=offset in negative_volume_offsets,
            zero_volume=offset in zero_volume_offsets,
        )
        for offset in offsets
    ]
    lines = [json.dumps(bar, sort_keys=True) for bar in bars]
    if malformed_line:
        lines.append("{malformed json")
    bars_path.write_text("\n".join(lines) + ("\n" if lines else ""))

    manifest = HistoricalSnapshotManifest(
        generated_at=datetime.now(UTC),
        symbol=symbol,
        contract_id=1001,
        exchange="SMART",
        currency="USD",
        duration="1 D",
        bar_size=BAR_SIZE,
        what_to_show=WHAT_TO_SHOW,
        use_rth=1,
        bar_count=len(bars),
        first_bar_time=bars[0]["timestamp"] if bars else None,
        last_bar_time=bars[-1]["timestamp"] if bars else None,
        request_timeout=30,
        snapshot_path=bars_path.as_posix(),
        manifest_path=manifest_path.as_posix(),
    )
    manifest_path.write_text(manifest.model_dump_json())
    return bars_path, manifest_path


def _bar_payload(
    symbol: str,
    offset_minutes: int,
    *,
    invalid_ohlc: bool = False,
    negative_volume: bool = False,
    zero_volume: bool = False,
) -> dict[str, Any]:
    timestamp = BASE_TIME + timedelta(minutes=offset_minutes)
    volume = "-10" if negative_volume else "0" if zero_volume else "1000"
    payload: dict[str, Any] = {
        "symbol": symbol,
        "contract_id": 1001,
        "timestamp": timestamp.strftime("%Y%m%d  %H:%M:%S"),
        "open": "100",
        "high": "101",
        "low": "99",
        "close": "100.50",
        "volume": volume,
        "wap": "100.25",
        "bar_count": 10,
        "source": "fixture",
        "duration": "1 D",
        "bar_size": BAR_SIZE,
        "what_to_show": WHAT_TO_SHOW,
        "use_rth": 1,
    }
    if invalid_ohlc:
        payload.update({"high": "99", "low": "98", "close": "101"})
    return payload
