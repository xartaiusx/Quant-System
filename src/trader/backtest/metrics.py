"""Backtest metric placeholders."""

from __future__ import annotations


def empty_metrics() -> dict[str, str]:
    """Return an explicit placeholder metric set."""

    return {"status": "not_implemented"}
