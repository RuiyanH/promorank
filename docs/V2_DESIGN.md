# MarketRank V2 Product and System Design

**Document state:** Owner-authorized execution as of 2026-09-16; independent final acceptance pending. Current evidence and justified adaptations are in [V2_EXECUTION.md](V2_EXECUTION.md).

**Product:** MarketRank Historical Replay System

**Design owner:** Project owner / integrator

**Implementation state:** Integrated candidate; frozen offline quality gates pass; real-release operational verification in progress

**Publication state:** Not published

## 1. Decision summary

MarketRank V2 is an internal ML and product-QA application built from the static H&M Kaggle dataset. It trains a ranking model on historical candidate sets, evaluates that model with strict time boundaries, packages precomputed historical recommendations into immutable releases, and lets an authorized analyst inspect the fixed 20,000-customer evaluation cohort through a local or private API and UI.

V2 is not a live H&M recommender. The repository has no supported source for current H&M customers, transactions, catalog changes, prices, inventory, or outcomes. Buying a server or domain would make the application reachable; it would not create live data or authorize live-product claims.

The V2 product returns ordering scores only. Calibration remains offline diagnostic evidence because the current training spine contains customer-days with an observed purchase, while replay can score customers on arbitrary approved dates. No API or UI field will be described as purchase probability, confidence, or propensity.

## 2. User, problem, and ownership

### 2.1 Primary user

The primary user is an authorized ML engineer, data scientist, product manager, or model reviewer investigating a historical recommendation pipeline. The user wants to answer:

- Which articles did the trained model place in the top 12 for this historical customer/date?
- Which retrieval sources contributed each candidate?
- How did the trained ranker compare with RRF on the identical candidate set?
- What data, model, feature, and release versions produced the result?
- Where does retrieval fail before ranking can help?

This is not a shopper-facing journey. Opaque customer labels are intentionally anonymous. An authorized analyst obtains a customer reference through the paginated customer browser or an approved restricted offline mapping; raw customer IDs are never accepted by the UI or API.

### 2.2 Decision rights

| Role | Accountable decision |
|---|---|
| Project owner / integrator | Product scope, claims, shared contracts, merge order, final verification, promotion, and publication |
| Data/retrieval owner | Point-in-time source correctness, ANN bundle, candidate manifests, and compute evidence |
| Ranking owner | Training population, labels, sampling, model, metrics, calibration diagnostics, and model card |
| Replay/service owner | Immutable release, privacy boundary, DuckDB repository, and API contract |
| Workbench owner | V1/V2 domain adapters, accessible UI behavior, and browser privacy |
| Independent manager | Plan go/no-go and release recommendation; does not implement or self-approve evidence |

An implementation slice may report `slice_complete`; it cannot declare V2 integrated, verified, accepted, promoted, or published. Only the project owner/integrator can make those transitions after cross-slice verification.

## 3. Accepted state versus published state

The project uses explicit states so a reviewed plan or successful component test cannot be mistaken for a released product.

| State | Meaning | Authority |
|---|---|---|
| `proposed` | Design or implementation plan exists | Document author |
| `manager_accepted` | Independent manager approves implementation within the written scope | Independent manager |
| `slice_complete` | One assigned component passes its own tests; integration is unverified | Slice owner |
| `integrated` | Project owner combines slices and resolves shared contracts | Project owner / integrator |
| `verified` | Clean-checkout test, artifact, privacy, performance, and UI evidence passes | Project owner / integrator |
| `promoted` | An immutable release pointer is deliberately selected | Project owner / integrator |
| `published_private` | The promoted release is reachable through an approved private-access mechanism and smoke-tested | Project owner / integrator |
| `published_public` | Not an allowed V2 state | N/A |

Manager acceptance authorizes scoped engineering; it is not publication. Component completion is not integration. A local server is not a verified deployment. A deployment is not a live-data product.

The existing compact V1 Sites deployment remains separate at its current access level. This design does not claim that it is public, private, current, or a durable rollback until the project owner records its release identifier, fixture hash, source commit/tag, CI result, and access setting.

## 4. Source feasibility and claims boundary

### 4.1 What the source can support

- Historical H&M transactions in the Kaggle observation window.
- Historical customer and article identifiers.
- Candidate generation using prior transactions.
- Offline time-split ranking evaluation.
- Static customer/article snapshot attributes with explicit caveats.
- Historical transaction price as a point-in-time feature only when derived strictly before the scoring date.
- Reproducible historical replay for dates whose inputs and artifacts are complete.

