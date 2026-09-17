# V2 execution record

## Authority and scope — 2026-09-16

The user authorized the current agent as project owner and builder to restore
reproducibility, execute the real-data pilot, and build V2. This supersedes the
old documents' statements that real compute and integration are unauthorized.
The point-in-time, privacy, evaluation, storage and promotion requirements remain.
Implementation changes and measured evidence are recorded here; a planned
deliverable is not a completed deliverable.

The accepted scope is the historical replay system in V2_DESIGN.md. Shared
feedback, feedback-driven learning, authentication-platform development, live
commerce, promotion optimization and OPE remain excluded. The previous status
assessment incorrectly listed durable shared feedback as required V2 work.

The owner may build independently testable ranking/service components while
compute is pending. Real full-range compute waits for measured pilot acceptance;
promotion waits for frozen evaluation and release verification. Independent
review and the five-person usability study cannot be self-certified by the builder.

## Baseline recovery

- Kingston is mounted at `/Volumes/KINGSTON-DATA`; the warehouse is accessible.
- GitHub retains implementation commit `ff3caf947f637a7cf52662df79aaf48d6584aedb`.
- The recovered baseline `137e8ec` has an identical tracked tree. It remains on
  `build/implementation`; new work uses `codex/v2-industry` from the original history.
- Original release tags were fetched without alteration.
- V1 browser fixture SHA-256 is
  `4a006269543f190d71130d9eac1a63fef3219d8e1222243db4d96cbb17125717`.
- GitHub CI run `33780341658` succeeded on the original implementation commit.
- Test isolation now supplies a disposable Iceberg catalog, configuration and
  Spark spill directory before importing application configuration.

## Verification status

The measured pilot, full development/final frames, eight-configuration model
selection, calibration and frozen final evaluation are complete. Both offline
quality gates pass. The immutable 20,000-customer/two-date replay, real API/UI,
privacy, performance and rollback checks pass. V2 remains a local/private
candidate: independent review and five real unassisted users are outstanding.
Later sections preserve the sequence of earlier checks and superseded pilot
measurements; synthetic evidence is identified separately from real-data checks.

## Execution adaptation and measured pilot

Misha login reaches Duo but approval has not completed. Kingston has 458+ GiB
free and the pinned Spark/Iceberg source export completed successfully locally:
31,028,115 transactions through 2020-09-01, snapshot `5931284054021401369`.
The restricted 20,000-customer cohort reproduces the frozen canonical hash.

The original all-pairs synthetic retriever training routine is unsuitable for
real data. V2 now has bounded minibatch training, sampled-softmax logQ correction,
duplicate-positive masking, and selection on the separate retrieval period.
The owner approves a train-only hash sample of 100,000 retrieval-fit customers
(all their fit positives) and 10,000 of those customers for selection. Ranker
training still uses all active customer-days in ranker_fit. This reduced retriever
is explicitly recorded, not described as training over the complete log.

The Spark source snapshot is exported once. A DuckDB execution adapter handles
daily bounded joins over this restricted export, preserving five-source depths,
prior-day windows, weekly co-visitation cadence, eligibility and source ranks.
The old Spark path remains available. Full Spark/adapter parity is a separate
verification requirement; synthetic future/same-day mutation tests pass.

Initial train-only pilot: 2020-07-15 through 2020-07-21, all seven partitions;
88,241 groups, 13,506,763 candidate rows, 36,435,578 compressed bytes, 109.55 seconds,
2,505,097,216 bytes peak process RSS on macOS. Each partition contains five source
artifacts, a sampled frame and the complete unsampled truth-group spine.
The 35 MiB figure includes sampled training frames; it is not the size of a
fully materialized unsampled feature frame. The pilot has not opened final outcomes.

On this measured local execution path, replace the cluster-specific 500 GiB free
scratch floor with a 64 GiB free-space floor, 4 GiB DuckDB working-memory cap,
20 GiB pilot persistent-output ceiling and bounded per-day execution. Full
development-frame generation is authorized by the owner on this evidence.
No queue allocation, GPU job, or authentication bypass is needed for this adapter.
The first pilot's bundle will be superseded after fixing selection denominators
for post-fit articles; its cost evidence remains valid, and its quality is not a
final result. Superseded artifacts are retained outside Git.

Baseline remote CI: run `35167396447` passed on `0999555` after recovery/isolation.
Run `35169549891` passed on `1414fa9`, including all Spark tests and the V2 additions.

## Reproducibility hardening before final evaluation

