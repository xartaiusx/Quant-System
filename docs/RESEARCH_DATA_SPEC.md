# SPY Research Data Store Specification

## Purpose

The research store is the canonical, broker-free source for SPY historical
research. It preserves licensed source files, records lineage and revisions,
and activates only complete XNYS regular-session partitions. It does not
download data, read credentials, contact IBKR, evaluate a strategy, calculate
P&L, or make a dataset promotion-eligible.

## Approved Initial Source

- Vendor: Massive U.S. Stocks SIP flat files.
- Dataset: `us_stocks_sip/minute_aggs_v1`.
- Symbol: `SPY` only.
- Source view: unadjusted/raw.
- Session: XNYS regular hours only, including official early closes.
- Storage root: `D:/MarketData/Quant-System` by default.

Massive documents compressed CSV flat files with the columns `ticker`,
`volume`, `open`, `close`, `high`, `low`, `window_start`, and `transactions`.
`window_start` is a Unix timestamp in UTC nanoseconds. Final daily files are
normally available around 11:00 AM ET on the following day.

The current Massive Developer plan documents ten years of aggregate history.
The flat-file archive documents stock aggregate records beginning in September
2003. It therefore does **not** independently satisfy the desired daily SPY
history back to the fund's January 22, 1993 inception. The 1993-2003 daily
segment remains an explicit provenance blocker until a licensed source is
selected and reconciled. Do not fill it from an unreviewed convenience feed.

Primary sources:

- Massive flat-file quickstart: https://massive.com/docs/flat-files
- Massive stocks flat-file overview: https://massive.com/docs/flat-files/stocks/overview
- State Street SPY fund page: https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy
- NYSE Daily TAQ catalog: https://www.nyse.com/data-products/catalog/daily-taq

## Layout And Immutability

```text
D:/MarketData/Quant-System/
  raw/massive/us_stocks_sip/minute_aggs_v1/
  curated/massive/us_stocks_sip/minute_aggs_v1/
  catalog/research.sqlite3
  quarantine/
```

Raw files are copied byte-for-byte and named by their vendor filename. A
different checksum for the same filename creates a hash-suffixed artifact; an
existing artifact is never overwritten. Curated Parquet files are partitioned
by price view, symbol, year, month, session, and revision. A correction creates
a new immutable revision and makes the previous revision inactive without
deleting it.

The SQLite catalog uses WAL mode, full synchronous writes, foreign keys, a
versioned schema, source SHA-256 values, Parquet SHA-256 values, row counts,
session coverage, active revision state, ingestion runs, and quality findings.

## Fail-Closed Quality Contract

An input may become active only when all selected SPY rows:

- have the documented Massive columns and parse cleanly;
- are aligned to UTC minute boundaries and ordered chronologically;
- have unique timestamps, positive finite prices, internally valid OHLC, and
  non-negative integral volume and transaction counts;
- exactly match every expected XNYS regular-session minute for the date;
- match the trading date embedded in the vendor filename when present.

Failed files remain in the immutable raw archive with a failed catalog run, but
no Parquet partition is activated. Zero-volume rows are warnings and remain
visible in evidence. Store audits verify paths remain under the configured
root, active checksums, Parquet row counts, one active revision per session,
and complete XNYS session coverage between the first and last active dates.

## Operator Workflow

Install research-only dependencies separately from the broker runtime:

```powershell
python -m pip install -e ".[dev,research]"
```

Download licensed files explicitly with the vendor-supported S3 client. Keep
access keys outside the repository. Then ingest and audit locally:

```powershell
python -m trader.cli research-data-ingest `
  --source-file D:\MarketData\incoming\2026-07-10.csv.gz `
  --root D:\MarketData\Quant-System

python -m trader.cli research-data-audit `
  --root D:\MarketData\Quant-System
```

Generated JSON and Markdown reports stay under ignored `reports/`. Raw files,
Parquet files, the SQLite catalog, credentials, and licensed vendor data must
never be committed.

## Deferred Views

This milestone activates only raw one-minute partitions. Split-adjusted signal
views, dividend-adjusted daily benchmark views, REST repair, corporate-action
lineage, five-minute derivation, and direct research-engine loading remain
separate reviewed milestones. Every derived view must retain its source hashes
and adjustment algorithm version; raw observations must never be rewritten.
