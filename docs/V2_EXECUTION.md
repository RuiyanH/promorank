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

The measured real-data pilot and development-frame builds are complete. The
eight-configuration model-selection run is in progress; final evaluation and
real-release operational verification remain pending. Synthetic UI/API checks
are complete, separately from real-data evidence. Later sections preserve the
sequence of earlier checks and superseded pilot measurements.

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
