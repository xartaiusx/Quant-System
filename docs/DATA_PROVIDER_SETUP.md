# SPY Data Provider Setup Gate

## Purpose

This is the durable setup boundary for the provisional Alpaca, Massive,
AlgoSeek, Databento, and Norgate data sources. It separates authenticated
dashboard access from licensed research rights, canonical acquisition, catalog
activation, and trading.

Dashboard login, an API key, a free plan, an MCP connection, or a successful
sample request proves technical access only. None of those proves permission to
store, back up, transform, retain, or use observations for automated research.

## Read-Only Dashboard Audit

Provider dashboards and consoles were inspected from the existing Chrome
state, and authentication was recorded separately for each provider. The audit
did not reveal or copy a key, change security settings, accept an agreement,
upgrade a plan, place a purchase, call a market-data API, or send a direct
provider communication.

### Massive

As of 2026-07-17:

- the account is authenticated and has one masked API key;
- the active U.S. stocks product is `Stocks Basic` at the free tier;
- the REST usage page reports no requests;
- the agreements page lists no agreements; and
- neither the local experimental MCP server nor the hosted Massive MCP is
  connected to this Codex environment.

This is correctly inert, but it is not acquisition-ready. The dashboard does
not show a written amendment authorizing the required private non-display,
derived, backup, correction-retention, and post-cancellation uses.

- https://massive.com/legal/individuals-terms-of-service
- https://massive.com/terms/market_data_terms.pdf

Massive now recommends its hosted Codex MCP at `https://mcp.massive.com/`, which
uses browser OAuth and mirrors the account's entitlements:

- https://massive.com/docs/ai-tools/clients/codex

The linked local server remains explicitly experimental and exposes broad API
search, arbitrary REST calls, and ephemeral SQLite-backed querying:

- https://github.com/massive-com/mcp_massive

It is not an approved Quant-System acquisition path. It lacks the repository's
SPY-only, fixed-date, immutable-page, checksum, correction, and catalog-lineage
controls. The hosted MCP may be useful later for isolated endpoint/schema
inspection, but it must never supply canonical research observations directly.

The supplied files are documentation indexes, not research feeds or streaming
clients:

- https://massive.com/docs/rest/llms.txt
- https://massive.com/docs/websocket/llms.txt

WebSocket access is outside the historical EOD milestone. If Massive is later
selected, canonical ingestion must use a separately approved repository-owned
SPY acquisition/flat-file path with immutable manifests and written-rights
provenance.

### Alpaca

As of 2026-07-17:

- the dashboard is authenticated in Paper Trading mode;
- it warns that multi-factor authentication must be enabled before setup can
  continue;
- the market-data plan page could not be authoritatively inspected without
  changing that security state;
- the packaged Codex Alpaca connector is available but was not called; and
- no production DPAPI credential file, EOD task, network acquisition, or catalog
  activation exists.

The current Alpaca market-data entitlement therefore remains unverified. Before
any production key is stored or used, the user should complete MFA directly in
the dashboard and then re-run this read-only entitlement audit.

Alpaca documents that the Basic plan has historical stock coverage since 2016
and permits historical SIP queries when the end is at least 15 minutes old. The
repository is stricter: it pins `data.alpaca.markets`, SPY, SIP, raw ascending
one-minute bars, and a close-plus-20-minute session gate.

- https://docs.alpaca.markets/us/docs/about-market-data-api
- https://docs.alpaca.markets/us/docs/market-data-faq
- https://docs.alpaca.markets/us/reference/stockbars

Those technical capabilities do not replace the written-rights decision.

### AlgoSeek

As of 2026-07-17, the visible AlgoSeek Console session showed the public
marketplace plus `Create Account` and `Sign In`, so an authenticated account
could not be verified. Two read-only attempts to open the sign-in control did
not navigate or expose a sign-in flow. The audit stopped there rather than
changing browser state or retrying indefinitely. No demo, trial, API, SQL,
download, purchase, or provider contact was started.

The official product documentation makes AlgoSeek a technically credible
candidate for the later bake-off:

- the standard US Equity Trade Only Minute Bar includes SIP trades, including
  FINRA/TRF reports, and exposes OHLC, VWAP, volume, and trade count;
- files are organized as compressed CSV by date and ticker;
- a minute with no qualifying trade may be omitted, so the SPY calendar-exact
  timestamp rule must be proved with samples rather than assumed;
- adjustment factors are available separately and use a stable `SecId`; and
- security-master data supplies identifier history needed to map ticker changes.

- https://algoseek.com/data-sets/docs/eq_trades_1min
- https://algoseek.com/data-sets/docs/eq_adj_factors_basic
- https://algoseek.com/data-sets/docs/eq_sec_master

The preferred future AlgoSeek layout is therefore unadjusted standard
trade-only minute bars as raw observations, plus separately versioned
adjustment-factor and security-master inputs. Provider-adjusted bars may be
retained for reconciliation but must not replace canonical raw observations.

AlgoSeek's public website terms explicitly do not provide a market-data
license. A separate written agreement must authorize the program's actual uses
before even a free demo can become acquisition or catalog evidence:

- https://algoseek.com/terms-of-use

The account owner must sign in manually before a future read-only entitlement
audit. That later audit must not accept a trial, agreement, or purchase without
the user's action-time approval.

