# MarketRank V2 G0a Evidence Record

**Gate state:** Independently approved for synthetic-only A0; G0b remains blocked

**Scope:** Non-circular prerequisites for synthetic-only foundation Slice A0

## 1. V1 rollback baseline

- Commit: `e71fea856859197b143de8df18c324425a5c9720`
- Tag: `v1.0.1-historical-workbench`
- Remote branch: `origin/build/implementation`
- Fixture SHA-256: `4a006269543f190d71130d9eac1a63fef3219d8e1222243db4d96cbb17125717`
- Source and built fixture hashes: identical
- Local Python verification: 74 passed
- Local dbt verification: 19 passed
- Workbench verification: lint passed, production build passed, 14 tests passed
- Remote CI: run `33768541208` passed on draft PR #1
- CI URL: `https://github.com/RuiyanH/promorank/actions/runs/33768541208`

The first remote run against `v1.0.0-historical-workbench` exposed a
runner-portability defect: Spark workers were forced to use a project-local
`.venv` path that does not exist on GitHub runners. Commit `e71fea8` uses the
project interpreter when present and otherwise the running Python executable.
The targeted local Spark regression after this correction passed 41 tests.

The V1 commit excludes all V2 planning and foundation changes.

## 2. Existing Sites deployment identity

- Project ID: `appgprj_6a995a9b67408191b5b9e6b978cbbdc3`
- Title: MarketRank Historical Workbench
- Version: 1
- Live URL: `https://marketrank-historical-workbench.ruiyan-huang.chatgpt.site`
- Recorded access: `custom`, owner-only, zero external visitors
- Status observed: active

This records the current deployment. G0a does not modify or republish it.

## 3. Temporal policy

- `src/marketrank/splits.py` implements the V2 `ope_env` context-only permission.
- Context is permitted only for target dates after 2020-09-08.
- Label, fit, tune, calibration, OPE, and standalone-metric uses are rejected.
- Every allowed read requires consumer job, target dates, row count, and input snapshot.
- Integrator-owned policy tests pass.

## 4. Nested chronology and unopened outcomes

- `retrieval_fit`: 2018-12-19 through 2020-06-30
- `retrieval_select`: 2020-07-01 through 2020-07-14
- `ranker_fit`: 2020-07-15 through 2020-08-11
- `val_tune`: 2020-08-12 through 2020-08-25
- `val_calib`: 2020-08-26 through 2020-09-01
- `ope_env`: context-only after its end, never an outcome input
- `test` and `holdout`: unopened during G0a

The primary retriever must be frozen after 2020-07-14 and before it generates any `ranker_fit` row.

## 5. Post-warm-up counts

Counts were measured from `local.raw.transactions` with distinct grains and no test/holdout query:

| Range | Active-day groups | Distinct customer/article/day positives | Customers |
|---|---:|---:|---:|
| Post-warm-up train, 2018-12-19..2020-08-11 | 7,406,596 | 23,658,264 | 1,223,553 |
| `retrieval_fit` | 6,861,492 | 21,992,752 | 1,189,073 |
| `retrieval_select` | 183,859 | 571,385 | 145,751 |
| `ranker_fit` | 361,245 | 1,094,127 | 244,760 |

The earlier 8,584,379 headline includes a different warm-up treatment and is not the V2 training denominator.

## 6. Restricted product/evaluation cohort

- Source artifact: `artifacts/twotower/eval_customers`
- Distinct rows: 20,000
- Canonical sorted-ID SHA-256: `6c49cf25819dd75c1f8c2d03d196ffcb2f248bd69538c62c28a728b921381fcf`
- Canonical four-part artifact SHA-256: `4754056cc8a84963550df886f85ad652dfef268065d1f8b9631f95e05b41a69b`

Raw IDs are not copied into this document, Git fixtures, browser assets, or API contracts. Ranker training selection is train-only and does not use this cohort as an eligibility condition.

## 7. Frozen candidate and evaluation choices

