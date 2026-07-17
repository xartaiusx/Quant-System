# Alpaca Historical SPY Data Acquisition

## Boundary

Alpaca is a candidate historical-data source only. Interactive Brokers remains
the sole broker. The acquisition path cannot place, replace, or cancel orders,
read an IBKR account, activate catalog data, derive research views, or run a
backtest.

Alpaca documents that an unsubscribed historical SIP query must set `end` at
least 15 minutes in the past. The program is stricter: the entire requested
closed-open date range and every returned bar must be older than that boundary.
It pins `https://data.alpaca.markets/v2/stocks/SPY/bars`, `feed=sip`,
`timeframe=1Min`, `adjustment=raw`, and `sort=asc`.

Primary references:

- https://docs.alpaca.markets/us/docs/about-market-data-api
- https://docs.alpaca.markets/us/docs/market-data-faq

Access does not establish permission. Every acquisition manifest is marked
`research_eligible=false` and `rights_status=written_rights_unverified` until a
passing offline bake-off and vendor-decision report prove the required written
rights.

## Credentials

Keep Alpaca material under ignored `Quant Creds/Alpaca`. Load only these names
into the process environment:

```powershell
$env:APCA_API_KEY_ID='<loaded from Quant Creds>'
$env:APCA_API_SECRET_KEY='<loaded from Quant Creds>'
```

Never put credentials in command arguments, manifests, logs, reports, shell
history, or Git. The acquisition script does not load files from `Quant Creds`;
the operator controls how the environment is populated.

On Windows, create the user-and-machine-bound DPAPI file interactively:

```powershell
pwsh scripts/set-alpaca-spy-credentials.ps1
```

Both the key ID and secret are stored as `SecureString` fields under ignored
`Quant Creds/Alpaca/credentials.clixml`. The EOD runner unwraps them only long
enough to populate the acquisition child process environment and removes them
from planner and comparator child environments. Task arguments, XML, reports,
and logs contain no credential values.

Microsoft references:

- https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/export-clixml
- https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-logontype

## Plan Before Download

The plan-only command reads no credentials and makes no network request:

```powershell
python scripts/acquire_alpaca_spy.py `
  --symbol SPY --feed sip --timeframe 1Min `
  --start 2016-01-01 --end 2025-12-31 `
  --output-root D:\MarketData\Quant-System\incoming\alpaca_sip `
  --plan-only
```

The expected result is 120 monthly closed-open partitions. The output root must
be outside the Git worktree.

Plan one completed XNYS session without reading credentials or using the
network:

```powershell
python scripts/acquire_alpaca_spy.py `
  --session-date 2026-07-16 `
  --output-root D:\MarketData\Quant-System\incoming\alpaca_sip `
  --plan-only
```

`--session-date` is mutually exclusive with the unchanged `--start/--end`
monthly interface. It resolves the official XNYS open, close, final minute
start, expected count, timestamp-grid hash, close-plus-20 eligibility time, and
request fingerprint.

## Acquire

After credentials are loaded:

```powershell
python scripts/acquire_alpaca_spy.py `
  --symbol SPY --feed sip --timeframe 1Min `
  --start 2016-01-01 --end 2025-12-31 `
  --output-root D:\MarketData\Quant-System\incoming\alpaca_sip
```

The downloader uses pagination, a conservative request rate, bounded retry and
backoff, interruption checkpoints, raw-page SHA-256 checks, deterministic gzip
monthly payloads, and immutable final manifests. A repeated acquisition creates
a separate run, allowing T+1 correction comparisons. Raw pages and acquisition
manifests are never committed.

The HTTP client rejects every redirect. Alpaca credential headers are sent only
to the pinned HTTPS `data.alpaca.markets` request and are never forwarded to a
redirect target.

Download success is not import permission. It does not trigger catalog import,
derivation, backtesting, experiment access, or paper execution.

## Complete Session Capture

After a passing rights decision, one EOD capture requests exactly the XNYS
regular-session minute labels from the official open through the last minute
start. Execution is rejected until at least 20 minutes after the official
close. A normal session must contain exactly 390 timestamps; a standard early
close must contain the calendar-derived 210 timestamps.

```powershell
python scripts/acquire_alpaca_spy.py `
  --session-date 2026-07-16 `
  --output-root D:\MarketData\Quant-System\incoming\alpaca_sip
```

Every HTTP response attempt, including rate-limit/error and malformed/drifted
bodies, is stored immutably with a checksum, allowlisted request ID, retrieval
time, HTTP status, and outcome. Interruption checkpoints retain those attempts;
an incomplete terminal run is marked failed so a later invocation starts a new
immutable run. A passing `acquisition_manifest.json` is published last and only
after:

- every raw-page checksum revalidates;
- response symbol and any returned feed/adjustment/timeframe metadata match;
- required OHLCV, trade-count, and VWAP values are valid;
- timestamps are chronological, unique, and exactly equal the XNYS grid;
- the deterministic compressed data file revalidates against its checksum.

Each completed recapture creates a distinct immutable run. Manifests record
session boundaries, expected and received counts, request fingerprint,
allowlisted source response IDs, raw-page/data hashes, and false broker, order,
catalog, research, promotion, and graduation flags.

Compare two completed revisions offline:

