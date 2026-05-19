# Stage-Gated Audit

Date: 2026-05-19

Scope: completed Quant-System milestones `v0.1` through `v0.11`.

Latest audited tag: `v0.11.0-broker-free-signal-contract`.

## Executive Summary

This audit reviewed the completed pipeline from the safe repository foundation
through the disabled broker-free signal contract scaffold. No P0 safety
violations were found. No broker probe, market probe, history snapshot, paper
execution, live trading, order placement, order modification, or order routing
was run in this task.

One P1 deterministic-test issue was fixed: synthetic historical fixture manifests
used a fixed `generated_at` timestamp that would become stale against the loader's
48-hour freshness check. Related fixture writers now stamp generated manifests at
write time so clean synthetic datasets stay clean in future test runs.

Four small P2 documentation/test-hardening issues were fixed:

- isolated the preflight CLI test from local `.env` and process trading env vars;
- refreshed stale `RUNBOOK.md` next-milestone wording;
- added a tag-to-stage map and explicit `v0.12` not-implemented boundary;
- added a quantitative research gate for future signal/performance work.

All stages are complete or fixed-and-complete. Remaining issues are non-blocking
for the current inert v0.1-v0.11 foundation, but several must be addressed before
any real signal evaluation, performance metric, fill, portfolio accounting, P&L,
or execution milestone.

## Source/Evidence Ledger

| source | evidence used | result |
| --- | --- | --- |
| Repo preflight | `git status --short`, current branch, remote, latest log, tags, `git diff --check` | started on `main` at `005162c`, tag `v0.11.0-broker-free-signal-contract`; no tracked diff before audit document creation |
| Local source/docs/tests/scripts | requested files, `src/trader/**`, `tests/**`, `scripts/**`, report writers | reviewed milestone boundaries, report fields, CLI behavior, tests, scripts, and generated-artifact policy |
| Bounded parallel audit lanes | safety, architecture, tests, docs, quant methodology | no P0/P1 safety findings; test lane found P1 fixture clock issue |
| OpenAI Codex AGENTS.md guidance | https://developers.openai.com/codex/guides/agents-md | confirmed project-scoped instructions and validation guidance are appropriate |
| OpenAI Codex subagents guidance | https://developers.openai.com/codex/concepts/subagents | used only because the task explicitly requested bounded subagent lanes |
| IBKR Campus TWS API docs | https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc/ | checked socket connection, paper/live port defaults, connection lifecycle, read-only/order boundaries, data-farm warning behavior |
| IBKR TWS API initial setup | https://interactivebrokers.github.io/tws-api/initial_setup.html | checked TWS paper/live port notes and Read Only API setting |
| IBKR TWS API market data type docs | https://interactivebrokers.github.io/tws-api/market_data_type.html | checked delayed/frozen market-data request semantics |
| IBKR TWS API historical bars docs | https://interactivebrokers.github.io/tws-api/historical_bars.html | checked `reqHistoricalData` and `cancelHistoricalData` as data request/cleanup APIs |
| QuantConnect Algorithm Framework | https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview | checked modular universe/alpha/portfolio/risk/execution separation |
| QuantConnect reality modeling | https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/key-concepts | checked future need for fills, slippage, fees, brokerage, and capacity assumptions |
| QuantStart backtesting biases | https://www.quantstart.com/articles/Successful-Backtesting-of-Algorithmic-Trading-Strategies-Part-I/ | checked look-ahead, survivorship, optimization/overfitting, and other backtest-bias warnings |

## Global Safety Audit

Safety scans were rerun after fixes. Hits were benign and fell into one of these
categories:

- tests asserting forbidden APIs are absent;
- docs listing forbidden APIs or safety scan commands;
- live ports documented or asserted as rejected;
- existing v0.1 simulator/risk/domain-model placeholders outside the v0.5-v0.11
  offline diagnostic path;
- ignored `__pycache__` and editable-install `egg-info` artifacts.

Confirmed safety state:

