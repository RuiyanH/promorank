# MarketRank V2 Implementation Plan

**Depends on:** `docs/V2_DESIGN.md`

**Document state:** A0 independently approved for component integration; G0b and full fan-out remain `NO-GO`

**Execution rule:** The independent manager conditionally authorized only foundation Slice A0 after G0a. Full Slices A/B/C require accepted G0b evidence; Slice D additionally requires the API-fixture hash gate. Slice owners stop at component completion; the project owner handles integration, final verification, promotion, and publication.

## 1. Delivery strategy

V2 is delivered through a two-stage foundation gate followed by four non-overlapping slices:

1. Daily retrieval and candidate generation.
2. Ranker training and offline calibration diagnostics.
3. Replay release and API service.
4. Workbench V2 adapter and UI states.

G0a contains every non-circular contract, rollback, dependency, privacy, split-policy, count, scratch, ownership, and shared-fixture prerequisite. After independent G0a confirmation, one narrowly scoped A0 owner may implement synthetic daily-retrieval and `--ann-root` capability. The integrator then reviews A0, trains the real V2 retriever, and runs the train-only pilot as G0b. Full Slices A, B, and C remain blocked until independent G0b acceptance. Slice D additionally waits for Slice C to validate the frozen API fixture and the integrator to confirm its unchanged hash. No agent edits shared integration files.

## 2. Integrator-owned prerequisites

The project owner/integrator exclusively owns:

- `docs/V2_DESIGN.md`
- `docs/V2_IMPLEMENTATION.md`
- `pyproject.toml`
- `uv.lock`
- `.github/workflows/ci.yml`
- `.gitignore`
- `README.md`
- `src/marketrank/splits.py`
- final generated artifacts and release pointer
- merge/conflict resolution
- clean-checkout integration and final verification
- deployment and rollback execution

Before foundation Slice A0 is delegated or begun, the integrator must complete G0a:

1. Freeze V1 in a clean commit/tag and record fixture hash, passing CI, deployment/release identifier, and access level.
2. Amend `splits.py` with the approved context-only `ope_env` policy.
3. Add exact Python 3.11-compatible retrieval/ranking/service pins and commit `uv.lock`.
4. Freeze shared V2 schema fixtures.
5. Record the approved compute scratch path and stop thresholds.
6. Record the restricted cohort hash and post-warm-up counts.
7. Record one owner for A0 and the later full Slice A.
8. Confirm test and holdout have not been opened.

Implementation agents may propose diffs for an integrator-owned file in their handoff, but must not edit it.

## 3. Dependencies and reproducibility

### 3.1 Python groups

`pyproject.toml` will separate exact direct pins into:

`retrieval`: Torch, NumPy, and PyArrow. HNSWLib is excluded because V2 freezes exact search.

`ranking`: LightGBM, NumPy, scikit-learn, PyArrow, joblib, and PyYAML.

`service`: FastAPI, Uvicorn with standard extras, DuckDB, Pydantic, and HTTPX.

`dev` contains the existing Spark/dbt/test tools plus all three groups. V2 supports Python 3.11 (`>=3.11,<3.12`); direct versions are frozen after a compatibility probe. `uv.lock` locks all transitive packages. A run records Python version, platform, lock hash, and relevant native-library versions. The service group is lock-resolved but requires a clean runtime compatibility probe before Slice C.

No slice may silently add a dependency. A needed addition is a handoff request to the integrator.

V2 freezes exact batched float32 inner-product retrieval, score descending then `article_id` ascending. The source identifier remains `ann`, but product text says embedding retrieval. Any move to approximate search requires a new design review and a pinned HNSW dependency/parameter/agreement contract.

### 3.2 Frontend

The exact versions in `workbench/package.json` and `workbench/package-lock.json` remain authoritative. The UI slice cannot add runtime dependencies without an integrator decision.

### 3.3 Artifact storage

- Large candidate/training outputs must resolve beneath explicit `$MARKETRANK_WAREHOUSE` scratch.
- Jobs fail if large output resolves under the project or home-directory default.
- Small manifests, schemas, and synthetic fixtures may remain in the repository.
- Secrets and restricted cohort mappings stay outside Git and deployment bundles.

