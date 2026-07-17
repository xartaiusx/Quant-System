# SPY Research Data Vendor RFI

## Purpose

At the explicitly authorized final data-farm gate, send the same core questions
to Massive, Norgate, Databento, AlgoSeek, and Alpaca before a purchase. This
document is a due-diligence checklist, not legal advice. Written vendor responses
and contracts belong only in ignored `Quant Creds`; Git may contain their
SHA-256 hashes and non-sensitive decision metadata.

## Dispatch Status

As of 2026-07-17, five separate Gmail drafts have been created and read back for
review. Every message remains labeled `DRAFT`; the exact subject has zero
matching messages in Sent. No RFI or direct provider communication has been
sent, and no vendor response or written right may be inferred from these drafts.
They are held until the explicit final data-farm gate.

Use these vendor-published contact routes, one message per vendor:

| Vendor | Contact route | Status |
| --- | --- | --- |
| Alpaca | `support@alpaca.markets` (request routing to market-data licensing) | Drafted - not sent |
| Massive | `sales@massive.com` | Drafted - not sent |
| Databento | `support@databento.com` (request routing to licensing/sales) | Drafted - not sent |
| Norgate Data | `support@norgatedata.com` | Drafted - not sent |
| AlgoSeek | `sales@algoseek.com` | Drafted - not sent |

Official contact references:

- https://alpaca.markets/contact
- https://massive.com/knowledge-base
- https://databento.com/support
- https://norgatedata.com/contact.php
- https://algoseek.com/contact-us

Do not change a row to sent until the user explicitly authorizes dispatch and
the sending system returns a durable success identifier. Store draft/message
identifiers and replies only in ignored operator evidence; tracked documentation
records only the public route, date, and status.

## Outbound Message

Subject: `Written rights and SPY historical data sample request`

Only after final-gate authorization, send the following text separately to each
vendor:

> Hello,
>
> I expect to use the data as a non-professional individual for private, local,
> automated quantitative research on SPY. Please confirm whether you would classify
> this account and use as non-professional, and identify any required attestations.
> Before I access any sample or trial, make a purchase, or begin a recurring
> download, please confirm in writing whether your governing terms or an available
> amendment permit all of the following for each applicable data kind: local
> storage of ticker-filtered SPY raw observations; encrypted private backup to
> Proton Drive and restore testing; automated research and model training;
> creation and retention of normalized, adjusted, aggregated, and statistical
> outputs; preservation and replay of corrections and superseded revisions; and,
> after cancellation, continued retention and private research use of the raw
> observations, encrypted backups, correction revisions, superseded revisions,
> models, derived artifacts, and compliance, tax, and reproducibility evidence.
> Please also confirm that research outputs may be used for my own paper and
> eventual live trading. I will not redistribute, display, resell, or provide the
> data as a service.
>
> Please state which data kinds you actually offer and authorize only samples whose
> written sample or trial license permits the evaluation, storage, backup, and
> retention described above. For minute-data candidates, please provide or
> authorize SPY samples covering one normal XNYS session, one official early close,
> both sides of a daylight-saving offset change, one corrected observation with
> before/after revision evidence, and an interval suitable for intraday overlap
> reconciliation. For daily/reference candidates, including a daily-only Norgate
> role, please provide or authorize SPY daily history, an ex-dividend date with
> corporate-action and adjustment history, identifier history where available, a
> corrected observation with before/after evidence, and a daily overlap interval.
> Minute data is not required for a daily/reference-only decision. For every data
> kind, include availability timestamps, delivery latency, schema/version notes,
> checksums, correction policy, and retention lifecycle.
>
> Finally, please provide the applicable individual/non-professional
> classification requirements and pricing, API/export fees and overages, minimum
> term, historical depth, correction access, cancellation handling, and estimated
> three-year total cost for this SPY-only use. Please identify the exact governing
> terms or written amendment supporting your answers.
>
> Thank you.

## Required Rights

Before dispatch, the account owner must confirm the factual description of the
intended private use. Ask the vendor to confirm the account classification and,
for each applicable data kind, whether that use may:

- store ticker-filtered SPY observations on one local research machine;
- keep an encrypted private Proton Drive backup and perform restore drills;
- use observations for automated quantitative research and model training;
- create and retain normalized, adjusted, aggregated, and statistical outputs;
- replay corrections and preserve superseded revisions;
- after cancellation, retain and privately reuse raw observations, encrypted
  backups, correction and superseded revisions, models, research results,
  derived artifacts, and audit evidence;
- use research outputs for the account owner's paper and eventual live trading;
- retain required compliance, tax, and reproducibility evidence;
- avoid redistribution, display, resale, or service-bureau use.

Any material ambiguity or prohibited required use fails the rights gate. Do not
infer rights from product features, trial access, or an unwritten statement.
Free API access and successful download are not evidence of these rights.

## Technical Sample Request

Do not access a sample or trial until its written license authorizes the required
evaluation, storage, backup, correction, and retention uses. Bind every sample
and decision to its provider and data kind. Request:

- for minute-data candidates, one normal XNYS session, one official early close,
  both daylight-saving offsets, a corrected observation with before/after
  revision evidence, and a cross-provider intraday overlap interval;
- for daily/reference candidates, SPY daily history, an ex-dividend date with
  split/corporate-action and adjustment history, identifier history where
  available, a corrected observation, and a daily overlap interval;
- availability timestamps, delivery latency, schema/version notes, checksums,
  correction policy, and retention lifecycle for every requested data kind.

Norgate remains daily/reference-only unless its written product evidence and an
authorized sample prove an approved minute offering. Lack of minute data must
not fail a decision scoped only to daily/reference data.

## Commercial Questions

Record the provider-confirmed account classification, applicable
individual/non-professional monthly price, API/export fees, overages, minimum
term, historical depth, correction access, cancellation handling, three-year
TCO, and estimated SPY-only storage. Whole-market archives are out of scope
unless rights, storage, and TCO separately pass.

## Decision Evidence

After `research-data-bakeoff`, create a local no-secret decision manifest and
run `research-vendor-decision`. Score exactly:

- rights and permitted use: 20;
- data quality: 20;
- coverage, corporate actions, corrections, timestamp/session correctness,
  delivery/operations, and total cost/storage: 10 each.

The $700 monthly limit and all required rights are hard gates. A higher weighted
technical score cannot override either failure.