The retriever retains selection positives outside its fitted article vocabulary
as misses, rather than dropping them. Training and inference now use identical
same-day recent-item tie ordering. The accepted fit has 1,680,131 positive rows,
4,108 selection rows, and 95,909 fitted articles. Epoch three wins with selection
Recall@100 of 0.031889. This is a bounded retriever diagnostic, not final ranking
quality. The frozen offline bundle records the pilot-bundle and input hashes.

A real repeat-build comparison exposed 148 differing co-visitation rank rows
on the first pilot day due to floating-point reduction ordering. The partial
full build was interrupted and preserved as `ranker-fit-superseded-reduction`.
Both co-visitation aggregations now use explicit stable reduction order. The
corrected pilot and full frames are rebuilt; no final outcomes had been opened.

Synthetic parity with the original Spark implementation passes for repurchase,
category popularity, global popularity and co-visitation. Embedding retrieval
uses the existing exact-search contract tests. The full Python suite passed
178 tests before the latest additional schema checks. Workbench tests pass 17;
lint, production build and strict TypeScript checking pass. Declaration files
were corrected to `.d.mts` so the type checker actually resolves `.mjs` exports.

The implementation additionally records complete split-date coverage, source
and frame hashes, explicit `ope_env` context-only usage, complete truth spines,
both metric denominator families, customer-cluster uncertainty and browser-safe
aggregate reports. Test and holdout remain locked behind a model/calibrator/code
hash-bound evaluation freeze. No model changes are permitted after that freeze.

The builder's acceptance authorizes bounded engineering execution; it does not
substitute for the independent final review or five-person usability study.

The corrected seven-day pilot contains 88,241 groups, 13,505,713 union candidates
and 36,436,513 compressed bytes; wall time 135.68 s, peak RSS 3,454,451,712 bytes.
An independent process rebuilt the first four full-training partitions with
identical physical parquet hashes. A direct relational comparison of the first
day found zero differences in any source or the sampled feature frame.
This costs more than unordered reduction but remains comfortably inside the
local resource budget. The full build uses the corrected pipeline.

Local verification after schema reconciliation: 179 pytest tests passed (Spark
included), dbt 19/19 passed, and workbench 17 tests/build/lint/typecheck passed.
Remote run `35170121174` passed on `08a2825`. The workflow now installs from
`uv.lock` rather than allowing fresh transitive dependency resolution.

## Browser and environment checks during training

A separate fresh locked environment passed 182 pytest tests and 19 dbt checks.
The active training environment's exact installed versions and launch revision
are recorded in the restricted `training-execution.json`; auxiliary developer
utilities differed from the lock, while the consumed core ML versions matched.
The original in-process evaluator is unchanged by a later memory optimization;
the new evaluator exactly matched it on a 5,400-row tied-score parity fixture,
including unreachable groups. The freeze binds the final evaluation code.

The browser checks used an explicitly labeled synthetic QA service, not final
model evidence. Verified: forward/back pagination, search and empty results,
both dates, date-preserving detail links, partial metadata, review persistence
after reload, review isolation across dates, clearing the QA review, invalid
customer/date states, quality-unavailable state, and V1 rollback. At 390 px,
the detail page had one H1, labeled inputs, and no page-level horizontal overflow.
The temporary QA service was stopped after these checks. Real-release browser
verification remains pending.

The client/public bundle scan checked 40 files (818,001 bytes) against the
restricted store and keys: no raw/internal customer IDs, secret material or
restricted artifact extensions. This scope is the V2 browser boundary, not
repository-history cleanup: the original public repository deliberately tracks
legacy H&M pseudonymous comparator artifacts. V2 does not add such artifacts.

The source-extension transaction now preserves existing customer keys, rolls
back mismatched counts, and recovers its sidecar from committed database state
after a crash. Synthetic recovery and idempotence tests pass. API documentation
does not load third-party CDN scripts on the private origin. A `verified` status
is rejected unless offline, technical, independent and five-user acceptances
are all present; this run does not invent those external acceptances.

## Frozen final evaluation

All eight configurations completed. The selected model is
`leaves31_lr0.03_min200`, with 1,993 boosting rounds, fit on 2,851,225 sampled
candidate rows. The training spine contains 361,245 active customer-days,
244,760 customers and 1,094,127 distinct truth positives; 135,540 retrieved
positives are retained in the sampled frame. Calibration uses 704,199 unsampled
rows and 2,071 positives, with one prior-odds correction.

The running environment was reconciled to the frozen lock after training ended.
The original development source sidecar was preserved in the freeze before the
store was extended. Freeze SHA-256:
`abbf7461f9dc613a439be825adb84c498522b6bfd330a480c33d8762268da929`.
The later export binds that freeze and the original transaction snapshot; it
contains 31,788,324 rows through 2020-09-22. No final-slice retuning occurred.

