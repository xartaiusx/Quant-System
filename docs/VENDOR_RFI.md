# SPY Research Data Vendor RFI

## Purpose

Send the same questions to Massive, Norgate, Databento, AlgoSeek, and Alpaca before a
purchase. This document is a due-diligence checklist, not legal advice. Written
vendor responses and contracts belong only in ignored `Quant Creds`; Git may
contain their SHA-256 hashes and non-sensitive decision metadata.

## Dispatch Status

As of 2026-07-17, the common RFI is prepared but has not been sent because the
configured Gmail connection requires reauthentication. No vendor response or
written right may be inferred from this pending outreach.

Use these vendor-published contact routes, one message per vendor:

| Vendor | Contact route | Status |
| --- | --- | --- |
| Alpaca | `support@alpaca.markets` (request routing to market-data licensing) | Pending |
| Massive | `sales@massive.com` | Pending |
| Databento | `support@databento.com` (request routing to licensing/sales) | Pending |
| Norgate Data | `support@norgatedata.com` | Pending |
| AlgoSeek | `sales@algoseek.com` | Pending |

Official contact references:

- https://alpaca.markets/contact
- https://massive.com/knowledge-base
- https://databento.com/support
- https://norgatedata.com/contact.php
- https://algoseek.com/contact-us

Do not change a row to sent until the sending system returns a durable success
identifier. Store message identifiers and replies only in ignored operator
evidence; tracked documentation records only the public route, date, and status.

## Outbound Message

Subject: `Written rights and SPY historical data sample request`

Send the following text separately to each vendor:

> Hello,
>
> I am a non-professional individual evaluating market-data vendors for private,
> local, automated quantitative research on SPY. Before any purchase or recurring
> download, please confirm in writing whether your governing terms or an available
> amendment permit all of the following: local storage of ticker-filtered SPY
> observations; encrypted backup and restore testing; automated research and model
> training; creation and retention of normalized, adjusted, aggregated, and
> statistical outputs; retention of models, derived artifacts, and compliance,
> tax, and reproducibility evidence after cancellation; preservation and replay of
> corrections and superseded revisions; and use of research outputs for my own
> paper and eventual live trading. I will not redistribute, display, resell, or
> provide the data as a service.
>
> Please also provide or authorize samples covering one normal XNYS session, one
> official early close, timestamps around a daylight-saving transition, an
> ex-dividend date with available corporate-action history, and one corrected
> observation with before/after revision evidence. I need SPY minute
> trades/aggregates plus daily overlap, availability timestamps, delivery latency,
> schema/version notes, checksums, correction policy, and retention lifecycle.
>
> Finally, please provide non-professional pricing, API/export fees and overages,
> minimum term, historical depth, correction access, cancellation handling, and
> estimated three-year total cost for this SPY-only use. Please identify the exact
> governing terms or written amendment supporting your answers.
>
> Thank you.

## Required Rights

Ask the vendor to confirm in writing whether a non-professional individual may:

- store ticker-filtered SPY observations on one local research machine;
- keep an encrypted Proton Drive backup and perform restore drills;
- use observations for automated quantitative research and model training;
- create and retain normalized, adjusted, aggregated, and statistical outputs;
- retain models, research results, derived artifacts, and audit evidence after
  cancellation;
- replay corrections and preserve superseded revisions;
- use research outputs for the account owner's paper and eventual live trading;
- retain required compliance, tax, and reproducibility evidence;
- avoid redistribution, display, resale, or service-bureau use.

Any material ambiguity or prohibited required use fails the rights gate. Do not
infer rights from product features, trial access, or an unwritten statement.
Free API access and successful download are not evidence of these rights.

## Technical Sample Request

Request ticker-filtered SPY exports or API samples covering:

- one normal XNYS session and one official early close;
- timestamps around daylight-saving transitions;
- an ex-dividend date and available split/corporate-action history;
- a corrected observation with before/after revision evidence;
- minute trades/aggregates plus daily overlap for cross-source reconciliation;
- availability timestamps, delivery latency, schema/version notes, checksums,
  correction policy, and retention lifecycle.

## Commercial Questions

Record non-professional monthly price, API/export fees, overages, minimum term,
historical depth, correction access, cancellation handling, three-year TCO,
and estimated SPY-only storage. Whole-market archives are out of scope unless
rights, storage, and TCO separately pass.

## Decision Evidence

After `research-data-bakeoff`, create a local no-secret decision manifest and
run `research-vendor-decision`. Score exactly:

- rights and permitted use: 20;
- data quality: 20;
- coverage, corporate actions, corrections, timestamp/session correctness,
  delivery/operations, and total cost/storage: 10 each.

The $700 monthly limit and all required rights are hard gates. A higher weighted
technical score cannot override either failure.
