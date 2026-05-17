"""Fail-closed runtime guards."""

from __future__ import annotations

from trader.config import LIVE_PORTS, TraderConfig


def config_has_live_order_risk(config: TraderConfig) -> bool:
    """Return whether config contains a live-order hazard."""

    return bool(config.allow_live_orders or config.ibkr_port in LIVE_PORTS)


def explain_execution_disabled(config: TraderConfig) -> list[str]:
    """Return explicit safety blockers from config."""

    blockers: list[str] = []
    if config.allow_live_orders:
        blockers.append("ALLOW_LIVE_ORDERS=true is rejected")
    if config.ibkr_port in LIVE_PORTS:
        blockers.append("configured IBKR port is a disabled live port")
    if not config.allow_paper_orders:
        blockers.append("ALLOW_PAPER_ORDERS=false blocks broker execution")
    return blockers