## Provider-Neutral Switching Contract

Easy switching happens at the immutable evidence and catalog boundaries, not
by changing a production URL or API key. Every provider must satisfy the same
contract before it can become active:

1. A repository-owned acquisition adapter is pinned to SPY, the approved data
   kind, date bounds, source feed, adjustment mode, and ascending timestamps.
2. The adapter preserves source files or pages and an immutable manifest with
   request parameters, provider and response identifiers, hashes, session
   boundaries, expected and received timestamps, and correction lineage.
3. A canonical decision report binds written-rights evidence, the selected
   vendor, the exact data kind, that vendor's own bake-off cases, and the budget
   gate. Evidence for one vendor or data kind cannot authorize another.
4. Import normalizes only validated immutable artifacts. It never downloads,
   reads dashboard state, calls an MCP server, or treats a mutable alias as
   evidence.
5. Raw observations remain provider-attributed and unadjusted. Corporate
   actions, adjustment factors, security identity, and derived views remain
   separately versioned with complete lineage.
6. A provider switch creates a new revision, runs normal-session, early-close,
   DST, correction, corporate-action, and cross-provider overlap checks, and
   requires an explicit catalog activation decision. It never overwrites the
   prior provider or automatically promotes research.
7. Repository-owned inert adapters and plan-only scheduler tooling may exist and
   be exercised with fixtures before selection. They receive no credentials,
   use no network, install no task, and activate no data. New provider SDKs, MCP
   servers, or network adapters, plus credentialing, network activation, and
   scheduler installation, wait until the exact provider and data kind are
   selected and the applicable final gates pass.

| Provider | Provisional role | Current zero-cost posture | Future adapter boundary |
| --- | --- | --- | --- |
| Alpaca | Primary SPY SIP minute candidate | Paper dashboard authenticated; entitlement blocked on user-completed MFA; no local DPAPI credential file, task, connector call, or market-data request was created or made by this audit | Existing inert SPY-only historical REST path plus immutable session/monthly manifests |
| Massive | Minute/flat-file reconciliation candidate | Stocks Basic, masked key, zero REST use; no agreement or MCP connection | New repository-owned flat-file or REST adapter; MCP never feeds the catalog directly |
| AlgoSeek | SIP trade-minute, adjustment-factor, and identity candidate | Visible console session was unauthenticated; this audit started no demo, trial, download, API/SQL use, or purchase | New CSV/SQL export adapter after written agreement and SPY sample bake-off |
| Databento | Normalized minute/reference-data candidate | RFI draft only; account, key, and subscription state were not audited; this work added no SDK or adapter and made no API request or purchase | New schema-pinned adapter after feed coverage, licensing, and correction semantics pass |
| Norgate | Daily/corporate-action candidate, not the minute primary | RFI draft only; account, license, and updater state were not audited; this work made no download or purchase | New daily/reference adapter only unless written product evidence and samples prove an approved minute product |

Databento documents OHLCV and trades schemas, instrument definitions, and
corporate-action capabilities. Those capabilities make it a useful candidate,
but the exact US-equity dataset/feed, bar construction, symbology, adjustment
lineage, correction behavior, and data kind must be selected and baked off
explicitly rather than hidden behind a generic SDK default:

- https://databento.com/docs/knowledge-base
- https://databento.com/docs/schemas-and-data-formats/corporate-actions

Norgate publicly describes its product as historical daily data with end-of-day
updates, so it remains a daily/reference candidate and cannot satisfy the
one-minute milestone by itself. Treat it as daily/reference-only unless later
written product evidence and authorized samples prove otherwise:

- https://norgatedata.com/

## Final Data-Farm Gate

Keep provider access inert until all applicable items pass in this order:

1. The user reviews and explicitly authorizes sending the five prepared RFIs.
2. Written provider evidence authorizes the exact provider and data kind,
   including local raw-observation storage, private automated research,
   encrypted Proton Drive backup and restore testing, derived data, correction
   and superseded-revision replay, paper/live research use, and continued
   retention and private use of those raw observations, backups, revisions, and
   derived artifacts after cancellation.
3. Only after that written evidence authorizes sample or trial access may an
   applicable provider/data-kind sample be obtained. Minute candidates must pass
   normal-session, early-close, both DST offsets, correction, and cross-provider
   intraday-overlap cases. Daily/reference candidates must pass corporate-action,
   adjustment/identity, correction, and daily-overlap cases. A daily/reference-
   only candidate is not rejected merely because it does not offer minute data.
4. The canonical vendor decision selects the same provider and data kind, and
   the budget hard gate passes.
5. The user explicitly approves any subscription or other cost.
6. The user completes any provider-required account security step, including
   Alpaca MFA and AlgoSeek manual sign-in, before a read-only entitlement audit.
7. Credentials for the selected provider are stored only through an approved
   user-bound secret workflow, never in Git,
   command arguments, logs, task XML, reports, or MCP configuration.
8. One authorized SPY-only acceptance capture proves complete immutable evidence
   with the Gateway stopped and no broker/order/catalog/promotion action.
9. Only then may the approved external files be imported and audited; the
   2024-2025 holdout remains sealed.

Massive MCP authentication, provider connector calls, demos or trials,
recurring acquisition, Task Scheduler installation, paid entitlements, and
live streams are all final-gate actions. They remain absent now.
