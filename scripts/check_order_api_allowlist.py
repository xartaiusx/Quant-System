"""Fail when production order API names escape the approved paper executor."""

from __future__ import annotations

from pathlib import Path

_ALLOWED_ORDER_API_PATHS = {
    Path("src/trader/execution/paper_order_smoke.py"),
}
_MUTATING_ORDER_APIS = ("placeOrder", "cancelOrder")
_GLOBALLY_FORBIDDEN_ORDER_APIS = ("reqGlobalCancel",)


def main() -> int:
    offenders: list[str] = []
    for path in sorted(Path("src").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for api_name in _MUTATING_ORDER_APIS:
            if api_name in source and path not in _ALLOWED_ORDER_API_PATHS:
                offenders.append(f"{path.as_posix()}: disallowed {api_name}")
        for api_name in _GLOBALLY_FORBIDDEN_ORDER_APIS:
            if api_name in source:
                offenders.append(f"{path.as_posix()}: forbidden {api_name}")
    if offenders:
        print("\n".join(offenders))
        return 1
    print("Production order API allowlist passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
