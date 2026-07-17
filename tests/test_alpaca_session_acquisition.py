from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import exchange_calendars as xcals  # type: ignore[import-untyped]
import pytest

from trader.data.alpaca_acquisition import (
    AcquisitionError,
    HttpResponse,
    SessionDataRequest,
    _urllib_transport,
    acquire_spy_session,
    plan_session_partition,
    session_plan_payload,
)
from trader.data.alpaca_session_artifacts import (
    AlpacaSessionArtifactError,
    load_alpaca_session,
)


def _request(tmp_path: Path, session_date: date) -> SessionDataRequest:
    return SessionDataRequest(
        symbol="SPY",
        feed="sip",
        timeframe="1Min",
        session_date=session_date,
        output_root=tmp_path / "market-data",
    )


def _session_times(session_date: date) -> list[str]:
    return [
        value.to_pydatetime().astimezone(UTC).isoformat().replace("+00:00", "Z")
        for value in xcals.get_calendar("XNYS").session_minutes(session_date)
    ]


def _bars(session_date: date, *, revised_close: str | None = None) -> list[dict[str, object]]:
    values = []
    for index, timestamp in enumerate(_session_times(session_date)):
        values.append(
            {
                "t": timestamp,
                "o": 500,
                "h": 501,
                "l": 499,
                "c": revised_close if index == 0 and revised_close else 500.5,
                "v": 1000 + index,
                "n": 20 + index,
                "vw": 500.25,
            }
        )
    return values


def _response(
    bars: list[dict[str, object]],
    *,
    headers: dict[str, str] | None = None,
    metadata: dict[str, object] | None = None,
) -> HttpResponse:
    payload: dict[str, object] = {"bars": bars, "symbol": "SPY", "next_page_token": None}
    payload.update(metadata or {})
    return HttpResponse(
        status=200,
        headers=headers or {},
        body=json.dumps(payload, separators=(",", ":")).encode(),
    )


@pytest.mark.parametrize(
    ("session_date", "expected_count", "expected_start", "expected_end"),
    [
        (date(2025, 1, 2), 390, "2025-01-02T14:30:00Z", "2025-01-02T20:59:00Z"),
        (date(2025, 11, 28), 210, "2025-11-28T14:30:00Z", "2025-11-28T17:59:00Z"),
    ],
)
def test_session_capture_requires_exact_xnys_grid_and_inclusive_api_end(
    tmp_path: Path,
    session_date: date,
    expected_count: int,
    expected_start: str,
    expected_end: str,
) -> None:
    calendar = xcals.get_calendar("XNYS")
    now = calendar.session_close(session_date).to_pydatetime() + timedelta(minutes=20)
    urls: list[str] = []

    def transport(url: str, _headers) -> HttpResponse:
        urls.append(url)
        return _response(
            _bars(session_date),
            headers={"X-Request-ID": f"request-{session_date.isoformat()}"},
        )

    result = acquire_spy_session(
        _request(tmp_path, session_date),
        api_key_id="key",
        api_secret_key="secret",
        transport=transport,
        now=lambda: now,
        sleep=lambda _: None,
        monotonic=lambda: 100.0,
    )

    assert result.total_bars == expected_count
    query = parse_qs(urlparse(urls[0]).query)
    assert query["start"] == [expected_start]
    assert query["end"] == [expected_end]
    manifest = load_alpaca_session(Path(result.manifest_paths[0])).manifest
    assert manifest["expected_bar_count"] == expected_count
    assert manifest["session_complete"] is True
    assert manifest["source_response_ids"] == [f"request-{session_date.isoformat()}"]
    assert manifest["research_eligible"] is False
    assert manifest["promotion_eligible"] is False
    assert manifest["graduation_eligible"] is False
    assert manifest["broker_contacted"] is False
    assert manifest["order_api_invoked"] is False