### 4.2 What the source cannot support

- Live customers, events, inventory, availability, catalog updates, or prices.
- A claim that an article is currently sold or available.
- Current personalization quality.
- Causal or incremental lift.
- Revenue, conversion, retention, or promotion effectiveness.
- Production reliability at H&M scale.
- A trained model that learns from workbench feedback.

### 4.3 Allowed product language

- "Historical replay"
- "Trained ranker"
- "Ordering score"
- "Candidate source evidence"
- "Historical offline NDCG@12"
- "Candidate recall ceiling"
- "Static snapshot attribute"
- "Backfilled provenance"

### 4.4 Prohibited product language

- "Live H&M recommendations"
- "Current price" or "in stock"
- "Likely to purchase"
- "Purchase probability" or "confidence"
- "Business uplift" or "revenue impact"
- "Production recommender"
- "All H&M customers"

The 20,000-customer product cohort must always be called the fixed historical evaluation cohort. It is not the complete Kaggle customer population and is not a live user base.

## 5. Product scope

### 5.1 Required V2 capabilities

- Versioned five-source candidate generation across required historical dates.
- A date-correct two-tower ANN source.
- A candidate-distribution LightGBM binary ranker.
- Offline calibration diagnostics, kept out of product score semantics.
- RRF and source baselines recomputed on identical V2 candidate sets.
- Immutable DuckDB releases for approved replay dates.
- Local/private FastAPI service with all 20,000 evaluation customers.
- Existing workbench routes backed by a V2 HTTP adapter.
- Provenance, leakage, privacy, performance, and rollback evidence.

### 5.2 Explicit exclusions

- Live feeds and synthetic-live claims.
- Shared feedback or feedback-driven learning.
- Current commerce fields.
- Authentication-platform development.
- Public unauthenticated full-cohort access.
- OPE, reward modeling, causal inference, and promotion optimization.
- Automated business-uplift claims.
- Kaggle submission as the product's success definition.

An optional synthetic demonstration may be designed later under a separate `data_mode=synthetic_demo` release. It cannot enter historical results or be described as observed behavior.

## 6. Data populations and time contract

### 6.1 Two spines that must never be mixed

`active_day` is the offline training/evaluation spine:

- one row per customer-day with at least one observed transaction;
- labels indicate which candidates were purchased on that day;
- used for ranker fitting and offline ranking/calibration diagnostics;
- every metric name and model card states the active-day conditioning.

`replay_day` is the product scoring spine:

- fixed 20,000-customer evaluation cohort crossed with an approved replay date;
- includes customers with and without an observed purchase on that date;
- used to generate inspectable historical rankings;
- never assigned an active-day probability interpretation.

Every candidate, feature, model-input, metric, and release record carries `spine_type`. Builders reject mixed-spine unions.

### 6.2 Warm-up

The candidate pipeline uses a 90-day warm-up. With the current data start of 2018-09-20, the first normally eligible training scoring date is 2018-12-19. Phase 0 must measure and freeze the post-warm-up active-day group and positive counts; the current 8,584,379-group headline may not be reused until its warm-up treatment is reconciled.

### 6.3 Time slices

| Slice | Dates | Allowed V2 use |
|---|---|---|
| `train` | 2018-09-20 through 2020-08-11 | Two-tower/ranker fitting, subject to warm-up |
| `val_tune` | 2020-08-12 through 2020-08-25 | Retrieval/ranker selection only |
| `val_calib` | 2020-08-26 through 2020-09-01 | Offline isotonic calibration only |
| `ope_env` | 2020-09-02 through 2020-09-08 | Context-only history for later scoring dates |
| `test` | 2020-09-09 through 2020-09-15 | Frozen final evaluation and replay eligibility |
| `holdout` | 2020-09-16 through 2020-09-22 | Final non-tuning guardrail and replay eligibility |

The broad `train` slice is further divided into a strict nested chronology:

| Nested slice | Dates | Exclusive use |
|---|---|---|
| `retrieval_fit` | 2018-12-19 through 2020-06-30 | Fit the V2 two-tower retriever |
| `retrieval_select` | 2020-07-01 through 2020-07-14 | Select/freeze the retriever only |
| `ranker_fit` | 2020-07-15 through 2020-08-11 | Generate candidates with the already-frozen retriever and fit the ranker |

