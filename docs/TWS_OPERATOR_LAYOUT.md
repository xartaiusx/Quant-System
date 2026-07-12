# TWS Operator Layout

## Scope

This layout is the supervised operator console for the SPY paper-autonomy
program. TWS is an observation and API-host surface; program reports and broker
callbacks remain authoritative. The layout does not enable execution or change
any application order-routing behavior.

Use exactly one paper API host per campaign:

| Use | Host | Port | Status |
| --- | --- | ---: | --- |
| Supervised paper testing | TWS | `7497` | Current operator default |
| Future unattended paper automation | IB Gateway | `4002` | Not approved yet |

Live ports `7496` and `4001` remain rejected. Do not run TWS and Gateway as
concurrent API hosts for one campaign.

## Version And Backup

The verified operator pairing is TWS `10.48.1d` with the currently installed
official IBKR TWS API. Re-run the API compatibility checker and all read-only
probes before accepting a TWS or API upgrade.

Before changing TWS configuration or layouts, export TWS settings to:

```text
Quant Creds/IBKR/TWS/settings/
```

The directory is sensitive, ignored by Git, and included in the encrypted
credential backup workflow. Never commit settings exports or raw TWS logs.

## API And Session Settings

Configure `Global Configuration -> API -> Settings` as follows:

- Enable ActiveX and Socket Clients: on.
- Read-Only API: on for normal operation and all shadow work.
- Socket port: `7497`.
- Allow connections from localhost only: on.
- Download open orders on connection: on.
- Master API client ID: blank.
- Maintain and resubmit orders when connection is restored: off.
- API message logging: on at `Error`.
- Market-data logging: off.
- Every API precaution bypass: off.

Automatic reconnect resubmission is incompatible with the program's
halt-and-reconcile recovery policy. During a bounded incident investigation,
API logging may be raised to `Detail`, but it must be returned to `Error`
afterward.

Configure the TWS session controls as follows:

- Warn on exit with position: on.
- Exit confirmation: on.
- Lock behavior: Never lock Trader Workstation.
- Supervised auto-logoff: enabled at the operator-selected time.
- Auto-restart: off. Configure restart separately on Gateway only after an
  unattended-paper milestone is approved.

## `SPY Shadow - DELAYED`

This is the normal supervised workspace until live entitlement is proven.
Its name is a safety label: observations from this tab never count toward
strict-live graduation.

The locked workspace contains:

- SPY Monitor: one `SPY STK/SMART/USD` row with primary exchange ARCA; Bid
  Size, Bid, Ask, Ask Size, Last, Change %, Close, and Volume.
- Advanced Chart: SPY five-minute candles, regular trading hours, New York
  time, volume, SMA(5), and SMA(20). Use it for visual verification only.
- Quote Details: bid, ask, sizes, last, close, volume, and delayed/live status
  when TWS exposes it.
- Portfolio: Symbol, Position, Market Value, Average Price, Daily P&L,
  Unrealized P&L, and Realized P&L.
- Activity: Orders, Trades, and Summary for broker lifecycle truth.

The monitor, chart, and quote panel share one color link. Portfolio and Activity
are unlinked. There is no Order Entry, scanner, market depth, BookTrader,
options, prediction-market, or generic-news panel.

After live SPY API entitlement is independently proven, duplicate the workspace
as `SPY Shadow - LIVE`. Do not rename delayed evidence as live or allow delayed
sessions to satisfy strict-live gates.

## `Commodity Research`

This locked workspace is research-only. It contains:

- Watchlist: GLD, USO, and DBA, with SPY as the benchmark.
- Linked Quote Details.
- Linked five-minute chart.
- Linked company-specific news.

It contains no Order Entry, Activity, futures contracts, options, or execution
controls. DBA remains excluded from execution. Direct futures remain blocked
until contract identity, expiry, rollover, multiplier, tick value, margin,
permissions, liquidity, and delivery risk are modeled.

## Startup Checklist

1. Confirm the red simulated-trading banner and paper account.
2. Confirm TWS is the only API host for the campaign and listens on `7497`.
3. Confirm socket clients, Read-Only API, and localhost-only access are enabled.
4. Confirm reconnect resubmission and every precaution bypass are disabled.
5. Set `TRADING_MODE=paper`, `ALLOW_PAPER_ORDERS=false`, and
   `ALLOW_LIVE_ORDERS=false`.
6. Use fresh client IDs and run broker-contact commands sequentially.
7. Open `SPY Shadow - DELAYED` and verify Portfolio and Activity show no
   unexplained broker state.
8. Run the read-only acceptance sequence from the runbook.

## Read-Only Acceptance Sequence

Use fresh client IDs and run these commands sequentially. The values below are
examples; replace any ID already in use.

```powershell
$env:TRADING_MODE='paper'
$env:ALLOW_PAPER_ORDERS='false'
$env:ALLOW_LIVE_ORDERS='false'
$env:IBKR_HOST='127.0.0.1'
$env:IBKR_PORT='7497'
$env:BROKER_KIND='tws'

.\scripts\check-ibapi.ps1

$env:IBKR_CLIENT_ID='731'
.venv\Scripts\python.exe -m trader.cli broker-probe --timeout 30

$env:IBKR_CLIENT_ID='732'
.venv\Scripts\python.exe -m trader.cli market-probe --symbols SPY --data-type delayed --historical --timeout 30

$env:IBKR_CLIENT_ID='733'
.venv\Scripts\python.exe -m trader.cli history-snapshot --symbols SPY --duration "1 D" --bar-size "5 mins" --what-to-show TRADES --use-rth 1 --timeout 45

$env:IBKR_CLIENT_ID='734'
.venv\Scripts\python.exe -m trader.cli paper-reconcile --timeout 30
```

Acceptance requires a compatible official IBKR API, a connected paper socket,
masked real-account evidence, clean disconnects, zero unexplained open orders,
`submitted_orders=false`, `paper_orders_enabled=false`, and
`order_api_invoked=false`. Outside regular hours, missing quote ticks or stale
history are data-availability results; they must not be relabeled as live or
used as graduation evidence.

## Shutdown Checklist

1. Confirm `ALLOW_PAPER_ORDERS=false`.
2. Confirm Read-Only API is enabled.
3. Run `paper-reconcile` and prove zero residual open-order uncertainty.
4. Preserve only masked reports in ignored local storage.
5. Leave both custom layouts locked.

Any deliberate paper-order smoke window is a separate supervised procedure.
It ends with Read-Only restored, paper orders disabled, reconciliation complete,
and zero residual orders. Paper fills are lifecycle evidence, not evidence of
live execution quality.

## References

- [IBKR TWS API installation and configuration](https://www.interactivebrokers.com/campus/trading-lessons/installing-configuring-tws-for-the-api/)
- [IBKR API settings reference](https://www.ibkrguides.com/traderworkstation/api.htm)
- [IBKR third-party connection and order recovery settings](https://www.interactivebrokers.com/campus/ibkr-api-page/third-party-connections/)
- [IBKR Mosaic workspace guide](https://www.interactivebrokers.com/campus/trading-lessons/getting-started-with-tws/)
- [IBKR API market-data requirements](https://www.interactivebrokers.com/campus/ibkr-api-page/market-data-subscriptions/)
- [IBKR paper-account limitations](https://www.interactivebrokers.com/campus/glossary-terms/paper-trading-account/)
- [FINRA Notice 15-09](https://www.finra.org/rules-guidance/notices/15-09)
- [SEC Rule 15c3-5 FAQ](https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/divisionsmarketregfaq-0)
- [CFTC commodity ETP advisory](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/CustomerAdvisory_CommodityETPs.htm)