| Final slice | Ranker NDCG@12 | RRF NDCG@12 | Relative change | Paired absolute-delta 95% interval | Gate |
|---|---:|---:|---:|---|---|
| Test Sep 9–15 | 0.0733463 | 0.0233907 | +213.57% | [0.0437199, 0.0563139] | Pass |
| Holdout Sep 16–22 | 0.0697404 | 0.0215482 | +223.65% | [0.0424626, 0.0542958] | Pass |

These are end-to-end, observed-active-day metrics, not live quality or business
uplift. Test covers 3,478 active days from 2,880 customers; holdout covers 3,410
days from 2,850 customers. Both pass observed-segment, coverage and concentration
rules. Only low/high activity segments are present: cohort membership requires
val_tune purchases, so no final customer is cold under the 90-day definition.
Cold-start quality is therefore unvalidated, not implicitly passed.
The complete records are `artifacts/v2/quality-report.json` and
`artifacts/v2/model-card.json`.

Retrieval remains the principal limit: candidate recall ceilings are 16.42% and
17.13%. Isotonic calibration improves held-out ECE, but slightly worsens Brier
on both slices and log loss on holdout. It remains an offline diagnostic and is
not served as a purchase probability.

The physical audit reconciles 455 files across 65 partitions, including both
full-cohort replay anchors (6,476,952 candidates, no outcome labels). The global
`ope_env` context-only read audit records 264,657 rows; no labels or fitting rows
come from that slice. Daily manifests separately count personalized-spine context.

Clean GitHub run `35174124558` on `66be130` passed 194 Python tests (Spark included),
19 dbt checks, 22 workbench tests, production build, lint and TypeScript checking.

## Real release and operational verification

Release `v2_candidate_20260916` contains 20,000 release-scoped customers,
40,000 customer/date records and exactly 480,000 recommendations. A full scan
confirms twelve per record, the exact HMAC cohort mapping, zero internal-reference
collisions and zero raw-ID patterns in payloads. The external release key is 0600.
The immutable DuckDB file is 463,482,880 bytes. Its manifest SHA-256 is
`18dcdaf1cdbc01f4a2d5538449864f5ca02bd4465bc61237759dfab29d2405e7`;
database SHA-256 is
`09f8aad8d879cc4abcb789ef9413b4bfb67ab5f843c767c2424b1041de2591ba`.

On Apple M3 / 16 GB RAM, Python 3.11.15:

- Fixed 230-request sequential loopback workload: warm p50 15.29 ms,
  p95 18.52 ms, max 19.20 ms; the 500 ms gate passes.
- Fresh-process start through validated readiness: 4.45 s. Filesystem caches
  were not cleared, so this is not a cold-disk measurement.
- Separate complete-release validation: 3.88 s.
- API resident memory: 651,493,376 bytes after startup and 652,263,424 after the
  workload. These are observations, not a claimed peak or concurrent-load SLO.
- Browser/client plus public assets: 40 files, 820,069 bytes; no restricted
  extensions, raw/internal customer IDs or key material found.

Real-browser checks passed overview, customer listing, forward/back pagination,
search through customer 20000, empty search, twelve ranked items on both dates,
quality results, date-preserving reload, review persistence/date isolation,
invalid-date rejection/recovery, keyboard skip navigation and V1 rollback.
Only this run's QA reviews were cleared afterwards. At 390 px the detail and
quality pages have no document overflow; all comparison columns are visible.
Partial metadata and corrupt-response states remain separately synthetic-tested.

Browser verification found and fixed stale error state after invalid-date
navigation, and a date selection that did not update its deep link. Regression
coverage now totals 23 frontend tests, with build/lint/typecheck passing. The
first V2 candidate has no earlier V2 release to roll back to; V1 is the tested
fallback. Corrupt-release readiness is covered by synthetic fault tests.

Final code CI `35175786936` on `4b4acf1` passes all 194 Python tests, 19 dbt checks,
23 frontend tests, build, lint and typecheck. Subsequent handoff-only commits
record these results without changing the verified implementation.

The aggregate handoff files are `artifacts/v2/{quality-report,model-card,
runtime-verification,verification-summary}.json`. Restricted source exports,
models, frames, keys and the full replay remain on Kingston, outside Git.

### Remaining work and claim boundary

The owner completed the engineering milestones, not independent certification.
Before promotion, obtain independent review and five real unassisted users using
`V2_ACCEPTANCE.md`. Improve retrieval and validate cold-start/inactive-day quality
under a newly declared development/evaluation protocol; do not retune on these
opened final slices. Any hosted full-cohort service needs a separately verified
authenticated private-access boundary. No public V2 deployment, live impact,
production SLO or Misha cluster execution is claimed. V1 remains promoted.