The V2 retrieval artifact must be frozen and available after `2020-07-14` and before the first `ranker_fit` scoring date. It may then generate `ranker_fit`, `val_tune`, `val_calib`, `test`, `holdout`, and approved replay candidates. It may not be used retrospectively to create training rows dated before its availability. Rolling cross-fitting is not part of V2.

### 6.4 Resolved `ope_env` policy

V2 changes the earlier blanket unread rule to a narrower, auditable rule:

- `ope_env` rows may be read by point-in-time candidate/feature builders only as antecedent context for scoring dates after 2020-09-08.
- They may not become labels, fitting rows, tuning inputs, calibration inputs, OPE/reward evidence, or reported standalone metrics.
- Reads must identify `usage=context_only`, consumer job, target scoring dates, row count, and input snapshot in the manifest.
- A policy test must fail any attempt to build an `active_day` label or model-fit partition from this slice.
- No `ope_env` outcome is reported in V2.

This policy must be reflected in `splits.py` before any Phase 1 production build.

### 6.5 Point-in-time rule

For scoring date `D`, dynamic candidates and features may use transactions strictly before `D` only. Same-day transaction price is a label/outcome and cannot be a feature. Article historical price features use the article's trailing values strictly before `D`, define missingness explicitly, and include missingness indicators.

Mutable static customer fields such as age, FN, Active, club status, and fashion-news frequency are excluded from the complete primary path—including retrieval, candidate generation, and ranking—because their historical effective dates are unavailable. A separately labeled comparator may measure them, but it cannot supply candidates to or replace the primary system without design review. Static article metadata may be used with the disclosure that it reflects a dataset snapshot rather than reconstructed historical state.

## 7. Cohort contract

### 7.1 Product/evaluation cohort

The product/evaluation cohort is the exact restricted ID set underlying the complete V1 candidate snapshot. It is identified by:

- canonical SHA-256 of sorted raw customer IDs;
- checksum of the restricted cohort artifact;
- selection provenance and original source snapshot;
- row count of exactly 20,000.

The raw list and raw-to-opaque mapping are restricted artifacts, never browser assets, API output, logs, or Git-tracked fixtures. Any regeneration orders by `(selection_hash, customer_id)` so hash collisions have a deterministic secondary tie-break.

### 7.2 Training population

The ranker training population is derived only from `train` data and is separately hashed. It cannot be selected by later `val_tune` activity or membership in the V1 product cohort. The default is all post-warm-up, train-eligible active customer-days that satisfy data-quality rules. A smaller sample requires a train-only deterministic selection rule and manager approval.

## 8. Candidate and ANN design

### 8.1 Canonical candidate configuration

One immutable configuration records source names/depths, lookbacks, co-visitation cadence, co-visitation seed depth `recent_k=10`, warm-up, eligible articles, date range, input snapshots, two-tower inference bundle, code revision, dependencies, V1 baseline ID, and scratch/output roots.

The complete V1 reference is `artifacts/candidates/ceiling.json`:

- 20,000 customers;
- 2,762,256 union rows;
- 138.1128 mean candidates per customer;
- 10.77706285795093% historical `val_tune` candidate recall ceiling;
- five source sidecars with backfilled provenance.

This is a one-snapshot reference, not the V2 multi-day baseline. The alternative 90/50/60 configuration and its 11.93% metric receive distinct IDs and must never be mixed with V1 values.

### 8.2 Two-tower inference bundle

The primary V2 retrieval source is a newly trained `v2_pit_safe` bundle. Its customer input contract excludes age bucket, club-member status, fashion-news frequency, FN/Active flags, and all other mutable snapshot customer attributes. It is fit on `retrieval_fit`, selected only on `retrieval_select`, and frozen before `ranker_fit` begins.

The bundle contains model weights, recorded training arguments/metrics, customer/article vocabularies, catalog arrays, embedding normalization/dimensions, feature/schema versions, nested-slice dates, `artifact_available_after`, code/dependency provenance, and content checksums. The loader rejects a scoring date earlier than artifact availability.

The legacy `r2_recency` artifact uses mutable snapshot customer fields and is therefore comparator evidence only. It cannot generate primary V2 candidates.

The default V2 search is exact batched float32 inner-product retrieval, ordered by score descending and then `article_id` ascending. The canonical source identifier remains `ann` for contract compatibility, while user-facing language says "embedding retrieval." HNSW is out of scope unless a later pilot demonstrates necessity and separately freezes approximation parameters and exact-search agreement.

