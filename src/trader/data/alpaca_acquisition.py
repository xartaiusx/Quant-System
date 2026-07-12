"""Isolated, data-only acquisition for historical Alpaca SPY SIP bars."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"
ALPACA_BARS_PATH = "/v2/stocks/SPY/bars"
FREE_DATA_DELAY = timedelta(minutes=15)
DEFAULT_REQUESTS_PER_MINUTE = 150
_REQUIRED_BAR_FIELDS = frozenset({"t", "o", "h", "l", "c", "v", "n", "vw"})
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class AcquisitionError(RuntimeError):
    """Fail-closed acquisition error with no credential content."""


@dataclass(frozen=True)
class HistoricalDataRequest:
    symbol: str
    feed: str
    timeframe: str
    start: date
    end: date
    output_root: Path

    def validate(self, *, now: datetime) -> None:
        if self.symbol.strip().upper() != "SPY":
            raise AcquisitionError("Alpaca acquisition is SPY-only")
        if self.feed.strip().lower() != "sip":
            raise AcquisitionError("Alpaca acquisition requires the historical SIP feed")
        if self.timeframe != "1Min":
            raise AcquisitionError("Alpaca acquisition requires one-minute bars")
        if self.start > self.end:
            raise AcquisitionError("acquisition start date must not follow end date")
        if self.start < date(2016, 1, 1):
            raise AcquisitionError("Alpaca free historical candidate coverage starts in 2016")
        requested_end = datetime.combine(
            self.end + timedelta(days=1),
            datetime_time.min,
            tzinfo=UTC,
        )
        if requested_end > now.astimezone(UTC) - FREE_DATA_DELAY:
            raise AcquisitionError(
                "requested data must be entirely older than the 15-minute free-access boundary"
            )
        if self.output_root.resolve() == _PROJECT_ROOT or _PROJECT_ROOT in (
            self.output_root.resolve().parents
        ):
            raise AcquisitionError("market-data output root must be outside the Git worktree")


@dataclass(frozen=True)
class PartitionPlan:
    start: datetime
    end: datetime

    @property
    def key(self) -> str:
        return f"{self.start:%Y-%m}"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    def __call__(self, url: str, headers: Mapping[str, str]) -> HttpResponse: ...


@dataclass(frozen=True)
class AcquisitionResult:
    ok: bool
    source: str
    symbol: str
    feed: str
    timeframe: str
    partition_count: int
    total_bars: int
    manifest_paths: list[str]
    research_eligible: bool
    rights_status: str


def plan_monthly_partitions(
    request: HistoricalDataRequest,
    *,
    now: datetime,
) -> list[PartitionPlan]:
    """Build closed-open monthly request ranges after validating the free-data boundary."""

    request.validate(now=now)
    cursor = date(request.start.year, request.start.month, 1)
    requested_end = request.end + timedelta(days=1)
    plans: list[PartitionPlan] = []
    while cursor < requested_end:
        next_month = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
        partition_start = max(cursor, request.start)
        partition_end = min(next_month, requested_end)
        plans.append(
            PartitionPlan(
                start=datetime.combine(partition_start, datetime_time.min, tzinfo=UTC),
                end=datetime.combine(partition_end, datetime_time.min, tzinfo=UTC),
            )
        )
        cursor = next_month
    return plans


def acquire_historical_spy(
    request: HistoricalDataRequest,
    *,
    api_key_id: str,
    api_secret_key: str,
    transport: HttpTransport | None = None,
    now: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE,
    max_retries: int = 5,
) -> AcquisitionResult:
    """Acquire immutable monthly raw pages without importing or activating them."""

    if not api_key_id.strip() or not api_secret_key.strip():
        raise AcquisitionError("Alpaca data credentials are required in the environment")
    if requests_per_minute <= 0 or requests_per_minute > 200:
        raise AcquisitionError("requests_per_minute must be between 1 and 200")
    current_time = (now or (lambda: datetime.now(UTC)))()
    plans = plan_monthly_partitions(request, now=current_time)
    request.output_root.expanduser().resolve().mkdir(parents=True, exist_ok=True)
    sender = transport or _urllib_transport
    manifests: list[str] = []
    total_bars = 0
    last_request_at: float | None = None
    for plan in plans:
        manifest_path, bar_count, last_request_at = _acquire_partition(
            request,
            plan=plan,
            api_key_id=api_key_id,
            api_secret_key=api_secret_key,
            transport=sender,
            cutoff=current_time.astimezone(UTC) - FREE_DATA_DELAY,
            sleep=sleep,
            monotonic=monotonic,
            requests_per_minute=requests_per_minute,
            max_retries=max_retries,
            last_request_at=last_request_at,
            run_time=current_time,
        )
        manifests.append(manifest_path.as_posix())
        total_bars += bar_count
    return AcquisitionResult(
        ok=True,
        source="alpaca_sip",
        symbol="SPY",
        feed="sip",
        timeframe="1Min",
        partition_count=len(plans),
        total_bars=total_bars,
        manifest_paths=manifests,
        research_eligible=False,
        rights_status="written_rights_unverified",
    )


def _acquire_partition(
    request: HistoricalDataRequest,
    *,
    plan: PartitionPlan,
    api_key_id: str,
    api_secret_key: str,
    transport: HttpTransport,
    cutoff: datetime,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    requests_per_minute: int,
    max_retries: int,
    last_request_at: float | None,
    run_time: datetime,
) -> tuple[Path, int, float | None]:
    partition_dir = (
        request.output_root.expanduser().resolve()
        / "symbol=SPY"
        / f"year={plan.start.year:04d}"
        / f"month={plan.start.month:02d}"
    )
    partition_dir.mkdir(parents=True, exist_ok=True)
    request_metadata = {
        "symbol": "SPY",
        "feed": "sip",
        "timeframe": "1Min",
        "adjustment": "raw",
        "sort": "asc",
        "start": _iso_z(plan.start),
        "end": _iso_z(plan.end),
        "endpoint": f"{ALPACA_DATA_BASE_URL}{ALPACA_BARS_PATH}",
    }
    request_fingerprint = _json_sha256(request_metadata)
    run_dir, checkpoint = _resume_or_create_run(
        partition_dir,
        request_fingerprint=request_fingerprint,
        request_metadata=request_metadata,
        run_time=run_time,
    )
    pages_dir = run_dir / "raw_pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_token = checkpoint.get("next_page_token")
    observed_token_hashes = set(checkpoint.get("requested_page_token_sha256", []))
    page_number = len(checkpoint.get("pages", [])) + 1
    while checkpoint.get("status") != "download_complete":
        token_marker = page_token or "__first__"
        token_hash = _sha256_bytes(str(token_marker).encode("utf-8"))
        if token_hash in observed_token_hashes:
            raise AcquisitionError("Alpaca pagination token repeated")
        observed_token_hashes.add(token_hash)
        parameters = {
            "timeframe": "1Min",
            "start": _iso_z(plan.start),
            "end": _iso_z(plan.end),
            "limit": "10000",
            "adjustment": "raw",
            "feed": "sip",
            "sort": "asc",
        }
        if page_token:
            parameters["page_token"] = str(page_token)
        url = (
            f"{ALPACA_DATA_BASE_URL}{ALPACA_BARS_PATH}?"
            f"{urllib.parse.urlencode(parameters)}"
        )
        response, last_request_at = _request_with_retry(
            url,
            headers={
                "APCA-API-KEY-ID": api_key_id,
                "APCA-API-SECRET-KEY": api_secret_key,
                "Accept": "application/json",
                "User-Agent": "quant-system-historical-data/1",
            },
            transport=transport,
            sleep=sleep,
            monotonic=monotonic,
            requests_per_minute=requests_per_minute,
            max_retries=max_retries,
            last_request_at=last_request_at,
        )
        payload, bars, next_token = _validate_page(
            response.body,
            plan=plan,
            cutoff=cutoff,
            previous_last_timestamp=checkpoint.get("last_timestamp"),
        )
        page_path = pages_dir / f"page-{page_number:06d}.json"
        _write_immutable(page_path, response.body)
        page_sha256 = _sha256_bytes(response.body)
        checkpoint["pages"].append(
            {
                "path": page_path.relative_to(run_dir).as_posix(),
                "sha256": page_sha256,
                "bar_count": len(bars),
                "first_timestamp": bars[0]["t"] if bars else None,
                "last_timestamp": bars[-1]["t"] if bars else None,
                "requested_page_token_sha256": (
                    _sha256_bytes(str(page_token).encode("utf-8")) if page_token else None
                ),
                "next_page_token_sha256": (
                    _sha256_bytes(str(next_token).encode("utf-8")) if next_token else None
                ),
                "response_symbol": payload.get("symbol"),
            }
        )
        checkpoint["requested_page_token_sha256"] = sorted(observed_token_hashes)
        checkpoint["next_page_token"] = next_token
        checkpoint["bar_count"] = int(checkpoint.get("bar_count", 0)) + len(bars)
        if bars:
            checkpoint["first_timestamp"] = checkpoint.get("first_timestamp") or bars[0]["t"]
            checkpoint["last_timestamp"] = bars[-1]["t"]
        if not next_token:
            checkpoint["status"] = "download_complete"
        _write_json_atomic(run_dir / "checkpoint.json", checkpoint)
        page_token = next_token
        page_number += 1

    data_path = run_dir / f"alpaca-sip-SPY-{plan.start:%Y%m}.json.gz"
    bars = _assemble_monthly_bars(run_dir, checkpoint)
    data_payload = {
        "schema_version": 1,
        "source": "alpaca_sip",
        "symbol": "SPY",
        "feed": "sip",
        "timeframe": "1Min",
        "adjustment": "raw",
        "sort": "asc",
        "start": _iso_z(plan.start),
        "end": _iso_z(plan.end),
        "bars": bars,
    }
    _write_immutable_gzip_json(data_path, data_payload)
    manifest_path = run_dir / "acquisition_manifest.json"
    manifest = {
        "manifest_version": 1,
        "source": "alpaca_sip",
        "request": request_metadata,
        "request_fingerprint": request_fingerprint,
        "acquired_at": checkpoint["acquired_at"],
        "bar_count": len(bars),
        "first_timestamp": bars[0]["t"] if bars else None,
        "last_timestamp": bars[-1]["t"] if bars else None,
        "pages": checkpoint["pages"],
        "data_file": data_path.name,
        "data_sha256": _sha256_file(data_path),
        "research_eligible": False,
        "rights_status": "written_rights_unverified",
        "automatically_activated": False,
        "automatically_derived": False,
        "automatically_backtested": False,
    }
    _write_immutable(manifest_path, _json_bytes(manifest))
    checkpoint["status"] = "complete"
    checkpoint.pop("next_page_token", None)
    _write_json_atomic(run_dir / "checkpoint.json", checkpoint)
    return manifest_path, len(bars), last_request_at


def _resume_or_create_run(
    partition_dir: Path,
    *,
    request_fingerprint: str,
    request_metadata: dict[str, str],
    run_time: datetime,
) -> tuple[Path, dict[str, Any]]:
    runs_dir = partition_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for checkpoint_path in sorted(runs_dir.glob("*/checkpoint.json"), reverse=True):
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if (
            payload.get("request_fingerprint") == request_fingerprint
            and payload.get("status") in {"in_progress", "download_complete"}
        ):
            _verify_checkpoint_pages(checkpoint_path.parent, payload)
            return checkpoint_path.parent, payload
    run_id = f"{run_time.astimezone(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:12]}"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=False, exist_ok=False)
    checkpoint: dict[str, Any] = {
        "checkpoint_version": 1,
        "status": "in_progress",
        "request": request_metadata,
        "request_fingerprint": request_fingerprint,
        "acquired_at": _iso_z(run_time.astimezone(UTC)),
        "pages": [],
        "requested_page_token_sha256": [],
        "next_page_token": None,
        "bar_count": 0,
    }
    _write_json_atomic(run_dir / "checkpoint.json", checkpoint)
    return run_dir, checkpoint


def _verify_checkpoint_pages(run_dir: Path, checkpoint: Mapping[str, Any]) -> None:
    for page in checkpoint.get("pages", []):
        page_path = (run_dir / str(page["path"])).resolve()
        if not page_path.is_relative_to(run_dir.resolve()) or not page_path.is_file():
            raise AcquisitionError("acquisition checkpoint references a missing raw page")
        if _sha256_file(page_path) != page.get("sha256"):
            raise AcquisitionError("raw page checksum drift detected during resume")


def _assemble_monthly_bars(run_dir: Path, checkpoint: Mapping[str, Any]) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    for page in checkpoint.get("pages", []):
        path = run_dir / str(page["path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        page_bars = payload.get("bars")
        if not isinstance(page_bars, list):
            raise AcquisitionError("raw page lost its Alpaca bars array")
        bars.extend(page_bars)
    timestamps = [str(bar.get("t", "")) for bar in bars]
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        raise AcquisitionError("assembled Alpaca bars are duplicated or non-chronological")
    return bars


def _validate_page(
    body: bytes,
    *,
    plan: PartitionPlan,
    cutoff: datetime,
    previous_last_timestamp: object,
) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcquisitionError("Alpaca returned malformed JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("bars"), list):
        raise AcquisitionError("Alpaca response must contain a bars array")
    if payload.get("symbol") not in {None, "SPY"}:
        raise AcquisitionError("Alpaca response symbol does not match SPY")
    bars = payload["bars"]
    timestamps: list[datetime] = []
    for index, bar in enumerate(bars):
        if not isinstance(bar, dict) or not _REQUIRED_BAR_FIELDS.issubset(bar):
            raise AcquisitionError(f"Alpaca bar {index} is missing required SIP fields")
        timestamp = _parse_timestamp(bar["t"])
        if not plan.start <= timestamp < plan.end:
            raise AcquisitionError("Alpaca returned a bar outside the requested partition")
        if timestamp > cutoff:
            raise AcquisitionError("Alpaca returned a bar inside the 15-minute free-data boundary")
        _validate_ohlcv(bar, index=index)
        timestamps.append(timestamp)
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        raise AcquisitionError("Alpaca page timestamps are duplicated or non-chronological")
    if (
        timestamps
        and previous_last_timestamp
        and timestamps[0] <= _parse_timestamp(previous_last_timestamp)
    ):
        raise AcquisitionError("Alpaca pagination repeated or reordered bars")
    raw_next = payload.get("next_page_token")
    if raw_next is not None and not isinstance(raw_next, str):
        raise AcquisitionError("Alpaca next_page_token must be a string or null")
    return payload, bars, raw_next


def _validate_ohlcv(bar: Mapping[str, Any], *, index: int) -> None:
    try:
        open_ = Decimal(str(bar["o"]))
        high = Decimal(str(bar["h"]))
        low = Decimal(str(bar["l"]))
        close = Decimal(str(bar["c"]))
        vwap = Decimal(str(bar["vw"]))
        volume = int(bar["v"])
        trades = int(bar["n"])
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AcquisitionError(f"Alpaca bar {index} contains invalid numeric fields") from exc
    prices = (open_, high, low, close, vwap)
    if any(not value.is_finite() or value <= 0 for value in prices):
        raise AcquisitionError(f"Alpaca bar {index} contains invalid prices")
    if high < max(open_, close, low) or low > min(open_, close, high):
        raise AcquisitionError(f"Alpaca bar {index} contains inconsistent OHLC")
    if volume < 0 or trades < 0:
        raise AcquisitionError(f"Alpaca bar {index} contains negative activity")


def _request_with_retry(
    url: str,
    *,
    headers: Mapping[str, str],
    transport: HttpTransport,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    requests_per_minute: int,
    max_retries: int,
    last_request_at: float | None,
) -> tuple[HttpResponse, float]:
    minimum_interval = 60 / requests_per_minute
    for attempt in range(max_retries + 1):
        current = monotonic()
        if last_request_at is not None:
            remaining = minimum_interval - (current - last_request_at)
            if remaining > 0:
                sleep(remaining)
        try:
            response = transport(url, headers)
        except (OSError, TimeoutError) as exc:
            if attempt >= max_retries:
                raise AcquisitionError("Alpaca historical request failed after retries") from exc
            sleep(min(2**attempt, 30))
            last_request_at = monotonic()
            continue
        last_request_at = monotonic()
        if response.status == 200:
            return response, last_request_at
        if response.status == 429 or 500 <= response.status < 600:
            if attempt >= max_retries:
                raise AcquisitionError(
                    f"Alpaca historical request failed with HTTP {response.status}"
                )
            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after is not None else min(2**attempt, 30)
            except ValueError:
                delay = min(2**attempt, 30)
            sleep(max(0, delay))
            continue
        raise AcquisitionError(f"Alpaca historical request failed with HTTP {response.status}")
    raise AcquisitionError("Alpaca historical request exhausted retry policy")


def _urllib_transport(url: str, headers: Mapping[str, str]) -> HttpResponse:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return HttpResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(
            status=exc.code,
            headers=dict(exc.headers.items()) if exc.headers else {},
            body=exc.read(),
        )
    except urllib.error.URLError as exc:
        raise OSError("Alpaca historical endpoint is unavailable") from exc


def _parse_timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AcquisitionError("Alpaca returned an invalid timestamp") from exc
    if parsed.tzinfo is None:
        raise AcquisitionError("Alpaca timestamps must include a timezone")
    return parsed.astimezone(UTC)


def _write_immutable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        if _sha256_file(path) != _sha256_bytes(content):
            raise AcquisitionError(
                f"immutable acquisition artifact collision: {path.name}"
            ) from exc


def _write_immutable_gzip_json(path: Path, payload: Mapping[str, Any]) -> None:
    content = _json_bytes(payload)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream:
                stream.write(content)
            raw.flush()
            os.fsync(raw.fileno())
        _write_immutable(path, temporary.read_bytes())
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(_json_bytes(payload))
    os.replace(temporary, path)


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _json_sha256(payload: Mapping[str, Any]) -> str:
    return _sha256_bytes(_json_bytes(payload))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def acquisition_result_json(result: AcquisitionResult) -> str:
    """Render a no-secret acquisition summary for the standalone script."""

    return json.dumps(asdict(result), indent=2, sort_keys=True)
