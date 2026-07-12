# SPY Research Data Vendor RFI

## Purpose

Send the same questions to Massive, Norgate, Databento, and AlgoSeek before a
purchase. This document is a due-diligence checklist, not legal advice. Written
vendor responses and contracts belong only in ignored `Quant Creds`; Git may
contain their SHA-256 hashes and non-sensitive decision metadata.

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