def test_session_plan_covers_dst_and_close_plus_twenty_gate(tmp_path: Path) -> None:
    before_dst = date(2025, 3, 7)
    after_dst = date(2025, 3, 10)
    calendar = xcals.get_calendar("XNYS")
    before_close = calendar.session_close(before_dst).to_pydatetime()
    after_close = calendar.session_close(after_dst).to_pydatetime()

    before = plan_session_partition(
        _request(tmp_path, before_dst),
        now=before_close + timedelta(minutes=20),
    )
    after = plan_session_partition(
        _request(tmp_path, after_dst),
        now=after_close + timedelta(minutes=20),
    )
    assert before.start.hour == 14
    assert after.start.hour == 13
    with pytest.raises(AcquisitionError, match="20 minutes"):
        plan_session_partition(
            _request(tmp_path, after_dst),
            now=after_close + timedelta(minutes=20) - timedelta(microseconds=1),
        )
    payload = session_plan_payload(
        _request(tmp_path, after_dst),
        now=after_close + timedelta(minutes=20),
    )
    assert payload["credentials_read"] is False
    assert payload["network_accessed"] is False
    assert payload["request_fingerprint"]


def test_session_plan_rejects_holiday(tmp_path: Path) -> None:
    with pytest.raises(AcquisitionError, match="not an XNYS"):
        plan_session_partition(
            _request(tmp_path, date(2025, 7, 4)),
            now=datetime(2025, 7, 5, tzinfo=UTC),
        )


def test_incomplete_session_keeps_raw_pages_but_publishes_no_manifest(
    tmp_path: Path,
) -> None:
    session_date = date(2025, 1, 2)
    calendar = xcals.get_calendar("XNYS")
    now = calendar.session_close(session_date).to_pydatetime() + timedelta(minutes=20)
    incomplete = _bars(session_date)
    incomplete.pop(100)

    with pytest.raises(AcquisitionError, match="incomplete XNYS session"):
        acquire_spy_session(
            _request(tmp_path, session_date),
            api_key_id="key",
            api_secret_key="secret",
            transport=lambda _url, _headers: _response(incomplete),
            now=lambda: now,
            sleep=lambda _: None,
            monotonic=lambda: 100.0,
        )

    assert list(_request(tmp_path, session_date).output_root.rglob("raw_pages/*.json"))
    assert not list(
        _request(tmp_path, session_date).output_root.rglob("acquisition_manifest.json")
    )


def test_incomplete_session_retry_uses_a_fresh_immutable_run(tmp_path: Path) -> None:
    session_date = date(2025, 1, 2)
    close = xcals.get_calendar("XNYS").session_close(session_date).to_pydatetime()
    request = _request(tmp_path, session_date)
    incomplete = _bars(session_date)
    incomplete.pop(100)
    calls = 0

    def first_transport(_url: str, _headers) -> HttpResponse:
        nonlocal calls
        calls += 1
        return _response(incomplete)

    with pytest.raises(AcquisitionError, match="incomplete XNYS session"):
        acquire_spy_session(
            request,
            api_key_id="key",
            api_secret_key="secret",
            transport=first_transport,
            now=lambda: close + timedelta(minutes=20),
            sleep=lambda _: None,
            monotonic=lambda: 100.0,
        )

    result = acquire_spy_session(
        request,
        api_key_id="key",
        api_secret_key="secret",
        transport=lambda _url, _headers: _response(_bars(session_date)),
        now=lambda: close + timedelta(minutes=21),
        sleep=lambda _: None,
        monotonic=lambda: 100.0,
    )

    assert calls == 1
    assert Path(result.manifest_paths[0]).is_file()
    checkpoints = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in request.output_root.rglob("checkpoint.json")
    ]
    assert sorted(item["status"] for item in checkpoints) == ["complete", "failed"]


def test_session_capture_rejects_response_metadata_drift(tmp_path: Path) -> None:
    session_date = date(2025, 1, 2)
    close = xcals.get_calendar("XNYS").session_close(session_date).to_pydatetime()
    request = _request(tmp_path, session_date)
    with pytest.raises(AcquisitionError, match="feed drifted"):
        acquire_spy_session(
            request,
            api_key_id="key",
            api_secret_key="secret",
            transport=lambda _url, _headers: _response(
                _bars(session_date), metadata={"feed": "iex"}
            ),
            now=lambda: close + timedelta(minutes=20),
            sleep=lambda _: None,
            monotonic=lambda: 100.0,
        )

    failed_pages = list(request.output_root.rglob("raw_pages/attempts/*.json"))
    assert len(failed_pages) == 1
    checkpoint = json.loads(
        next(request.output_root.rglob("checkpoint.json")).read_text(encoding="utf-8")
    )
    assert checkpoint["response_attempts"][0]["outcome"] == "rejected_validation"
    assert checkpoint["pages"] == []


