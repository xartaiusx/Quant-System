# Broker Setup

## Concepts

Interactive Brokers TWS and IB Gateway are local applications that act as the API host. A client connects to the host over a socket after the user has logged in.

This repo opens a socket only when explicitly asked to run a read-only probe:

```bash
python -m trader.cli broker-probe
python -m trader.cli market-probe --symbols SPY,AAPL --data-type delayed
python -m trader.cli history-snapshot --symbols SPY,AAPL --duration "1 D" --bar-size "5 mins"
python -m trader.cli paper-readiness-run
```

The probe requests current server time and managed accounts. Account identifiers are masked in CLI output and reports.
The market-data probe requests contract details, market-data type, quote ticks,
and optional small historical-bar samples. It does not route orders.
The historical snapshot command requests bounded historical bars and stores
local data files for future offline analysis. It does not route orders.
The paper readiness command runs the first broker-connected program test
sequentially, requires a real broker account summary, then uses offline loading
and analysis. It does not route orders.

## IBKR API Dependency

The default dev install keeps the repo usable without broker dependencies:

```bash
python -m pip install -e ".[dev]"
```

For real TWS / IB Gateway probing, install the optional broker extra when available:

```bash
python -m pip install -e ".[dev,broker]"
scripts/check-ibapi.sh
```

If `ibapi` is not available from your package index, install the official IBKR TWS API Python client manually, then rerun `scripts/check-ibapi.sh`. The check script never installs anything automatically.

## Default Ports

| Host | Paper | Live |
| --- | ---: | ---: |
| TWS | `7497` | `7496` disabled |
| IB Gateway | `4002` documented only | `4001` disabled |

The config rejects live ports `7496` and `4001`. Paper ports `7497` and `4002` are allowed for read-only probing.

## TWS Settings

For broker-backed reads, enable API socket clients in TWS:

```text
Global Configuration -> API -> Settings -> Enable ActiveX and Socket Clients
```

The socket port configured in TWS or IB Gateway must match the client port.

Keep Read-Only API enabled while developing this project. It blocks API orders at the TWS/Gateway setting level. This repo also keeps order routing disabled in code, so the read-only probe does not submit, modify, or cancel orders.

## Paper TWS Checklist

- Log into paper trading.
- Open `Global Configuration -> API -> Settings`.
- Enable `ActiveX and Socket Clients`.
- Confirm socket port `7497`.
- Keep `Read-Only API` enabled for this milestone.
- Confirm trusted IPs allow localhost if trusted IPs are configured.
- Use a unique `IBKR_CLIENT_ID` to avoid duplicate-client conflicts.

## Paper IB Gateway Checklist

- Log into paper trading.
- Use paper port `4002`.
- Keep live ports `7496` and `4001` blocked.
- Confirm localhost access from this machine.
- Use a unique `IBKR_CLIENT_ID`.
- Run broker-contact commands sequentially when collecting acceptance evidence.
  IB Gateway can accept separate clients, but overlapping managed-account,
  account-summary, or historical-data probes make timeout diagnosis ambiguous.
  Prefer a fresh base client ID and a short pause between broker stages.

## Current Repo Behavior

- Unit tests do not require TWS or IB Gateway.
- `python -m trader.cli preflight` does not connect unless `--connect` is passed.
- `python -m trader.cli broker-probe` connects, requests current time, requests managed accounts, masks account IDs, writes reports, and disconnects.
- The `ibapi` package is optional.
- If `ibapi` is unavailable, broker commands fail gracefully with setup guidance.
- Missing `ibapi` reports `failure_stage=dependency_check` and `connection_attempted=false`.
- Socket failures report `failure_stage=socket_connect`.
- Request timeouts report `failure_stage=timeout`.
- Successful probes report current server time and masked managed accounts when returned.
- `market-probe` defaults to delayed data and writes `market_probe` reports.
- `history-snapshot` writes ignored JSONL snapshots and manifests under `data/historical/`.
- `paper-readiness-run` runs broker probe, broker account summary, historical snapshot, offline load, commodity proxy universe, and analytical signal evaluation sequentially.
- `paper-readiness-run` uses distinct IBKR client IDs for broker-contact stages and pauses between those stages by default; override with `--broker-stage-pause` if needed.
- `paper-readiness-run` fails if broker account summary is unavailable or only mock fallback data is available.
- `paper-reconcile` is the read-only post-paper-run broker-state check. Run it after re-enabling Read-Only API and setting `ALLOW_PAPER_ORDERS=false`.
- `alpha-test-summary` is offline-only and aggregates ignored local run reports into a no-secret paper campaign summary.
- `paper-ledger-update` is offline-only and writes one masked campaign row to ignored local `state/paper_ledger.jsonl` after reconciliation and summary evidence pass.
- `alpha-shadow-daemon` repeats the read-only SPY shadow path for bounded cycles, writes ignored heartbeat evidence, honors a kill-switch file, and keeps order routing disabled.
- `alpha-shadow-daemon-summary` is offline-only and compares ignored daemon reports for same-commit, heartbeat, broker/account, stale-data, and safety evidence before any paper-daemon design.
- Paper execution remains blocked by the refusing paper executor.
- Live trading remains impossible.