- no `placeOrder`, `cancelOrder`, or `reqGlobalCancel` in source or scripts;
- no live executor;
- `TRADING_MODE=live`, `ALLOW_LIVE_ORDERS=true`, and live ports `7496`/`4001`
  remain rejected by config and tests;
- `ALLOW_PAPER_ORDERS` defaults to `false`;
- `PaperExecutor` remains a refusing stub;
- offline loader/feed/backtest/strategy/signal paths do not import `trader.broker`
  or `ibapi`;
- generated reports, generated historical snapshots, `.env`, `.venv`, caches,
  pycache, and egg-info remain ignored and untracked;
- no generated reports or historical snapshots were staged or committed;
- no commit, push, or tag operation was performed.

## Stage-By-Stage Audit Table

| stage | purpose | expected boundary | files reviewed | checks run | issues found | severity | fixes made | validation result | completion status | next gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v0.1 | Safe repo foundation | fail-closed config, dry-run default, live rejected, paper blocked | `.gitignore`, `.env.example`, `pyproject.toml`, `AGENTS.md`, `README.md`, `docs/SAFETY.md`, `src/trader/config.py`, foundation models/risk/execution tests | config tests, full pytest, status CLI, safety scans, artifact scan | CLI preflight test could read local env | P2 | env isolation in `tests/test_broker_client.py` | `202 passed`; status shows live disabled and paper orders blocked | fixed-and-complete | v0.2 read-only broker diagnostics |
| v0.2 | Read-only IB Gateway broker probe | optional `ibapi`, read-only current-time/account diagnostics, no orders | `src/trader/broker/ibkr_client.py`, broker models/reports, `docs/BROKER_SETUP.md`, `docs/RUNBOOK.md`, `tests/test_broker_client.py` | static API scan, mocked broker tests, docs check | none blocking | none | none | mocked tests pass; optional live broker probe skipped | complete | v0.3 market diagnostics |
| v0.3 | Read-only market-data diagnostics | contract/quote/history diagnostics only; cleanup data requests only | broker market-data code, CLI/reporting, market-data tests/docs | safety scan, source review, report schema review | no blocking issue | none | none | tests pass; no order APIs added | complete | v0.4 historical snapshots |
| v0.4 | Historical snapshots/readiness | bounded read-only historical requests; local generated snapshots ignored | `src/trader/data/historical.py`, history CLI/reporting/tests, `.gitignore` | history tests, artifact scan, docs review | generated artifacts present locally but ignored | P3 | documented as ignored local evidence | tests pass; tracked file scan clean | complete | v0.5 offline loader |
| v0.5 | Offline historical loader | local JSONL/manifests only; no broker imports | `src/trader/data/historical_loader.py`, loader CLI/reports/tests | loader tests, stress loader tests, dependency scan, CLI smoke | synthetic fixture freshness would age out | P1 | use fresh manifest `generated_at` in fixture writers | targeted tests pass; full suite passes | fixed-and-complete | v0.6 feed adapter |
| v0.6 | Backtest feed adapter | consume loaded datasets, align frames, no strategy/order/P&L | `src/trader/backtest/data_adapter.py`, feed CLI/reports/tests | feed tests, stress feed tests, CLI/script smoke | inherited fixture freshness risk | P1 | fresh manifest timestamps in feed CLI fixtures | feed CLI/report pass | fixed-and-complete | v0.7 engine |
| v0.7 | Backtest engine skeleton | replay frames only; no strategy, order, fill, P&L | `src/trader/backtest/engine.py`, run CLI/reports/tests | engine tests, stress engine tests, CLI/script smoke | inherited fixture freshness risk | P1 | fresh manifest timestamps in engine CLI fixtures | run CLI/report pass; false safety flags confirmed | fixed-and-complete | v0.8 strategy contract |
| v0.8 | Strategy contract scaffold | no-op contract only, diagnostics only, no real signals/orders/P&L | `src/trader/strategy/interface.py`, strategy-contract CLI/reports/tests | strategy-contract tests, CLI/script smoke, dependency scan | diagnostic module imports feed helpers from `backtest` | P2 | no refactor in this audit; record future gate | passes; no broker/order risk | complete | v0.9 inert runner |
| v0.9 | Inert strategy runner | no-op diagnostics only, no signals/orders/fills/accounting/P&L | `src/trader/strategy/runner.py`, runner CLI/reports/tests | runner tests, stress runner tests, CLI/script smoke | diagnostic module imports feed helpers from `backtest` | P2 | no refactor in this audit; record future gate | passes; report false flags confirmed | complete | v0.10 stress suite |
| v0.10 | Offline fixture stress suite | synthetic ugly data only, broker-free | `tests/fixtures/historical_snapshots.py`, `tests/test_offline_stress_*.py`, docs | targeted stress tests and full suite | fixed fixture timestamp would become stale | P1 | use fresh generated time for stress fixture manifests | full suite passes now and future-stale risk removed | fixed-and-complete | v0.11 signal contract |
| v0.11 | Signal contract scaffold | disabled, diagnostics only, no real signals/order intents/fills/P&L/broker | `src/trader/strategy/signals.py`, signal-contract CLI/reports/tests | signal tests, stress signal tests, CLI/script smoke, report-key checks | none blocking | none | none | report validates with zero signals and all safety flags false | complete | review/commit audit polish before v0.12 |

