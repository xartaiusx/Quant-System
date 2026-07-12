"""Compatibility helpers for IBKR callback signature changes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedIBKRError:
    """Normalized legacy or timestamped `EWrapper.error` callback values."""

    error_time: int | None
    error_code: int
    error_string: str
    advanced_order_reject_json: str


def normalize_ibkr_error_args(args: tuple[object, ...]) -> NormalizedIBKRError:
    """Accept both pre-10.33 and current IBKR Python callback signatures."""

    error_time: object | None = None
    advanced_reject: object = ""
    if len(args) == 2:
        error_code, error_string = args
    elif len(args) == 3 and isinstance(args[1], int):
        error_time, error_code, error_string = args
    elif len(args) == 3:
        error_code, error_string, advanced_reject = args
    elif len(args) == 4:
        error_time, error_code, error_string, advanced_reject = args
    else:
        raise ValueError(f"unsupported IBKR error callback argument count: {len(args)}")

    if not isinstance(error_code, int):
        raise ValueError("IBKR error code must be an integer")
    if error_time is not None and not isinstance(error_time, int):
        raise ValueError("IBKR error time must be an integer epoch timestamp")

    return NormalizedIBKRError(
        error_time=error_time,
        error_code=error_code,
        error_string=str(error_string),
        advanced_order_reject_json=str(advanced_reject or ""),
    )