## 4. Foundation gates G0a and G0b

G0a is non-circular evidence/contract work. G0b uses the integrated A0 capability for the real retriever and pilot. Neither gate opens test or holdout.

### 4.1 G0a frozen records

- Candidate configuration ID and exact five source parameters, including co-visitation `recent_k=10`.
- V1 reference ID and separate 90/50/60 experiment ID.
- New `v2_pit_safe` retriever specification, nested dates, and synthetic bundle-contract manifest/checksum; the real bundle is a G0b artifact and `r2_recency` is comparator-only.
- Nested dates: `retrieval_fit=2018-12-19..2020-06-30`, `retrieval_select=2020-07-01..2020-07-14`, and `ranker_fit=2020-07-15..2020-08-11`.
- Restricted 20,000-row product-cohort artifact hash.
- Train-only population rule/hash.
- `active_day` and `replay_day` schemas.
- Post-warm-up first date (`2018-12-19`) and measured group/positive counts.
- Constant training-negative retention probability `q=0.05`.
- End-to-end and candidate-conditional metric definitions.
- Customer-cluster bootstrap method/seed.
- Frozen RRF: equal weights, `k=60`, missing contribution zero, merge source duplicates, score descending/article ID ascending.
- Frozen LightGBM grid of eight configurations and tuning/tie-break rules from the design.
- Frozen bootstrap: 2,000 paired customer clusters, seed `20260903`, 95% percentile interval.
- Frozen promotion rules: >=2% relative test NDCG@12 gain, paired absolute-delta lower bound >0, and the design's segment/coverage/concentration/holdout guardrails.
- Calibration binning, sample minimums, and clipping.
- Test-start and holdout-start replay anchors.
- Python lock hash.
- Named scratch root and compute stop thresholds.
- Machine-checkable `ope_env` permission tests and read-audit contract.
- Integrator-owned shared-fixture hashes under `tests/fixtures/contracts_v2/**`.
- Clean V1 commit/tag record and one named A0/Slice-A owner.
- Evidence that test and holdout remain unopened.

### 4.2 G0a exit and A0 authorization

- Every G0a record exists and is consistent.
- Shared fixtures validate and their hash manifest is frozen.
- V1 rollback evidence is durable.
- 10.7771% and 11.93% experiments are not mixed.
- Independent manager confirms G0a.

Only A0 may then begin, within the prefix scope in Section 6. It may use synthetic data and frozen fixtures only.

### 4.3 G0b real retriever and seven-day pilot

After A0 handoff, the integrator reviews/integrates A0, trains `v2_pit_safe` on `retrieval_fit`, selects it only on `retrieval_select`, and freezes its real manifest, hashes, dependency provenance, input signature, and `artifact_available_after`. The integrator verifies mutable customer snapshot fields are absent from tensors, vocabularies, signature, and manifest.

Before a full candidate/frame build, run the train-only range `2020-07-15..2020-07-21` and mark every artifact `non_release_pilot`. Record active-day group counts and a synthetic or restricted replay-day sizing spine for the same train dates; candidates by source; rows and compressed/uncompressed bytes; wall/stage time; peak memory; shuffle/spill; retries; failed partitions; and projected full-build storage/time/cost. Test and holdout data remain unopened.

Stop if output leaves approved scratch, any source is lost, a resource ceiling is exceeded, or PIT/provenance checks fail. Full compute requires explicit project-owner approval of pilot evidence.

### 4.4 G0b exit and full-slice authorization

- A0 is integrated and independently reviewed; its author did not self-approve.
- Real `v2_pit_safe` chronology, signature, and artifact hashes validate.
- The non-release pilot reconciles all five sources, eligibility, spines, PIT reads, counts, bytes, time, memory, spill, retries, and projected cost.
- Output stayed under approved scratch and no stop threshold fired.
- Independent manager accepts G0b.

Only then may the same owner continue full Slice A while Slices B and C begin concurrently. Slice D remains separately gated.

## 5. Shared contracts frozen before A0 delegation

The integrator exclusively owns and freezes `tests/fixtures/contracts_v2/**`, including a manifest of SHA-256 hashes, for:

