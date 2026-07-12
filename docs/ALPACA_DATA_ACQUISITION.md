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

Download success is not import permission. It does not trigger catalog import,
derivation, backtesting, experiment access, or paper execution.

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