## Issue Register

| issue id | severity | stage | file(s) | description | evidence | fix applied | remaining risk | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| QSA-001 | P1 | v0.5-v0.10 | `tests/fixtures/historical_snapshots.py`, loader/feed/engine/strategy fixture writers | synthetic manifests used fixed `2026-05-19T04:00Z`; loader marks snapshots stale after 48 hours | test auditor lane plus loader freshness code | changed generated fixture manifests to `datetime.now(UTC)` at write time | none for current synthetic fixtures | fixed |
| QSA-002 | P2 | v0.1-v0.2 | `tests/test_broker_client.py` | preflight CLI test could load local `.env` and process trading env vars | test auditor lane; `load_config()` loads `.env` by default | clear configured env vars and run the test in `tmp_path` | broader CLI coverage still thin | fixed |
| QSA-003 | P2 | cross-stage docs | `docs/RUNBOOK.md`, `docs/STATUS.md` | stale next-milestone wording and implicit tag/stage mapping | docs auditor lane | refreshed safe next milestones, added tag map, marked `v0.12` not implemented | docs must be updated again when v0.12 is approved | fixed |
| QSA-004 | P2 | cross-stage quant methodology | `docs/SAFETY.md` | docs did not explicitly list future backtesting/research hazards | quant methodology lane and source review | added quantitative research gate | future real-signal plan still must implement controls, not just mention them | fixed |
| QSA-005 | P2 | v0.8-v0.11 | `src/trader/strategy/interface.py`, `runner.py`, `signals.py` | strategy/signal diagnostics import neutral feed helpers from `trader.backtest.data_adapter` | architecture auditor lane | no patch; refactor would be broader than this gate | move neutral frame/feed helpers before real signal evaluation | open, non-blocking |
| QSA-006 | P3 | v0.1 foundation | `src/trader/broker/orders.py` | unused helper creates `OrderIntent` from `TradePlan`; no callers found | architecture auditor lane and `rg` | no patch | quarantine or route through approved risk decisions before real execution work | open, non-blocking |
| QSA-007 | P3 | v0.1 tests | `tests/test_cli.py`, `tests/test_strategy.py` | foundation CLI and mean-reversion coverage is thin | test auditor lane | no patch | add direct CLI/registry tests in a future hardening pass | open, non-blocking |

## Fix Log

| fix id | files | change | validation |
| --- | --- | --- | --- |
| F-001 | `tests/fixtures/historical_snapshots.py`, `tests/test_historical_loader.py`, `tests/test_backtest_data_adapter.py`, `tests/test_backtest_engine.py`, `tests/test_strategy_interface.py`, `tests/test_strategy_runner.py` | replaced fixed synthetic manifest `generated_at` values with fresh UTC write-time timestamps | targeted tests passed; full pytest passed |
| F-002 | `tests/test_broker_client.py` | made `test_cli_preflight_runs_without_tws` clear config env vars and run from `tmp_path` | targeted broker client tests passed; full pytest passed |
| F-003 | `docs/RUNBOOK.md` | updated Safe Next Milestones to review audit/signal-contract first and keep v0.12 unimplemented | docs reviewed |
| F-004 | `docs/STATUS.md` | added tag-to-stage map and explicit `v0.12` not-implemented boundary | docs reviewed |
| F-005 | `docs/SAFETY.md` | added future quantitative research gate | docs reviewed |
| F-006 | `docs/STAGE_AUDIT.md` | completed this audit record | `git diff --check` passed |

