from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from trader.data.alpaca_acquisition import (
    AcquisitionError,
    HistoricalDataRequest,
    HttpResponse,
    acquire_historical_spy,
    plan_monthly_partitions,
)

_NOW = datetime(2026, 1, 5, 12, tzinfo=UTC)


def _request(tmp_path: Path, *, start: date | None = None, end: date | None = None):
    return HistoricalDataRequest(
        symbol="SPY",
        feed="sip",
        timeframe="1Min",
        start=start or date(2025, 1, 2),
        end=end or date(2025, 1, 31),
        output_root=tmp_path / "market-data",
    )


def _bar(timestamp: str, *, close: str = "500.01") -> dict[str, object]:
    return {
        "t": timestamp,
        "o": 500.0,
        "h": 500.02,
        "l": 499.99,
        "c": close,
        "v": 1000,
        "n": 20,
        "vw": 500.005,
    }


def _response(bars: list[dict[str, object]], token: str | None = None) -> HttpResponse:
    return HttpResponse(
        status=200,
        headers={},
        body=json.dumps(
            {"bars": bars, "symbol": "SPY", "next_page_token": token},
            separators=(",", ":"),
        ).encode(),
    )


def test_plans_monthly_closed_open_partitions(tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        start=date(2024, 12, 15),
        end=date(2025, 2, 4),
    )

    plans = plan_monthly_partitions(request, now=_NOW)

    assert [(item.start.isoformat(), item.end.isoformat()) for item in plans] == [
        ("2024-12-15T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
        ("2025-01-01T00:00:00+00:00", "2025-02-01T00:00:00+00:00"),
        ("2025-02-01T00:00:00+00:00", "2025-02-05T00:00:00+00:00"),
    ]


def test_acquires_paginated_immutable_pages_and_nonpromoting_manifest(tmp_path: Path) -> None:
    responses = iter(
        [
            _response([_bar("2025-01-02T14:30:00Z")], "next-secret-token"),
            _response([_bar("2025-01-02T14:31:00Z")]),
        ]
    )
    requests: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, headers) -> HttpResponse:
        requests.append((url, dict(headers)))
        return next(responses)

    result = acquire_historical_spy(
        _request(tmp_path),
        api_key_id="test-key-id",
        api_secret_key="test-secret-key",
        transport=transport,
        now=lambda: _NOW,
        sleep=lambda _: None,
        monotonic=lambda: 100.0,
    )

    assert result.ok is True
    assert result.total_bars == 2
    assert result.research_eligible is False
    assert result.rights_status == "written_rights_unverified"
    assert len(requests) == 2
    first_query = parse_qs(urlparse(requests[0][0]).query)
    assert first_query["feed"] == ["sip"]
    assert first_query["adjustment"] == ["raw"]
    assert first_query["sort"] == ["asc"]
    assert "page_token" not in first_query
    assert parse_qs(urlparse(requests[1][0]).query)["page_token"] == [
        "next-secret-token"
    ]
    manifest_path = Path(result.manifest_paths[0])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["bar_count"] == 2
    assert manifest["research_eligible"] is False
    assert manifest["automatically_activated"] is False
    assert "next-secret-token" not in json.dumps(manifest)
    data_path = manifest_path.parent / manifest["data_file"]
    with gzip.open(data_path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert [bar["t"] for bar in payload["bars"]] == [
        "2025-01-02T14:30:00Z",
        "2025-01-02T14:31:00Z",
    ]
    all_artifact_text = "".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in manifest_path.parent.rglob("*")
        if path.is_file() and path.suffix != ".gz"
    )
    assert "test-key-id" not in all_artifact_text
    assert "test-secret-key" not in all_artifact_text
    assert "next-secret-token" not in manifest_path.read_text(encoding="utf-8")


def test_retries_rate_limit_without_exposing_credentials(tmp_path: Path) -> None:
    responses = iter(
        [
            HttpResponse(status=429, headers={"Retry-After": "2"}, body=b"{}"),
            _response([_bar("2025-01-02T14:30:00Z")]),
        ]
    )
    sleeps: list[float] = []

    result = acquire_historical_spy(
        _request(tmp_path),
        api_key_id="key",
        api_secret_key="secret",
        transport=lambda _url, _headers: next(responses),
        now=lambda: _NOW,
        sleep=sleeps.append,
        monotonic=lambda: 100.0,
    )

    assert result.ok is True
    assert 2.0 in sleeps
    manifest = json.loads(Path(result.manifest_paths[0]).read_text(encoding="utf-8"))
    assert [item["http_status"] for item in manifest["response_attempts"]] == [429, 200]
    assert [item["outcome"] for item in manifest["response_attempts"]] == [
        "rejected_http",
        "accepted",
    ]


