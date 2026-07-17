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
It can compare a local Alpaca SIP one-minute sample directly with a local IBKR
five-minute snapshot through the `intraday_overlap` case. One-minute bars are
aggregated deterministically to 78/42 XNYS-anchored five-minute bars before
OHLCV comparison.

Standard published terms are provisionally insufficient until a vendor gives
written permission for this private program's automated research, model
training, local and approved cloud storage, derived artifacts, backups,
correction history, paper/live trading use, and post-cancellation retention.
Run `research-vendor-decision` only after the same RFI and sample suite has been
applied to Massive, Norgate, Databento, AlgoSeek, and Alpaca. Rights failure overrides
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
- Alpaca Market Data API: https://docs.alpaca.markets/us/docs/about-market-data-api
- Alpaca SIP historical boundary: https://docs.alpaca.markets/us/docs/market-data-faq

Alpaca is a no-cost historical SIP candidate, not a broker integration. Its
standalone downloader is documented in `docs/ALPACA_DATA_ACQUISITION.md`.
Acquired files remain non-promoting until written rights and the full technical
bake-off pass.

## Point-in-Time Macro Evidence

`research-evidence-register` is an offline metadata registry for primary-source
releases, news references, and operator briefs. It never downloads a source,
reads credentials, contacts IBKR, evaluates a strategy, accesses the sealed
holdout, or changes execution eligibility. Every record is permanently
`strategy_feature_eligible=false`, `promotion_eligible=false`, and
`execution_eligible=false`.

Each immutable revision records the observed period, publication time and its
precision, public first-availability time, local retrieval time, source URL,
official corroborating URLs, vintage, SHA-256, rights status, topics, and
affected instruments. An exact publication time must be timezone-aware. When a
source exposes only a date, use `first_observed` precision and set publication
time equal to the first time the operator actually observed it; never invent a
midnight release time. `research-evidence-audit --as-of` reports public and
local availability separately so a later retrieval cannot masquerade as data
available to an earlier decision.

The approved primary-source hierarchy is:

- EIA energy releases and API: https://www.eia.gov/opendata/documentation.php
- NOAA CPC weather and ENSO: https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.html
- USDA WASDE agriculture releases: https://www.usda.gov/about-usda/general-information/staff-offices/office-chief-economist/commodity-markets/wasde-report
- CFTC historical Commitments of Traders: https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm
- FRED/ALFRED observations and vintages: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- SEC EDGAR identity and filing APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces

Secondary news and user-supplied briefs are hypothesis context only. They must
reference at least one approved official source and cannot become a model
feature or alter the preregistered v2 SMA experiment. Metadata-only artifacts
are hash-verified but not copied. Permitted excerpts are capped and explicit.
Full documents are copied into a content-addressed external archive only when
the manifest declares retention rights.

```powershell
python -m trader.cli research-evidence-register `
  --manifest D:\MarketData\Quant-System\incoming\evidence\manifest.json `
  --root D:\MarketData\Quant-System

python -m trader.cli research-evidence-audit `
  --as-of 2026-07-13T16:00:00-04:00 `
  --root D:\MarketData\Quant-System
```

## Catalog V4

The SQLite catalog runs in WAL mode with full synchronous writes and foreign
keys. Schema v4 retains earlier ingestion, lineage, identity, and experiment
tables and adds immutable point-in-time evidence revisions:

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
- linear evidence revision chains, as-of indexes, content hashes, and optional
  rights-approved content-addressed archives.

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
  evidence/artifacts/<sha256>
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

- `minute_bars`: rights-approved Massive or Alpaca SIP raw minute aggregates;
- `daily_bars`: approved canonical daily OHLCV exports;
- `corporate_actions`: complete split/dividend event exports with declared
  coverage dates.

Alpaca, Massive, AlgoSeek, Databento, and Norgate imports require the selected
provider's authoritative vendor-decision report. The importer recomputes the
embedded decision and bake-off chain before any catalog write and requires
evidence for the imported data kind. Minute imports additionally require the
selected provider's own passing normal-session, early-close, pre/post-DST,
correction-before/after, and cross-vendor intraday-overlap evidence; another
provider's cases cannot satisfy those gates. Daily imports require that
provider's own `daily_overlap` sample and a passing cross-vendor daily-overlap
comparison involving it. Corporate-action imports require that provider's own
passing `ex_dividend` and `synthetic_split` cases.

Minute partitions must exactly match the XNYS calendar: 390 one-minute rows on a
normal session or 210 on a standard early close. Daily imports must contain every
XNYS session between their first and last observations. Corporate-action sets
must declare complete coverage for the period they support.

Target acquisition remains ten complete calendar years of SPY minute data for
2016-2025 and selected daily/action history from SPY inception through 2025.
Until a passing licensed daily/action export covers 1993-2003, that segment is a
hard provenance blocker rather than a gap to fill with a convenience feed.

## Derived Views

`research-data-derive` creates deterministic catalog-v4 revisions:

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

python scripts/acquire_alpaca_spy.py `
  --symbol SPY --feed sip --timeframe 1Min `
  --start 2016-01-01 --end 2025-12-31 `
  --output-root D:\MarketData\Quant-System\incoming\alpaca_sip `
  --plan-only

python -m trader.cli research-data-import-batch `
  --source-dir D:\MarketData\incoming\massive `
  --vendor massive `
  --kind minute_bars `
  --vendor-decision-report <passing-massive-decision-report.json> `
  --root D:\MarketData\Quant-System

# Alpaca import remains blocked until this report selects alpaca_sip and proves rights.
python -m trader.cli research-data-import-batch `
  --source-dir <one-complete-alpaca-run> `
  --vendor alpaca_sip `
  --kind minute_bars `
  --pattern 'alpaca-sip-SPY-*.json.gz' `
  --vendor-decision-report <passing-local-decision-report.json> `
  --root D:\MarketData\Quant-System

python -m trader.cli research-data-import-batch `
  --source-dir D:\MarketData\incoming\actions `
  --vendor norgate `
  --kind corporate_actions `
  --vendor-decision-report <passing-norgate-decision-report.json> `
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