## Common Connection Failures

- TWS or IB Gateway is not running.
- API socket clients are disabled.
- Configured port does not match the running application.
- Live ports `7496` or `4001` were configured; the repo rejects them.
- Another API client is already using the same client ID.
- Multiple broker-contact commands are running at the same time against one
  Gateway session; rerun sequentially with fresh client IDs before treating this
  as a broker outage.
- Firewall or localhost binding blocks the socket.
- `ibapi` is missing; install with `python -m pip install -e ".[dev,broker]"`.
- Market data subscriptions are not required for the current-time probe.
- Read-only mode is acceptable and recommended for this milestone.
- In Python `ibapi`, a falsy `connect()` return does not by itself prove failure; the probe waits for readiness callbacks and the current-time response.
- IBKR farm-status warnings such as `2104`, `2106`, `2107`, and `2158` are informational for this probe. They do not mean current-time connectivity failed.
- Live market data requires IBKR permissions/subscriptions. Delayed data is acceptable for early diagnostics and is the default.
- Historical data availability depends on IBKR data permissions, instrument availability, and pacing limits.
- Missing bid/ask values can occur outside market hours or when permissions are unavailable; the report records this as diagnostics rather than pretending mock data is broker data.
- IB Gateway paper uses port `4002`; live Gateway port `4001` remains rejected.

## Probe Commands

```bash
scripts/check-ibapi.sh
python -m trader.cli preflight
python -m trader.cli preflight --connect --timeout 10
python -m trader.cli broker-probe --timeout 10
scripts/run-broker-preflight.sh --timeout 10
scripts/run-broker-probe.sh --timeout 10
python -m trader.cli account --connect
python -m trader.cli positions --connect
python -m trader.cli market-probe --symbols SPY,AAPL --data-type delayed
python -m trader.cli market-probe --symbols SPY,AAPL --data-type delayed --historical
python -m trader.cli history-snapshot --symbols SPY,AAPL --duration "1 D" --bar-size "5 mins" --what-to-show TRADES --use-rth 1
python -m trader.cli paper-readiness-run
python -m trader.cli paper-readiness-run --broker-stage-pause 2
python -m trader.cli paper-reconcile --timeout 30
python -m trader.cli alpha-test-summary
python -m trader.cli paper-ledger-update
python -m trader.cli alpha-campaign-run --mode shadow --campaign-id campaign-YYYYMMDD-spy-001
python -m trader.cli alpha-campaign-run --mode paper --campaign-id campaign-YYYYMMDD-spy-001 --read-only-off-confirm READ_ONLY_OFF_FOR_ALPHA_PAPER
python -m trader.cli alpha-shadow-daemon --campaign-id campaign-YYYYMMDD-spy-shadow-daemon-001 --max-cycles 5 --interval-seconds 300
python -m trader.cli alpha-shadow-daemon-summary --report-glob='reports/alpha_shadow_daemon_*.json' --min-clean-sessions 5 --max-report-age-hours 168 --require-same-commit true
```

`account --connect` and `positions --connect` are read-only. If the broker is unavailable, they clearly fall back to mock data instead of pretending mock data came from TWS or Gateway.

## References

- IBKR TWS API setup and paper/live ports: https://www.interactivebrokers.com/campus/trading-lessons/installing-configuring-tws-for-the-api/
- IBKR contracts API reference: https://www.interactivebrokers.com/campus/ibkr-api-page/contracts/