def test_reacquisition_creates_distinct_immutable_session_revisions(tmp_path: Path) -> None:
    session_date = date(2025, 1, 2)
    close = xcals.get_calendar("XNYS").session_close(session_date).to_pydatetime()
    request = _request(tmp_path, session_date)
    first = acquire_spy_session(
        request,
        api_key_id="key",
        api_secret_key="secret",
        transport=lambda _url, _headers: _response(_bars(session_date)),
        now=lambda: close + timedelta(minutes=20),
        sleep=lambda _: None,
        monotonic=lambda: 100.0,
    )
    second = acquire_spy_session(
        request,
        api_key_id="key",
        api_secret_key="secret",
        transport=lambda _url, _headers: _response(
            _bars(session_date, revised_close="500.75")
        ),
        now=lambda: close + timedelta(days=1),
        sleep=lambda _: None,
        monotonic=lambda: 100.0,
    )

    assert first.manifest_paths != second.manifest_paths
    assert len(list(request.output_root.rglob("acquisition_manifest.json"))) == 2


def test_offline_loader_rejects_raw_to_data_lineage_drift(tmp_path: Path) -> None:
    session_date = date(2025, 1, 2)
    close = xcals.get_calendar("XNYS").session_close(session_date).to_pydatetime()
    result = acquire_spy_session(
        _request(tmp_path, session_date),
        api_key_id="key",
        api_secret_key="secret",
        transport=lambda _url, _headers: _response(_bars(session_date)),
        now=lambda: close + timedelta(minutes=20),
        sleep=lambda _: None,
        monotonic=lambda: 100.0,
    )
    manifest_path = Path(result.manifest_paths[0])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_path = manifest_path.parent / manifest["pages"][0]["path"]
    raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
    raw_payload["bars"][0]["c"] = 500.75
    raw_bytes = json.dumps(raw_payload, separators=(",", ":")).encode()
    raw_path.write_bytes(raw_bytes)
    manifest["pages"][0]["sha256"] = hashlib.sha256(raw_bytes).hexdigest()
    attempt_path = manifest_path.parent / manifest["response_attempts"][0]["path"]
    attempt_path.write_bytes(raw_bytes)
    manifest["response_attempts"][0]["sha256"] = hashlib.sha256(raw_bytes).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(AlpacaSessionArtifactError, match="raw pages do not match"):
        load_alpaca_session(manifest_path)


def test_offline_loader_binds_accepted_response_to_raw_page(tmp_path: Path) -> None:
    session_date = date(2025, 1, 2)
    close = xcals.get_calendar("XNYS").session_close(session_date).to_pydatetime()
    result = acquire_spy_session(
        _request(tmp_path, session_date),
        api_key_id="key",
        api_secret_key="secret",
        transport=lambda _url, _headers: _response(
            _bars(session_date), headers={"X-Request-ID": "request-lineage"}
        ),
        now=lambda: close + timedelta(minutes=20),
        sleep=lambda _: None,
        monotonic=lambda: 100.0,
    )
    manifest_path = Path(result.manifest_paths[0])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    attempt = manifest["response_attempts"][0]
    attempt_path = manifest_path.parent / attempt["path"]
    altered_attempt = attempt_path.read_bytes() + b"\n"
    attempt_path.write_bytes(altered_attempt)
    attempt["sha256"] = hashlib.sha256(altered_attempt).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(AlpacaSessionArtifactError, match="checksum does not match"):
        load_alpaca_session(manifest_path)


def test_urllib_transport_rejects_redirect_without_forwarding_credentials() -> None:
    target_hits = 0
    target_secret_headers: list[str | None] = []

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            nonlocal target_hits
            if self.path == "/source":
                self.send_response(302)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{self.server.server_port}/target",
                )
                self.end_headers()
                return
            target_hits += 1
            target_secret_headers.append(self.headers.get("APCA-API-SECRET-KEY"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = _urllib_transport(
            f"http://127.0.0.1:{server.server_port}/source",
            {
                "APCA-API-KEY-ID": "test-key",
                "APCA-API-SECRET-KEY": "test-secret",
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 302
    assert target_hits == 0
    assert target_secret_headers == []
