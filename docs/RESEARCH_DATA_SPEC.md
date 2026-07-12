# SPY Research Data Specification

## Purpose

The external research store is the canonical broker-free source for SPY
historical research. It separates immutable vendor observations, normalized
canonical data, corporate actions, derived research views, and experiment
evidence. No research-data command downloads data, reads credentials, contacts
IBKR, evaluates a strategy, or routes an order.

Generated data, catalogs, reports, credentials, and `Quant Creds` remain outside
Git. The default store root is `D:/MarketData/Quant-System`.

## Procurement Bake-off

Run `research-data-bakeoff` before purchasing or adopting a source. Its manifest
points only to manually supplied local CSV or CSV.gz samples and declares:

- normal-session and official early-close samples;
- ex-dividend observations and synthetic split fixtures;
- before/after correction samples;
- overlapping daily observations across candidate vendors;
- expected checksums and row counts when available;
- written rights for internal storage, model training, derived data, correction
  replay, and retention after subscription termination.

The bake-off validates timestamps, XNYS session alignment, OHLCV, duplicates,
checksums, corrections, overlap tolerances, and rights evidence. It reports
procurement readiness but never downloads data or promotes a strategy.

Standard published terms are provisionally insufficient until a vendor gives
written permission for this private program's automated research, model
training, local and approved cloud storage, derived artifacts, backups,
correction history, paper/live trading use, and post-cancellation retention.
Run `research-vendor-decision` only after the same RFI and sample suite has been
applied to Massive, Norgate, Databento, and AlgoSeek. Rights failure overrides
the 20/20/10/10/10/10/10/10 technical score and the $700 monthly ceiling.
Contracts and responses stay in `Quant Creds`; the decision manifest contains
only SHA-256 evidence references and non-sensitive terms metadata. See
`docs/VENDOR_RFI.md`.

Massive documents its stock flat files as unadjusted SIP data. Prices and volume
are not adjusted for splits, dividends, or other corporate actions, so raw
Massive observations must never be treated as a signal-ready adjusted series.
Norgate is only an approved candidate for daily/corporate-action coverage after
its export and license pass the same bake-off. Its U.S. Platinum history is
advertised back to 1990, which can potentially cover SPY's 1993 inception, but
the actual trial/export and rights must be verified before purchase.

Primary vendor sources:

- Massive stock flat files: https://massive.com/docs/flat-files/stocks/overview
- Norgate U.S. stock packages: https://norgatedata.com/stockmarketpackages.php

## Catalog V3

The SQLite catalog runs in WAL mode with full synchronous writes and foreign
keys. Schema v3 retains earlier ingestion and lineage tables and adds:

- immutable source artifacts and ingestion runs;
- raw and canonical partitions with active revisions;
- complete corporate-action sets and event revisions;
- derived partitions and parent lineage;
- algorithm, input, action, dataset, and checksum fingerprints;
- preregistered experiment specs/runs;
- append-only final-holdout access records.
- permanent sealed-period records that generic loaders cannot bypass;
- experiment supersession state;
- immutable versioned SPY identity records keyed by `spy-us-equity`.

Corrections never overwrite raw or derived data. A changed source creates a new
parent revision, deactivates the prior parent, invalidates dependent derived
partitions, and requires deterministic re-derivation. Loaders reject inactive
parents, stale lineage, checksum drift, incomplete actions, and multiple active
revisions.

## Store Layout

```text
D:/MarketData/Quant-System/
  raw/<vendor>/<dataset>/
  curated/<vendor>/<dataset>/
  derived/<price-view>/<bar-size>/
  catalog/research.sqlite3
  quarantine/
```

Source artifacts are copied byte-for-byte. If a vendor reuses a filename with
different content, the archive uses a hash-suffixed name. Existing artifacts and
partitions are never rewritten.

## Instrument Identity

Before importing licensed observations, run `research-instrument-register`
against the tracked SPY manifest. It pins the internal ID, symbol, security
type, currency, SMART/ARCA routing identity, minimum tick, listing dates, IBKR
`conId`, FIGI when available, vendor mappings, and primary-source references.
A registered version is immutable; a correction requires a higher version and
deactivates the previous record without deleting it.

## Import Contract

`research-data-import-batch` sorts a non-recursive local filename glob before
import and accepts only these SPY source kinds:

- `minute_bars`: licensed Massive-style unadjusted minute aggregates;
- `daily_bars`: approved canonical daily OHLCV exports;
- `corporate_actions`: complete split/dividend event exports with declared
  coverage dates.

Minute partitions must exactly match the XNYS calendar: 390 one-minute rows on a
normal session or 210 on a standard early close. Daily imports must contain every
XNYS session between their first and last observations. Corporate-action sets
must declare complete coverage for the period they support.

Target acquisition remains ten complete calendar years of SPY minute data for
2016-2025 and selected daily/action history from SPY inception through 2025.
Until a passing licensed daily/action export covers 1993-2003, that segment is a
hard provenance blocker rather than a gap to fill with a convenience feed.

## Derived Views

`research-data-derive` creates deterministic catalog-v3 revisions:

1. `raw_execution`, `5 mins`: XNYS-anchored OHLCV aggregated from immutable raw
   one-minute observations for simulated execution.
2. `split_adjusted_signal`, `5 mins`: the same parent observations adjusted for
   splits for indicator calculations.
3. `total_return_benchmark`, `1 day`: a split-and-cash-dividend-adjusted daily
   benchmark index.

Raw prices remain the simulated execution truth. Splits and cash dividends are
also applied explicitly to portfolio accounting. Five-minute derivation fails
on incomplete groups and must produce exactly 78 rows for a normal session or 42
for a standard early close.

`research-catalog-load` accepts only passing active revisions, rechecks every
derived and parent checksum, verifies expected XNYS coverage, and returns dataset
and action fingerprints. Backtest and experiment commands use this loader only;
they do not consume ad hoc IBKR snapshots.

## Operator Workflow

Install the hash-locked environment, then register identity and evaluate vendor
rights before import:

```powershell
python -m pip install --only-binary=:all: --require-hashes -r requirements.lock
python -m pip install --no-deps -e .
python -m trader.cli research-instrument-register `
  --manifest research/instruments/spy_v1.json `
  --catalog-root D:\MarketData\Quant-System
```

Run the offline bake-off, import, derivation, and load checks:

```powershell
python -m trader.cli research-data-bakeoff `
  --manifest D:\MarketData\bakeoff\spy-vendors.json

python -m trader.cli research-vendor-decision `
  --manifest D:\MarketData\bakeoff\spy-vendor-decision.json

python -m trader.cli research-data-import-batch `
  --source-dir D:\MarketData\incoming\massive `
  --vendor massive `
  --kind minute_bars `
  --root D:\MarketData\Quant-System

python -m trader.cli research-data-import-batch `
  --source-dir D:\MarketData\incoming\actions `
  --vendor norgate `
  --kind corporate_actions `
  --coverage-start 1993-01-22 `
  --coverage-end 2025-12-31 `
  --root D:\MarketData\Quant-System

python -m trader.cli research-data-derive --root D:\MarketData\Quant-System
python -m trader.cli research-catalog-load `
  --root D:\MarketData\Quant-System `
  --price-view split_adjusted_signal `
  --bar-size "5 mins"
python -m trader.cli research-data-audit --root D:\MarketData\Quant-System
```

Stop on any failed report. A successful bake-off is necessary procurement
evidence, not permission to redistribute vendor data and not a strategy result.