def test_interrupted_run_resumes_from_next_page(tmp_path: Path) -> None:
    first_responses = iter(
        [
            _response([_bar("2025-01-02T14:30:00Z")], "resume-token"),
            OSError("offline"),
        ]
    )

    def interrupted(_url: str, _headers) -> HttpResponse:
        response = next(first_responses)
        if isinstance(response, OSError):
            raise response
        return response

    with pytest.raises(AcquisitionError, match="after retries"):
        acquire_historical_spy(
            _request(tmp_path),
            api_key_id="key",
            api_secret_key="secret",
            transport=interrupted,
            now=lambda: _NOW,
            sleep=lambda _: None,
            monotonic=lambda: 100.0,
            max_retries=0,
        )

    seen_urls: list[str] = []

    def resumed(url: str, _headers) -> HttpResponse:
        seen_urls.append(url)
        return _response([_bar("2025-01-02T14:31:00Z")])

    result = acquire_historical_spy(
        _request(tmp_path),
        api_key_id="key",
        api_secret_key="secret",
        transport=resumed,
        now=lambda: _NOW,
        sleep=lambda _: None,
        monotonic=lambda: 100.0,
    )

    assert result.total_bars == 2
    assert parse_qs(urlparse(seen_urls[0]).query)["page_token"] == ["resume-token"]
    assert len(list(_request(tmp_path).output_root.rglob("page-000001.json"))) == 1


def test_resume_rejects_raw_page_checksum_drift(tmp_path: Path) -> None:
    responses = iter(
        [_response([_bar("2025-01-02T14:30:00Z")], "resume"), OSError("stop")]
    )

    def interrupted(_url: str, _headers) -> HttpResponse:
        response = next(responses)
        if isinstance(response, OSError):
            raise response
        return response

    with pytest.raises(AcquisitionError):
        acquire_historical_spy(
            _request(tmp_path),
            api_key_id="key",
            api_secret_key="secret",
            transport=interrupted,
            now=lambda: _NOW,
            sleep=lambda _: None,
            monotonic=lambda: 100.0,
            max_retries=0,
        )
    page = next(_request(tmp_path).output_root.rglob("page-000001.json"))
    page.write_text("{}", encoding="utf-8")

    with pytest.raises(AcquisitionError, match="checksum drift"):
        acquire_historical_spy(
            _request(tmp_path),
            api_key_id="key",
            api_secret_key="secret",
            transport=lambda _url, _headers: _response([]),
            now=lambda: _NOW,
        )


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (HttpResponse(status=200, headers={}, body=b"not-json"), "malformed JSON"),
        (_response([{"t": "2025-01-02T14:30:00Z"}]), "missing required SIP fields"),
        (
            _response(
                [
                    _bar("2025-01-02T14:30:00Z"),
                    _bar("2025-01-02T14:30:00Z"),
                ]
            ),
            "duplicated or non-chronological",
        ),
    ],
)
def test_fails_closed_on_malformed_or_duplicate_payloads(
    tmp_path: Path,
    response: HttpResponse,
    message: str,
) -> None:
    with pytest.raises(AcquisitionError, match=message):
        acquire_historical_spy(
            _request(tmp_path),
            api_key_id="key",
            api_secret_key="secret",
            transport=lambda _url, _headers: response,
            now=lambda: _NOW,
            sleep=lambda _: None,
            monotonic=lambda: 100.0,
        )


def test_rejects_missing_credentials_and_unavailable_period(tmp_path: Path) -> None:
    with pytest.raises(AcquisitionError, match="credentials"):
        acquire_historical_spy(
            _request(tmp_path),
            api_key_id="",
            api_secret_key="",
            now=lambda: _NOW,
        )
    recent = _request(tmp_path, start=date(2026, 1, 5), end=date(2026, 1, 5))
    with pytest.raises(AcquisitionError, match="15-minute"):
        plan_monthly_partitions(recent, now=_NOW)


def test_acquisition_module_has_no_broker_or_execution_path() -> None:
    source = Path("src/trader/data/alpaca_acquisition.py").read_text(encoding="utf-8")
    for forbidden in (
        "trader.broker",
        "trader.execution",
        "placeOrder",
        "cancelOrder",
        "reqGlobalCancel",
        "/v2/orders",
        "/v2/account",
    ):
        assert forbidden not in source