- candidate configuration and manifest;
- inference-bundle manifest;
- a three-day five-source candidate set containing active/replay spines, missing eligible-source membership, and unreachable positives;
- ranker-frame input/output schema;
- V2 replay/API response with `trained_ranker` and `ordering_score`;
- standard API error and signed cursor fields.

Fixtures use synthetic IDs and no secrets. Slices consume, but do not redefine, shared semantics.

The entire path `tests/fixtures/contracts_v2/**` is read-only to every slice agent.

## 6. Foundation Slice A0 and full Slice A — Daily retrieval and candidates

A0 is a prefix of Slice A with the same eventual owner and file boundaries.

### 6.1 Exclusive file scope

- `src/marketrank/candidate_pipeline/**`
- `src/marketrank/retrieval_v2/**`
- `src/marketrank/retrieval/inference_bundle.py`
- `src/marketrank/retrieval/daily_ann.py`
- `src/marketrank/jobs/build_daily_ann.py`
- `src/marketrank/jobs/build_candidates.py`
- `tests/test_candidate_config.py`
- `tests/test_inference_bundle.py`
- `tests/test_daily_ann*.py`
- `tests/test_candidate_union*.py`
- `tests/fixtures/candidate_pipeline/**`

### 6.2 Deliverables

- Strict versioned configuration and stable ID.
- `v2_pit_safe` dataset/model/training code, excluding mutable undated customer snapshot fields.
- Bundle trained only on `retrieval_fit` and selected only on `retrieval_select`.
- Legacy `r2_recency` loader used only for comparator evidence.
- Exact once-per-bundle article matrix and per-day customer queries.
- Daily article eligibility from first observed transaction `< scoring day`, with filter/refill before final top-k.
- Checksum-complete daily ANN partition reader/writer.
- `--ann-root` orchestration.
- Five-source active/replay union with fixed evidence columns.
- Counts, reach/overlap, context reads, resume state, and checksums.
- Explicit scratch-output guard.

### 6.3 A0 restrictions

A0 implements the interfaces and capabilities above against synthetic data and frozen shared fixtures. It may run a synthetic three-day pipeline and malformed-input, determinism, eligibility, and existing regression tests. It must not train the real retriever, read test/holdout, run the real pilot, write restricted mappings, perform the full build, or claim Slice A complete.

### 6.4 Tests

- Reject missing/extra sources, invalid depths, bad schema, and cross-version inputs.
- Reject incomplete bundles and checksum mismatches.
- Primary retriever schema and model reject age bucket, club-member status, fashion-news frequency, FN/Active, and other mutable undated customer fields.
- Artifact availability must precede every candidate scoring date.
- Retriever fitting/selection/ranker-fitting nested slices cannot overlap or reorder.
- Golden ANN ranks, uniqueness, and repeat determinism.
- Exact float32 score/article-ID tie-break is stable across batch sizes.
- Future-only articles are filtered and top-k is refilled from eligible articles.
- V2 article matrix reuse works with date-varying eligibility and customer queries.
- Future mutation does not change earlier candidates.
- Reject single-date snapshot reuse and invalid ANN partitions.
- Union keys are unique and retain all source evidence.
- Every date has five valid source artifacts; individual groups may lack an ineligible source.
- Mixed `spine_type` fails.
- `ope_env` appears only as recorded context for later dates.
- Large output outside scratch fails.

### 6.5 Exit A0

Synthetic tests pass and the handoff states `foundation_a0_complete; synthetic capability only; not pilot-validated, integrated, or release-verified`.

### 6.6 Full Slice A after G0b

After G0b acceptance, the same owner may fix pilot-discovered defects within scope, complete production hardening, and rerun synthetic/regression tests. Real full-range compute remains integrator-owned. The handoff states exact files/results/hashes, unrun work, dependency requests, and `slice_complete; not integrated or release-verified`.

## 7. Slice B — Ranking and offline calibration diagnostics

### 7.1 Exclusive file scope