The primary V2 bundle uses no time-varying article-volume input, so the article vector matrix may be computed once per bundle. Daily eligibility masking and refill still apply.

### 8.3 Daily ANN partition interface

Candidate orchestration accepts an explicit `--ann-root`. Each date resolves to one checksum-complete partition containing `(customer_id, day_index, article_id, source, source_rank)` plus schema version, date, bundle ID, cohort/spine ID, depth, counts, and checksum. A candidate chunk reads only matching dates and refuses missing, duplicate, partial, or cross-version partitions.

An article is eligible on scoring date `D` only if its first observed transaction date is strictly earlier than `D`. Every source enforces the same eligibility relation. Embedding retrieval filters or masks future-only articles before final top-k selection and refills until it reaches the configured depth or exhausts eligible articles. The manifest records eligible-catalog size by date.

### 8.4 Candidate union

The five required source artifacts are repurchase, category popularity, global popularity, co-visitation, and canonical source `ann` (displayed as embedding retrieval). Each configured date must have all five artifacts, while an individual customer-day may legitimately have no candidates from an eligibility-dependent source.

The union grain is `(customer_id, day_index, article_id, spine_type)`. It retains fixed membership flags and nullable rank columns for all five sources plus source count. No required source may silently disappear.

## 9. Ranking, sampling, and calibration design

### 9.1 Training row and label

The training row is one unique candidate at `(customer_id, scoring_day, article_id, active_day)`. The label is one when that candidate was purchased on the scoring day and zero otherwise. Multiple positives per customer-day are allowed. Prior purchases remain eligible because repurchase is an intentional source.

### 9.2 Frozen negative-sampling method

- Retain every positive.
- Use one constant negative-retention probability `q=0.05` for every negative in the training build.
- Select negatives by a deterministic keyed hash.
- Do not pass inverse-probability sample weights to LightGBM.
- Record `q`, seed/key identifier, pre/post counts, and sampling code version.
- Apply the corresponding prior-odds correction exactly once to offline score diagnostics.
- Build `val_tune`, `val_calib`, `test`, and `holdout` frames without negative sampling.

Variable-rate sampling requires a new derivation and design review. It may not combine IPW and the simple odds correction.

### 9.3 Model and evaluation

The primary model is LightGBM with the binary objective, trained on candidate rows. Customer-day grouping is used by ranking metrics. A `lambdarank` experiment is outside the approved primary path.

The frozen V1-style comparator uses equal source weights, `k=60`, missing-source contribution zero, duplicate evidence merged by source, score descending, then `article_id` ascending. It is recomputed independently for every scoring date on the identical V2 candidate union.

Ranker tuning uses exactly eight configurations from the Cartesian grid `num_leaves={31,63}`, `learning_rate={0.03,0.05}`, and `min_data_in_leaf={200,1000}`. Other primary settings are fixed: `feature_fraction=0.9`, `bagging_fraction=1.0`, `max_depth=-1`, maximum 2,000 rounds, early stopping after 100 rounds on full unsampled `val_tune` binary log loss, deterministic/column-wise mode, and seed `20260903` for all LightGBM seed fields. Final configuration selection uses end-to-end NDCG@12; ties use candidate-conditional NDCG@12, then fewer leaves, then configuration ID.

For each split, V2 reports both:

1. `active_day_end_to_end_*`: every active-day group remains; groups with no reachable positive receive zero ranking contribution.
2. `active_day_candidate_conditional_*`: only groups with at least one reachable positive, labeled as conditional diagnostic evidence.

Reports include all denominator and reach counts. RRF is recomputed per scoring day on the identical V2 union. Primary metric is end-to-end NDCG@12; secondary metrics include MAP@12, Recall@12, Precision@12, catalog coverage, concentration, source contribution, and activity/candidate-count segments. Candidate recall ceiling remains separate.

Uncertainty uses 2,000 paired customer-cluster bootstrap replicates, seed `20260903`, and a two-sided 95% percentile interval. Promotion requires test end-to-end NDCG@12 relative improvement of at least 2% and a paired absolute-delta lower bound above zero. No predeclared activity segment may fall more than 0.005 absolute NDCG@12, catalog coverage may not fall more than 10% relative, and top-1%-article concentration may not increase more than 10% relative. Holdout must have a positive point delta and pass the same segment/coverage/concentration guardrails. Failure on test or holdout leaves V1 promoted and forbids retuning on either slice.