- Candidate configuration ID: `v2-five-source-30-40-40-40-50`
- Source depths: repurchase 30, category popularity 40, global popularity 40, co-visitation 40, embedding retrieval 50
- Co-visitation lookback/max-basket/cadence/seed depth: 30 / 20 / 7 days / `recent_k=10`
- Article eligibility: first observed transaction date strictly before scoring date
- Search: exact batched float32 inner product; score descending, article ID ascending
- Legacy `r2_recency`: comparator-only
- RRF: equal weights, `k=60`, missing contribution zero, merge named-source evidence, score descending/article ID ascending
- Training negative retention: constant `q=0.05`, all positives retained, unweighted LightGBM, one odds correction
- Tuning: eight frozen LightGBM configurations from the design, seed `20260903`
- Bootstrap: 2,000 paired customer-cluster replicates, seed `20260903`, 95% percentile interval
- Promotion/segment/coverage/holdout thresholds: frozen in `docs/V2_DESIGN.md`
- Calibration: 15 equal-frequency bins, at least 200 rows per bin and 500 positives overall; isotonic out-of-bounds behavior `clip`

The complete V1 10.7771% candidate-ceiling artifact and separate 11.93% experiment remain separately identified.

## 8. Dependency lock

- Python requirement: 3.11
- Retrieval, ranking, service, and development direct dependencies: exactly pinned in `pyproject.toml`
- Approximate-search dependency: absent
- Lockfile: `uv.lock`, 121 packages, portable registry sources only
- Lockfile SHA-256: `3ca01df575c49a9f6f1278b5cd3b1104ead8986424c2d64de13112b683aad5c9`
- Offline freshness check: `uv lock --check --offline` passed using an empty task-local cache
- Local-path scan: no `/Users/` or `file://` reference is present
- Service dependencies are lock-resolved but have not yet passed a clean runtime
  compatibility probe. That probe is required before Slice C, not A0.

## 9. Shared synthetic contracts

- Integrator-owned path: `tests/fixtures/contracts_v2/**`
- Hash manifest: `tests/fixtures/contracts_v2/SHA256SUMS`
- Contents: candidate config, inference bundle, three-day candidate set, ranker frame, V2 recommendation response, API error/cursor contract, and ownership README
- Shared contract/policy tests: 14 passed
- Complete local Python suite after G0a changes: 88 passed
- Raw customer IDs, secrets, real mappings, test/holdout outcomes, and product probability fields: absent

Slice agents may read but not edit this directory.

## 10. Scratch path and stop thresholds

Read-only historical warehouse:

`/gpfs/radev/project/dijk/rh849/marketrank/warehouse`

V2 bulk derived root:

`/gpfs/radev/scratch/dijk/rh849/marketrank-v2`

- Tables: `/gpfs/radev/scratch/dijk/rh849/marketrank-v2/tables`
- Artifacts: `/gpfs/radev/scratch/dijk/rh849/marketrank-v2/artifacts`
- Spark temporary data: node-local `${TMPDIR:-/tmp}/marketrank-v2-spark`

A production/pilot job fails if bulk output resolves inside the repository, home directory, or project fileset.

Train-only pilot stops:

- Date range must equal 2020-07-15 through 2020-07-21.
- Every output declares `non_release_pilot`.
- At least 500 GiB free scratch and 100,000 free inodes before start.
- Maximum scheduled wall time 8 hours; maximum requested host memory 400 GiB.
- Maximum compressed persistent pilot output 20 GiB.
- Zero missing sources, unrecovered failed dates, checksum mismatches, PIT/eligibility violations, or test/holdout reads.

The integrator stops for a new full-build budget decision if the pilot projects more than 160 GiB compressed persistent data, 1 TiB transient peak scratch, 400 GiB host memory, or 24 hours for one stage.

## 11. Ownership map

- Product owner / integration / final verification: user
- G0a evidence coordinator: primary agent
- Planned A0 and full Slice A owner: `a0_retrieval`
- Independent gate reviewer: `manager_design_review`
- Shared files, locks, fixtures, tags, real training/pilot, merge, release, and deployment: integrator-only

No implementation task has been released at this evidence-record state.

## 12. Independent G0a decision and remaining hard gate

- Independent reviewer decision: `GO` for synthetic-only A0.
- Clean staging commit: `879950d289754aee4f9ecc1cb6d42bdf33b10fad`
  with parent `e71fea856859197b143de8df18c324425a5c9720`.
- The reviewer confirmed the staging commit's reviewed files match this workspace
  byte-for-byte and have no diff-check errors.
- Remote push/CI of the G0a-only staging commit was deferred because this session
  could neither write the linked worktree metadata nor resolve GitHub DNS.
- Before G0b real retriever training or the seven-day pilot, the integrated A0
  commit must contain these exact G0a bytes and pass the complete remote workflow.

Full Slices A/B/C/D, real data, training, pilot compute, deployment, promotion,
and publication remain unauthorized.
