# MarketRank Workbench v1 implementation

Status: approved for implementation by the independent manager review.

## Outcome

Build a coherent internal historical-demo alpha with two parts:

1. A Python release core that validates five candidate sources, applies a
   deterministic reciprocal-rank-fusion baseline, creates release-scoped opaque
   customer references, and emits a compact static UI release.
2. A Sites/Vinext workbench that reads that release and lets an internal reviewer
   inspect demo customers, recommendation candidates, source evidence, quality
   metrics, and structured local feedback.

This is a candidate exploration workbench. It is not a trained final ranker, a
consumer storefront, a live H&M system, or evidence of business uplift.

## Frozen product boundary

The UI has exactly four routes:

- `/` — historical snapshot and release overview;
- `/customers` — demo-customer browser;
- `/customers/[customerRef]` — top-12 candidate workbench;
- `/quality` — source diagnostics, metric definitions, and limitations.

Every recommendation surface displays:

- `ranking_mode = baseline_fusion`;
- `as_of = 2020-08-12`;
- the release ID;
- candidate-only and no-trained-ranker warnings;
- `provenance_status = backfilled` for the real demo snapshot.

V1 excludes images, prices, inventory, revenue, probabilities, confidence,
discounts, free-text feedback, live-data claims, and online training.

## Data boundary

The real demo fixture is derived from `artifacts/candidates`, the locally complete
five-source snapshot. Its full-cohort diagnostics are:

- 20,000 historical validation customers;
- 2,762,256 union candidate rows;
- 138.1128 candidates per customer on average;
- 10.7771% historical `val_tune` candidate recall ceiling;
- candidate date 2020-08-12.

Only a compact deterministic customer sample is exposed in the browser. The UI
must label the demo-customer count separately from the 20,000-customer metric
scope. Raw customer hashes must not appear in emitted JSON, URLs, browser state,
feedback, telemetry, or logs.

## Baseline fusion contract

- Version: `equal-weight-rrf-v1`.
- Sources: `ann`, `repurchase`, `category_pop`, `global_pop`, `covisit`.
- Each source weight is 1.0.
- `k = 60`.
- A source contributes at most once per customer/article.
- Score: sum of `1 / (60 + source_rank)` over contributing sources.
- Order: fusion score descending, then article ID ascending.
- The top 12 must be unique.
- Missing any source is a hard release error.
- Fusion scores are ordering values, never probabilities or confidence.

## Static release contract

The browser release contains:

- `meta`: schema version, release ID, as-of date, slice, ranking mode, warning,
  provenance status, demo and cohort counts, and RRF constants;
- `diagnostics`: candidate recall ceiling, mean candidate count, union candidate
  rows, source metrics, definitions, and scope;
- `customers`: release-scoped opaque customer reference, display label, and
  recommendations;
- `recommendations`: position, article ID, allowed article metadata, ordering-only
  fusion score, contributing source names/ranks, and provenance-derived reason.

## Work packages

### A — release core

Owns `src/marketrank/release/**`, release fixtures and tests, the JSON Schema,
the fixture-build script, generated demo data, and required Python dependency
edits.

Success means five-source validation rejects incomplete or inconsistent input;
RRF is deterministic and tested; opaque references are release-scoped; builds
are byte-identical; the UI fixture validates; real diagnostics exactly reconcile
to the source ceiling JSON; and no raw customer ID or secret enters output.

### B — workbench UI

Owns `workbench/**` except generated data under `workbench/public/data/**`.

Success means all four routes build and load the static release; limitations and
metric scope are always clear; top-12 candidates are unique and evidence-backed;
structured feedback is idempotent and local; required loading/error/empty states
work; and keyboard, responsive, and accessibility checks pass.

### Integration

The lead owns this document, README/CI changes, contract arbitration, fixture
regeneration, privacy scans, full tests, visual review, and publication.

## Completion gates

1. Release-core tests and JSON Schema validation pass.
2. The generated fixture exactly reconciles full-cohort diagnostics and discloses
   backfilled provenance.
3. UI tests and production build pass.
4. Browser-visible output contains no raw customer hash, unsupported commerce
   field, probability, confidence, or live-data claim.
5. Desktop and mobile layouts are usable, keyboard-accessible, and visually
   reviewed.
6. All existing fast Python tests remain green.
7. The validated Sites build is published, or a concrete platform blocker is
   recorded without weakening access controls.

## Next milestone, not v1

FastAPI, DuckDB request-time serving, durable shared feedback, authentication,
container deployment, full-cohort browser serving, the trained ranker and
calibration, live retail data, and promotion optimization remain separate future
work. They must pass their own privacy, correctness, performance, and product
validation gates before this project is described as a production recommender.
