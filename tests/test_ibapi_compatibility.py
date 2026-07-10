from types import ModuleType

import pytest

from trader.broker.ibapi_compatibility import (
    MIN_REQUIRED_SERVER_VERSION,
    inspect_ibapi,
)


def _ibapi_module(version: str) -> ModuleType:
    module = ModuleType("ibapi")
    module.__version__ = version
    return module


def _server_versions_module(maximum: int) -> ModuleType:
    module = ModuleType("ibapi.server_versions")
    module.MIN_SERVER_VER_BASE = 38
    module.MIN_SERVER_VER_REQUIRED_FEATURE = maximum
    return module


def test_current_protocol_is_compatible() -> None:
    report = inspect_ibapi(
        ibapi_module=_ibapi_module("10.40.1"),
        server_versions_module=_server_versions_module(MIN_REQUIRED_SERVER_VERSION),
    )

    assert report.importable is True
    assert report.package_version == "10.40.1"
    assert report.max_supported_server_version == MIN_REQUIRED_SERVER_VERSION
    assert report.compatible is True
    assert report.errors == ()


def test_legacy_protocol_fails_closed() -> None:
    report = inspect_ibapi(
        ibapi_module=_ibapi_module("9.81.1-1"),
        server_versions_module=_server_versions_module(157),
    )

    assert report.importable is True
    assert report.max_supported_server_version == 157
    assert report.compatible is False
    assert "at least 163 is required" in report.errors[0]


def test_missing_protocol_constants_fail_closed() -> None:
    report = inspect_ibapi(
        ibapi_module=_ibapi_module("unknown"),
        server_versions_module=ModuleType("ibapi.server_versions"),
    )

    assert report.importable is True
    assert report.max_supported_server_version is None
    assert report.compatible is False
    assert report.errors == ("ibapi server protocol constants are unavailable",)


def test_missing_ibapi_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_module(name: str) -> ModuleType:
        raise ModuleNotFoundError(f"No module named '{name}'")

    monkeypatch.setattr(
        "trader.broker.ibapi_compatibility.importlib.import_module",
        missing_module,
    )

    report = inspect_ibapi()

    assert report.importable is False
    assert report.package_version is None
    assert report.max_supported_server_version is None
    assert report.compatible is False
    assert report.errors == ("ibapi import failed: No module named 'ibapi'",)