### 9.4 Offline calibration diagnostic

Isotonic calibration is fit only on full unsampled `val_calib` candidates after the single odds correction. Test and holdout diagnostics also use full unsampled candidates. It estimates per-item purchase incidence conditional on an observed active customer-day and candidate inclusion.

It is not served as probability. API/UI responses expose `ordering_score` plus `score_semantics=ordering_only`. Offline reports include Brier score, log loss, ECE with 15 equal-frequency bins, reliability data, and bin counts. Each bin requires at least 200 rows and the calibration slice requires at least 500 positives overall. Isotonic inference uses `out_of_bounds=clip` and records the calibrator/library version.

## 10. Replay and service design

### 10.1 Valid replay dates

Initial anchors are `2020-09-09` (test start) and `2020-09-16` (holdout start). The release records the retriever availability date after `2020-07-14`, `model_available_after=2020-08-25`, and `calibrator_available_after=2020-09-01`. Earlier replay requests are rejected; earlier slices are offline evaluation panels only.

### 10.2 Immutable release and contracts

The release stores precomputed top-12 rankings in DuckDB and identifies every data/cohort/candidate/feature/model/calibration/release artifact. It uses canonical ordered table-content hashes for logical reproducibility and a full-file checksum for the exact built file. Cross-platform byte-identical DuckDB files are not assumed.

V1 validation remains unchanged: `baseline_fusion`, `fusion_score`, and no probability fields. V2 has a separate schema and discriminated union: `trained_ranker`, `ordering_score`, and `ordering_only` semantics.

### 10.3 API boundary

- Localhost by default; DuckDB read-only.
- Opaque signed cursors bound to release, sort, and position.
- Capped pages and whitelisted SQL sort mappings.
- Search by display label or opaque ref only.
- Separate liveness/readiness.
- Safe redacted errors and request events.
- No feedback write endpoint.
- Nonlocal startup fails without a named/tested private-access mechanism, TLS/reverse proxy, restrictive CORS, request limits, and log redaction.

## 11. Workbench design

The current shared runtime is `workbench/lib`. Preserve the V1 static adapter and validator. Add a V2 HTTP repository and discriminated types; release/date selection; server pagination/search; source evidence; ordering-only and static-snapshot disclosures; all existing failure states; and browser-local feedback explicitly excluded from training.

## 12. Security, retention, publication, and rollback

- HMAC-SHA256 release-scoped refs use external secret material of at least 32 bytes.
- Restricted IDs/mappings, keys, labels, and unsanitized manifests never enter Git, browser bundles, uploads, or routine logs.
- Bundle scans enforce this boundary.
- Large artifacts use explicit `$MARKETRANK_WAREHOUSE` scratch paths.
- Promoted releases/manifests are retained; intermediate cleanup requires project-owner approval and an evidence window.
- Full-cohort V2 remains localhost until private access is named and verified.

Rollback has two separate paths: atomically select a prior immutable V2 release and readiness/smoke-test it, or configure the UI back to static V1 and test all routes. Neither is available until V1 has a clean tag, fixture hash, CI result, deployment identifier, and recorded access level.

## 13. Product-level success

V2 succeeds when an authorized analyst can privately select an approved post-calibration historical date, browse any opaque customer in the fixed cohort, inspect 12 deterministic trained-ranker results with source evidence, and trace them to validated immutable artifacts. Success also requires honest end-to-end RRF comparison, no leakage, no probability/business/live claims, no Spark in requests, and project-owner integration and verification.

Manager acceptance authorizes scoped implementation only. It is not evidence that V2 is integrated, verified, promoted, or published.

## 14. Historical manager decision and current authority

The second independent review returned `NO-GO` for full fan-out. After the amendments above, a focused ruling accepted the architecture and conditionally authorized only foundation Slice A0 after the non-circular G0a prerequisites. The document remains `proposed`, not `manager_accepted`, until G0a evidence is complete and independently confirmed. Full Slices A/B/C require later G0b acceptance, and Slice D has an additional API-fixture hash gate.

The paragraph above records the original pre-execution ruling, not the current
implementation status. On 2026-09-16 the user authorized a single project owner
to build, integrate and make justified plan adaptations. That authorizes the
measured local engineering execution recorded in V2_IMPLEMENTATION.md and
V2_EXECUTION.md; it does not constitute independent approval or waive the final
review, human-usability, privacy and promotion gates.
