# Runbook

## First-Time Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

For real read-only broker probes:

```bash
python -m pip install -e ".[dev,broker]"
scripts/check-ibapi.sh
```

If `ibapi` is unavailable from your package index, install the official IBKR TWS API Python client manually and rerun `scripts/check-ibapi.sh`.

Optional local config:

```bash
cp .env.example .env
```

Keep `.env` local.

## Test Commands

```bash
pytest
ruff check .
mypy src
```

## Broker Dependency Check

```bash
source .venv/bin/activate
scripts/check-ibapi.sh
```

Expected missing-dependency result:

```text
ibapi package: missing
Next step: activate the repo venv and install the optional broker extra:
  python -m pip install -e ".[dev,broker]"
No packages were installed by this script.
```

Expected success result:

```text
ibapi import: ok
ibapi readiness: ok
```

## Preflight

```bash
python -m trader.cli preflight
```

Expected behavior:

- reports config
- reports whether `ibapi` is installed
- does not open a broker socket
- does not place orders
- reports `connection_attempted=false`

To include a harmless current-time connection probe:

```bash
python -m trader.cli preflight --connect --timeout 10
```

## Broker Probe

```bash
python -m trader.cli broker-probe --timeout 10
scripts/run-broker-probe.sh --timeout 10
```

Expected success output:

```text
Read-only broker probe
Order routing: disabled.
No order APIs invoked.
Final status: connected
Server time: <broker timestamp>
Managed accounts: DUXX****99
```

Expected `ibapi` missing output:

```text
Read-only broker probe
Order routing: disabled.
No order APIs invoked.
Failure stage: dependency_check
connection_attempted: false
```

Expected failure output:

```text
Read-only broker probe
Order routing: disabled.
No order APIs invoked.
Final status: failed
Errors
- socket unavailable; confirm TWS/Gateway is running...
```

Expected paper TWS success prerequisites:

- Paper TWS is open and logged in.
- `Global Configuration -> API -> Settings -> Enable ActiveX and Socket Clients` is enabled.
- Socket port is `7497`.
- `Read-Only API` remains enabled.
- `IBKR_CLIENT_ID` is not already in use.

Combined readiness command:

```bash
scripts/run-broker-preflight.sh --timeout 10
```

Reports are written to:

```text
reports/broker_probe_<timestamp>.json
reports/broker_probe_<timestamp>.md
reports/latest_broker_probe.json
reports/latest_broker_probe.md
```

## Dry-Run Plan

```bash
python -m trader.cli plan --strategy momentum --dry-run
```

Expected behavior:

- uses deterministic mock quotes
- emits strategy signals
- builds trade plans
- runs risk checks
- writes JSON and Markdown reports
- places no orders

## Market Probe

```bash
python -m trader.cli probe --symbols SPY,QQQ,AAPL
```

Expected behavior:

- prints deterministic mock quote data
- opens no broker socket

## Troubleshooting

If config is rejected, inspect environment variables first:

- `TRADING_MODE` must be `paper`, `dry_run`, or `backtest`.
- `ALLOW_LIVE_ORDERS` must be `false`.
- `IBKR_PORT` must not be `7496` or `4001`.
- Paper TWS normally uses `IBKR_PORT=7497`.
- Paper IB Gateway normally uses `IBKR_PORT=4002`.
- Risk limits must be positive.
- `UNIVERSE` must contain at least one valid symbol.

If `python -m trader.cli ...` cannot import `trader`, install the project:

```bash
python -m pip install -e .
```

If `broker-probe` fails:

- Install the optional broker dependency: `python -m pip install -e ".[dev,broker]"`.
- Run `scripts/check-ibapi.sh`.
- Confirm TWS or IB Gateway is running and logged in.
- In TWS, open `Global Configuration -> API -> Settings`.
- Enable `ActiveX and Socket Clients`.
- Keep `Read-Only API` enabled.
- Match the configured socket port to `IBKR_PORT`.
- Try a unique `IBKR_CLIENT_ID` if another API client is connected.
- Keep the host on `127.0.0.1` or `localhost`.
- Remember that market data subscriptions are not required for current-time probing.

## Safe Next Milestones

1. Add historical-data snapshot ingestion with stale-data and subscription diagnostics.
2. Add read-only market-data subscription diagnostics behind explicit flags.
3. Add a paper execution design document before enabling any paper submission.
