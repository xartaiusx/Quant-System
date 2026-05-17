# Broker Setup

## Concepts

Interactive Brokers TWS and IB Gateway are local applications that act as the API host. A client connects to the host over a socket after the user has logged in.

This repo opens a socket only when explicitly asked to run a read-only probe:

```bash
python -m trader.cli broker-probe
```

The probe requests current server time and managed accounts. Account identifiers are masked in CLI output and reports.

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
- Paper execution remains blocked by the refusing paper executor.
- Live trading remains impossible.

## Common Connection Failures

- TWS or IB Gateway is not running.
- API socket clients are disabled.
- Configured port does not match the running application.
- Live ports `7496` or `4001` were configured; the repo rejects them.
- Another API client is already using the same client ID.
- Firewall or localhost binding blocks the socket.
- `ibapi` is missing; install with `python -m pip install -e ".[dev,broker]"`.
- Market data subscriptions are not required for the current-time probe.
- Read-only mode is acceptable and recommended for this milestone.

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
```

`account --connect` and `positions --connect` are read-only. If the broker is unavailable, they clearly fall back to mock data instead of pretending mock data came from TWS or Gateway.

## References

- IBKR initial setup and API settings: https://interactivebrokers.github.io/tws-api/initial_setup.html
- IBKR connection flow: https://interactivebrokers.github.io/tws-api/connection.html
- IBKR default Gateway/TWS port notes: https://interactivebrokers.github.io/tws-api/rtd_simple_syntax.html