## Validation Log

Baseline before fixes:

- `.venv/bin/python -m pytest`: `202 passed in 0.94s`
- `.venv/bin/ruff check .`: passed
- `.venv/bin/mypy src`: passed for 41 source files
- `.venv/bin/python -m trader.cli --help`: passed
- `.venv/bin/python -m trader.cli status`: passed; live disabled, order routing disabled, `allow_paper_orders=false`
- `git diff --check`: passed
- global safety scan: benign docs/test/ignored-artifact hits only
- artifact scan: generated reports, `.env`, `.venv`, caches, pycache, egg-info, and `data/historical/` ignored; no tracked generated files found

Targeted after fixes:

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_historical_loader.py tests/test_offline_stress_loader.py tests/test_backtest_data_adapter.py tests/test_backtest_engine.py tests/test_strategy_interface.py tests/test_strategy_runner.py tests/test_broker_client.py -q -p no:cacheprovider`: passed

Final validation:

- `.venv/bin/python -m pytest`: `202 passed in 1.08s`
- `.venv/bin/ruff check .`: passed
- `.venv/bin/mypy src`: passed for 41 source files
- `.venv/bin/python -m trader.cli --help`: passed
- `.venv/bin/python -m trader.cli status`: passed
- `.venv/bin/python -m trader.cli history-index`: passed offline
- `.venv/bin/python -m trader.cli history-load --symbols SPY,AAPL`: passed offline
- `.venv/bin/python -m trader.cli backtest-feed --symbols SPY,AAPL`: passed offline
- `.venv/bin/python -m trader.cli backtest-run --symbols SPY,AAPL`: passed offline
- `.venv/bin/python -m trader.cli strategy-contract --symbols SPY,AAPL`: passed offline
- `.venv/bin/python -m trader.cli strategy-runner --symbols SPY,AAPL`: passed offline
- `.venv/bin/python -m trader.cli signal-contract --symbols SPY,AAPL`: passed offline
- `scripts/run-history-load.sh`: passed offline
- `scripts/run-backtest-feed.sh`: passed offline
- `scripts/run-backtest-run.sh`: passed offline
- `scripts/run-strategy-contract.sh`: passed offline
- `scripts/run-strategy-runner.sh`: passed offline
- `scripts/run-signal-contract.sh`: passed offline
- report-key check: latest backtest, strategy, and signal reports keep broker/order/P&L safety keys false where applicable
- `reports/latest_signal_contract.json`: written and ignored
- `reports/latest_signal_contract.md`: written and ignored
- `git diff --check`: passed

Optional broker validation:

- `broker-probe` and `market-probe` were intentionally not run. The audit did
  not require a live Gateway session, and this task was scoped to avoid broker
  contact unless clearly necessary.

## Final Readiness Decision

Decision: fixed-and-complete for v0.1 through v0.11.

The repository is ready for review of the audit polish changes. Do not start
v0.12 from this working tree until these fixes and `docs/STAGE_AUDIT.md` are
reviewed and committed or otherwise deliberately handled.

Recommended next action: review, commit, push, and tag the audit polish as
`v0.11.1-stage-gated-audit-polish`.

## v0.12 Start Note

The disabled signal diagnostic runner milestone starts only after the
`v0.11.1-stage-gated-audit-polish` gate. Its boundary remains broker-free and
diagnostics-only: it may route offline feed frames through the disabled signal
contract, but it must not add real signal evaluation, trading outputs, order
intents, order simulation, fills, portfolio accounting, P&L, paper execution,
live trading, or broker contact.