```powershell
python -m trader.alpaca_session_compare_cli `
  --baseline-manifest <earlier-acquisition-manifest.json> `
  --candidate-manifest <later-acquisition-manifest.json>
```

The command is a dedicated broker-free process and imports neither IBKR/order
modules nor the network-capable acquisition module. It revalidates both
manifests, response attempts, contained paths, raw-to-data lineage, metadata,
XNYS grids, and checksums before classifying OHLCV, trade-count, and VWAP
differences. Passing same-session manifests necessarily have complete identical
timestamp grids; a purported incomplete manifest fails closed before comparison
instead of becoming valid correction evidence.

## Rights-Gated EOD Task

Preview the runner and Task Scheduler definition without reading rights,
credentials, using the network, writing files, or changing scheduler state:

```powershell
pwsh scripts/run-alpaca-spy-eod.ps1 `
  -OutputRoot D:\MarketData\Quant-System\incoming\alpaca_sip `
  -CaptureStartDate 2026-07-16 -PlanOnly

pwsh scripts/manage-alpaca-spy-eod-task.ps1 `
  -Mode Plan `
  -OutputRoot D:\MarketData\Quant-System\incoming\alpaca_sip `
  -CaptureStartDate 2026-07-16
```

Installation and every real run require a clean committed release plus an
authoritatively parsed `ResearchVendorDecisionReport` whose selected
`alpaca_sip` candidate passes written-rights, bake-off, and budget gates. Each
orchestration report records the decision SHA-256, commit, configuration
fingerprint, and comparison-report hashes.
The task runs at 13:30 Pacific Monday-Friday in the logged-on current-user
context. Its runner uses XNYS—not weekdays—to skip holidays, identify the latest
completed session, backfill every missing date since `CaptureStartDate`, and
recapture the prior two sessions once for T+1/T+2 correction detection.
An unmatched newest revision pair remains pending across retries until a valid
offline comparison report exists; capture success alone cannot advance health.

The installed settings are `StartWhenAvailable=true`, network required, three
retries at 15-minute intervals, `IgnoreNew`, two-hour execution limit, and
`WakeToRun=false`. The local no-offset start boundary follows Pacific DST.
Missed work catches up when the logged-on machine is next available. Successful
runs write immutable external orchestration reports plus a convenience-only
health pointer; failures preserve diagnostics and never advance success state.

Microsoft references:

- https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-startwhenavailable
- https://learn.microsoft.com/en-us/windows/win32/api/taskschd/nf-taskschd-itrigger-put_startboundary

Install or remove only after rights approval:

```powershell
pwsh scripts/manage-alpaca-spy-eod-task.ps1 `
  -Mode Install `
  -OutputRoot D:\MarketData\Quant-System\incoming\alpaca_sip `
  -CaptureStartDate 2026-07-16 `
  -RightsDecisionReport <passing-alpaca-vendor-decision.json>

pwsh scripts/manage-alpaca-spy-eod-task.ps1 -Mode Uninstall
```

Uninstall removes only a repository-owned task and leaves credentials, raw
data, correction history, reports, and exported task XML intact.

## Rights Gate And Import

Send the RFI in `docs/VENDOR_RFI.md` and store the response or contract only in
`Quant Creds`. Run the offline bake-off and vendor decision with hashes of that
written evidence. An Alpaca decision must prove all storage, training, derived
data, backup, correction, paper/live-use, and post-termination retention rights.

Only a passing decision report selected for `alpaca_sip` unlocks batch import:

```powershell
python -m trader.cli research-data-import-batch `
  --source-dir <one-complete-acquisition-run> `
  --vendor alpaca_sip --kind minute_bars `
  --pattern 'alpaca-sip-SPY-*.json.gz' `
  --vendor-decision-report <passing-local-decision-report.json> `
  --root D:\MarketData\Quant-System
```

The importer maps Alpaca `t/o/h/l/c/v/n/vw` into UTC event time, OHLC, volume,
trade count, and VWAP. It requires exact XNYS regular-session coverage and
preserves Alpaca as the source identity in catalog lineage.

## Bake-off And Forward Capture

Before adopting the source, compare:

- a normal session and an official 210-minute early close;
- a volatile session and an ex-dividend date;
- deterministic one-minute to five-minute aggregation;
- Alpaca SIP against the corresponding captured IBKR session;
- the same Alpaca partition acquired on different days for revisions;
- distributions and instrument identity against State Street and SEC records.

IBKR notes that its historical feed is filtered and can change as data is
adjusted, so differences must be classified rather than assumed to be vendor
errors. Cboe market-wide volume is useful only as a broad sanity check, not as
SPY OHLC truth.

Self-captured delayed IBKR sessions remain engineering evidence only. They never
count toward strict-live graduation or strategy promotion.

For a direct technical comparison, tag an Alpaca one-minute sample and an IBKR
five-minute JSONL snapshot with `intraday_overlap`. The offline bake-off
deterministically aggregates the one-minute sample to XNYS-anchored five-minute
bars, normalizes IBKR timezone-qualified timestamps, and compares aligned OHLCV.
Use `source_format=alpaca_sip_json` with `kind=minute_bars` and
`source_format=ibkr_snapshot_jsonl` with `kind=five_minute_bars`. Unexplained
price, volume, boundary, or completeness differences fail the technical gate.