- `src/marketrank/ranking/**`
- `src/marketrank/jobs/build_ranker_frame.py`
- `src/marketrank/jobs/train_ranker.py`
- `src/marketrank/jobs/calibrate_ranker.py`
- `src/marketrank/jobs/evaluate_ranker.py`
- `tests/test_ranker_dataset*.py`
- `tests/test_ranker_model.py`
- `tests/test_ranking_metrics.py`
- `tests/test_sampling_correction.py`
- `tests/test_calibration.py`
- `tests/fixtures/ranking/**`

### 7.2 Deliverables

- Strict active-day frame and candidate/label join.
- PIT/source/static-article feature contract.
- Trailing pre-day price plus missingness.
- Primary feature list excluding mutable undated customer fields.
- Constant-`q` train-only negative sampling.
- Unweighted reproducible binary LightGBM trainer.
- Exactly one prior-odds correction.
- Unsampled later-slice loaders.
- Per-day identical-candidate RRF.
- End-to-end and conditional metric families.
- Customer-cluster bootstrap.
- Offline isotonic diagnostics and model/evaluation cards.

### 7.3 Tests

- Unique grain, all positives, and deterministic constant-`q` negatives.
- No sampling weights passed to LightGBM.
- One correction matches hand calculations.
- Later splits reject sampled input.
- Future and same-day-price leakage tests.
- Mutable undated customer fields rejected from primary features.
- Unreachable groups score zero end-to-end; conditional denominator is separate.
- RRF uses identical per-day candidates.
- Bootstrap clusters all days for a customer.
- Split audit rejects prohibited usage.
- Calibration uses only unsampled `val_calib` and records thresholds/clipping/version.
- Product schema contains no probability/confidence.
- Fixed-seed reload preserves ordering within documented tolerance.

### 7.4 Exit B

Synthetic end-to-end training/evaluation passes without headline quality claims. Full training remains integration compute. Handoff states exact files/results/hashes, unrun work, dependency requests, and `slice_complete; not integrated or release-verified`.

## 8. Slice C — Replay release and API

### 8.1 Exclusive file scope

- `src/marketrank/replay/**`
- `src/marketrank/service/**`
- `contracts/replay-release-v2.schema.json`
- `contracts/workbench-api-v2.schema.json`
- `tests/test_replay_release*.py`
- `tests/test_service_api.py`
- `tests/test_service_privacy.py`
- `tests/fixtures/replay_v2/**`

### 8.2 Deliverables

- Immutable DuckDB builder and logical table hashes.
- HMAC release-scoped refs with external key.
- Artifact availability-date validation.
- Test/holdout-start replay support.
- Read-only repository and FastAPI app.
- Separate live/ready endpoints.
- Release, customer, recommendation, and quality endpoints.
- Signed bound cursors, limits, sort whitelist, safe search.
- Redacted errors/events and fail-closed nonlocal settings.

### 8.3 Tests

- Reject corrupt/missing/cross-version releases.
- Logical hashes repeat for equivalent tables; file hash names exact build only.
- Reject pre-availability replay dates.
- Unique deterministic top 12 and traceable source evidence.
- No raw IDs, labels, secrets, paths, probability, confidence, commerce, or live claims.
- Opaque refs are release/key scoped.
- Read-only DuckDB.
- Cursor tampering/cross-release/sort changes fail.
- Caps and SQL whitelist enforced.
- Safe invalid/not-ready/error states.
- Liveness may pass while readiness fails.
- Nonlocal startup fails without private-access controls.
- Bundle scan excludes restricted artifacts.

### 8.4 Exit C

Synthetic 20-customer/two-date release/API and OpenAPI reconciliation pass. No deployment occurs. Handoff states exact files/results/hashes, unrun work, dependency requests, and `slice_complete; not integrated or release-verified`.

## 9. Slice D — Workbench V2 adapter

Slice C validates its implementation against the already integrator-frozen API fixture. Slice D begins only after the integrator confirms that fixture's hash is unchanged and explicitly releases the slice.

### 9.1 Exclusive file scope

- `workbench/app/**`
- `workbench/lib/**`
- `workbench/tests/**`
- `workbench/styles/**` if present

Excluded: `workbench/public/data/demo-release.json`, dependency/hosting config, and generated output directories.

### 9.2 Deliverables

