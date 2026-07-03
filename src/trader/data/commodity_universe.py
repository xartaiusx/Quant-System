"""Broker-free commodity-linked research proxy universe."""

from __future__ import annotations

from trader.models import (
    CommodityProxyCategory,
    CommodityProxyInstrument,
    CommodityResearchUniverseReport,
    CommodityResearchUniverseRequest,
)


def default_commodity_proxy_universe() -> list[CommodityProxyInstrument]:
    """Return commodity-linked security proxies for offline research."""

    return [
        CommodityProxyInstrument(
            symbol="GLD",
            name="SPDR Gold Shares",
            category=CommodityProxyCategory.METALS,
            underlying_exposure="gold-linked exchange-traded product",
            notes="Security proxy only; not a direct futures contract.",
        ),
        CommodityProxyInstrument(
            symbol="SLV",
            name="iShares Silver Trust",
            category=CommodityProxyCategory.METALS,
            underlying_exposure="silver-linked exchange-traded product",
            notes="Security proxy only; not a direct futures contract.",
        ),
        CommodityProxyInstrument(
            symbol="USO",
            name="United States Oil Fund",
            category=CommodityProxyCategory.ENERGY,
            underlying_exposure="crude-oil-linked exchange-traded product",
            notes="Security proxy only; futures roll behavior is not modeled here.",
        ),
        CommodityProxyInstrument(
            symbol="DBA",
            name="Invesco DB Agriculture Fund",
            category=CommodityProxyCategory.AGRICULTURE,
            underlying_exposure="agriculture-linked exchange-traded product",
            notes="Security proxy only; basket composition is not modeled here.",
        ),
        CommodityProxyInstrument(
            symbol="DBC",
            name="Invesco DB Commodity Index Tracking Fund",
            category=CommodityProxyCategory.BROAD_BASKET,
            underlying_exposure="broad commodity basket exchange-traded product",
            notes="Security proxy only; basket composition and roll yield are not modeled here.",
        ),
    ]


def build_commodity_proxy_universe(
    request: CommodityResearchUniverseRequest,
) -> tuple[list[CommodityProxyInstrument], list[str]]:
    """Return filtered commodity-linked proxies and warnings."""

    instruments = default_commodity_proxy_universe()
    if not request.symbols:
        return instruments, []

    by_symbol = {instrument.symbol: instrument for instrument in instruments}
    selected: list[CommodityProxyInstrument] = []
    warnings: list[str] = []
    for symbol in request.symbols:
        instrument = by_symbol.get(symbol)
        if instrument is None:
            warnings.append(f"{symbol} is not in the configured commodity proxy universe")
            continue
        selected.append(instrument)
    return selected, warnings


def build_commodity_research_universe_report(
    request: CommodityResearchUniverseRequest,
) -> CommodityResearchUniverseReport:
    """Build an offline report for commodity-linked security proxies."""

    instruments, warnings = build_commodity_proxy_universe(request)
    categories: dict[str, list[str]] = {}
    for instrument in instruments:
        category = str(getattr(instrument.category, "value", instrument.category))
        categories.setdefault(category, []).append(instrument.symbol)
    errors: list[str] = []
    if request.symbols and not instruments:
        errors.append("no requested symbols matched the commodity proxy universe")
    return CommodityResearchUniverseReport(
        ok=not errors,
        request=request,
        symbols_requested=request.symbols,
        instruments=instruments,
        categories={category: sorted(symbols) for category, symbols in sorted(categories.items())},
        warnings=list(dict.fromkeys(warnings)),
        errors=errors,
        final_status="ready" if not errors else "failed",
    )
