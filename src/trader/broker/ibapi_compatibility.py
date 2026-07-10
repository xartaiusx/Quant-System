"""Offline compatibility check for the installed IBKR Python API client."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType

MIN_REQUIRED_SERVER_VERSION = 163
OFFICIAL_API_URL = "https://interactivebrokers.github.io/"


@dataclass(frozen=True)
class IbapiCompatibility:
    """Describe whether the installed client supports required protocol features."""

    importable: bool
    package_version: str | None
    max_supported_server_version: int | None
    compatible: bool
    errors: tuple[str, ...] = ()


def inspect_ibapi(
    *,
    ibapi_module: ModuleType | None = None,
    server_versions_module: ModuleType | None = None,
) -> IbapiCompatibility:
    """Inspect local modules only; never connect to TWS or IB Gateway."""

    try:
        selected_ibapi = ibapi_module or importlib.import_module("ibapi")
        selected_server_versions = server_versions_module or importlib.import_module(
            "ibapi.server_versions"
        )
    except (ImportError, ModuleNotFoundError) as exc:
        return IbapiCompatibility(
            importable=False,
            package_version=None,
            max_supported_server_version=None,
            compatible=False,
            errors=(f"ibapi import failed: {exc}",),
        )

    version = str(getattr(selected_ibapi, "__version__", "unknown"))
    protocol_versions = [
        value
        for name, value in vars(selected_server_versions).items()
        if name.startswith("MIN_SERVER_VER_") and isinstance(value, int)
    ]
    max_supported = max(protocol_versions, default=None)
    errors: list[str] = []
    if max_supported is None:
        errors.append("ibapi server protocol constants are unavailable")
    elif max_supported < MIN_REQUIRED_SERVER_VERSION:
        errors.append(
            "installed ibapi supports server protocol "
            f"{max_supported}; at least {MIN_REQUIRED_SERVER_VERSION} is required"
        )

    return IbapiCompatibility(
        importable=True,
        package_version=version,
        max_supported_server_version=max_supported,
        compatible=not errors,
        errors=tuple(errors),
    )


def main() -> int:
    """Print compatibility evidence and return a shell-friendly status code."""

    report = inspect_ibapi()
    print(f"ibapi import: {'ok' if report.importable else 'failed'}")
    print(f"ibapi version: {report.package_version or 'unavailable'}")
    print(
        "ibapi max server protocol: "
        f"{report.max_supported_server_version or 'unavailable'}"
    )
    print(f"required server protocol: {MIN_REQUIRED_SERVER_VERSION}")
    print(f"ibapi compatibility: {'ok' if report.compatible else 'failed'}")
    for error in report.errors:
        print(f"error: {error}")
    if not report.compatible:
        print("Install the current Stable or Latest TWS API from IBKR's official download.")
        print(f"Official download: {OFFICIAL_API_URL}")
    print("Broker contacted: false")
    print("Order APIs invoked: false")
    return 0 if report.compatible else 1


if __name__ == "__main__":
    raise SystemExit(main())