- Preserve V1 validation/adapter behavior.
- V2 discriminated types and HTTP repository.
- Approved release/date selector.
- Paginated/searchable cohort workflow.
- Ordering score/source evidence and all claims warnings.
- Complete load/empty/partial/invalid/unavailable/corrupt/retry states.
- Browser-local feedback labeled non-training.
- Accessible responsive behavior.

### 9.3 Tests

- Existing V1 tests remain unchanged and pass.
- V1/V2 malformed hybrids fail.
- Four routes/direct navigation render from V2 fixture.
- Pre-availability dates cannot be requested.
- Search uses labels/opaque refs only.
- No prohibited claims or fields.
- All failure states render safely.
- No raw/restricted data enters browser state/storage/telemetry.
- Accessibility, desktop/mobile, lint, SSR, and production build pass.

### 9.4 Exit D

Tests/build pass against the synthetic API fixture. No real deployment or integration claim is made. Handoff states exact files/results/hashes, unrun work, and `slice_complete; not integrated or release-verified`.

## 10. Integration reserved for the project owner

Agents stop before the project owner:

1. Reviews diffs and ownership compliance.
2. Applies shared dependency, lock, split, CI, README, and config changes.
3. Reconciles cross-slice schemas.
4. Runs/approves the seven-day pilot.
5. Builds full candidates/frames on scratch.
6. Trains/tunes, freezes rules, and opens test/holdout once.
7. Builds the real 20,000-customer/two-date release.
8. Connects the workbench to the private API.
9. Runs clean-checkout, Spark, artifact, API, UI, E2E, privacy, accessibility, and performance verification.
10. Obtains independent final release review.
11. Promotes, privately publishes if authorized, smoke-tests, and records evidence.

## 11. Integration exit gates

### G1 — Candidate integrity

Pilot approved; full partitions contain five source artifacts; ANN/PIT provenance passes; physical counts/hashes reconcile.

### G2 — Ranker frame

Warm-up counts frozen; training selection is train-only; leakage tests pass; sampling and unsampled evaluation frames validate.

### G3 — Model selection

RRF is recomputed identically; both denominator families reported; frozen tuning rule and segment/coverage evidence pass.

### G4 — Test and holdout

Test opens once; customer-cluster confidence rule, offline calibration thresholds, and holdout guardrail pass without retuning. Otherwise V1 remains promoted.

### G5 — Replay/API

All 20,000 opaque customers work on two dates; immutable release/privacy/security pass; no Spark/training in requests.

### G6 — UI and performance

Four routes/states pass with real private API; warm p95 is under 500 ms on named hardware/fixed requests; cold start, memory, release, and bundle sizes are separate. Five real representative users complete the workflow without help; this is not automated.

### G7 — Verified private release

Clean verification and both rollback paths pass; scans exclude restricted data/secrets; independent reviewer recommends promotion; project owner explicitly marks `verified`, `promoted`, then optionally `published_private`.

## 12. Handoff contract and stop conditions

Every slice reports files, deviations, exact tests/results, unrun tests, hashes, dependency requests, remaining real compute, risks, assumptions, and `slice_complete; not integrated or release-verified`.

An agent stops rather than editing another slice/integrator file, starting the billion-row build, exposing a public service, creating production secrets, merging, tagging, promoting, publishing, or claiming final verification.

## 13. Implementation-stage success

Delegation succeeds when all four slices are complete against frozen synthetic contracts and provide compliant handoffs. That state is not an integrated V2. Only the project owner's integration and final verification can establish real-artifact, full-compute, service, UI, performance, security, rollback, or publication success.

## 14. Current go/no-go status

The second independent manager review returned `NO-GO` for full fan-out. G0a is complete, and the corrected A0 component is independently approved for user/integrator integration with no remaining P0/P1 finding. Real H&M data, retriever training, the seven-day pilot, test/holdout access, large compute, service/UI work, deployment, and publication remain blocked. Before G0b, the user/integrator must create a clean integrated commit, preserve and revalidate the frozen contract hashes and V1 rollback baseline, run the complete remote workflow including every Spark test, and record the terminal evidence. Full A/B/C require independent G0b acceptance; D has the additional API-fixture hash gate. Nonblocking later hardening: give clearer errors for zero epochs, non-finite learning rates, and out-of-range vocabulary indices.
