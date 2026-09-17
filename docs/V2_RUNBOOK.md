# V2 local historical replay runbook

## Operating boundary

V2 is a candidate historical replay, not a live recommender or a business-impact
claim. The complete 20,000-customer release is local/private. Do not expose its
API publicly or upload the restricted warehouse, keys, models, or input frames.
V1 remains the promoted baseline until all V2 gates have passed. A passing
offline comparison alone does not authorize promotion.

Python 3.11, Java 17, Node 22 and the pinned project dependencies are required.
Install with `uv sync --extra dev --frozen` and `npm --prefix workbench ci`.
On macOS, LightGBM uses the OpenMP library shipped with Torch; the Makefile sets
the corresponding process environment for verification.

## Start an already built release

Keep Kingston mounted. From the project root, start the API with:

```sh
.venv/bin/python -m marketrank.service \
  --release /Volumes/KINGSTON-DATA/MarketRank/v2-runtime/releases/v2_candidate_20260916
```

In another terminal, start the workbench:

```sh
npm --prefix workbench run dev
```

Open `http://localhost:5173/?mode=v2`. The service binds only to loopback on port
8070. `/health/live` indicates a running process; `/health/ready` separately
indicates a valid immutable release. Altered or missing release files fail
readiness and must not be served. Restart after restoring an intact release.
The UI requests only validated release dates and displays ordering scores.
Customer labels and release-scoped opaque references are the only search keys.

The service has no writes, model training or Spark jobs in request handlers.
The API response schema is in `contracts/workbench-api-v2.schema.json`; the
running service also exposes OpenAPI at `/openapi.json`.

## Verify before accepting changes

```sh
make test
make dbt-ci
npm --prefix workbench run build
npm --prefix workbench test
npm --prefix workbench run lint
npm --prefix workbench run typecheck
```

All Spark tests run against a disposable catalog, without the real warehouse.
GitHub runs the same gates from a clean checkout. Browser testing must cover
overview, listing/search/pagination, customer detail on both dates, quality,
invalid reference/date, unavailable/retry, keyboard navigation and narrow layout.
Automated testing does not replace the five-person unassisted usability study.

With the API running, measure the fixed HTTP workload:

```sh
.venv/bin/python -m marketrank.jobs.verify_replay_runtime \
  --release /Volumes/KINGSTON-DATA/MarketRank/v2-runtime/releases/v2_candidate_20260916 \
  --out /Volumes/KINGSTON-DATA/MarketRank/v2-runtime/runtime-verification.json
```

With port 8070 unused, add `--launch` to start and stop a verifier-owned API process.
This additionally measures process-start-to-ready time and API resident memory
after startup and after the workload. It does not clear the filesystem cache or
claim a peak-memory measurement. Without `--launch`, only the verifier's own
peak memory is recorded, not the existing API process's memory.

This reports actual loopback HTTP latency, separate immutable-release validation
time, artifact size and hardware. It is not a concurrent-load
capacity claim. The warm p95 acceptance threshold is 500 ms.

## Artifact lineage and rebuilding

The current restricted working root is
`/Volumes/KINGSTON-DATA/MarketRank/v2-runtime/pilot-20260916`.
Do not regenerate its internal reference key during reproduction: it determines
the stable pseudonyms used by training and deterministic negative sampling.
Release HMAC keys are separate, externally stored, release-scoped and mode 0600.
Neither key belongs in Git, browser bundles, logs, or public manifests.

The jobs are deliberately explicit, not an unattended scheduler:

1. `export_v2_source` pins the Iceberg snapshot and exports only through Sep 1.
2. `train_retriever_v2` trains on the recorded train-only population and selects
   on retrieval_select. `build_v2_frames --pilot` runs Jul 15–21.
3. After owner acceptance, `freeze_retriever` creates the offline bundle and
   `build_v2_frames` builds ranker_fit, val_tune and val_calib independently.
4. `train_ranker` selects the eight-configuration grid. `calibrate_ranker` uses
   only unsampled val_calib. Complete dates and matching pipeline hashes are
   required throughout.
5. `python -m marketrank.ranking.freeze --root <working-root> --source <source>`
   binds the models, calibrator, code, chronology and thresholds before any
   final outcomes are exported. `export_v2_source --through 2020-09-22
   --evaluation-freeze <freeze>` uses the same snapshot. `extend_v2_source --root
   <working-root> --source <final-source> --scratch-root <approved-root>` appends
   later transactions without changing existing customer keys.
6. Build the complete test and holdout frames once, then run `evaluate_ranker`.
   Never tune on either final slice. A failed gate leaves V1 promoted.
7. Build the two replay_day anchors, then use `build_replay_release --root
   <working-root> --out <new-release-directory> --release-id <safe-id>
   --scratch-root <approved-root>` to write a new immutable directory. Verify
   every customer/date and run API/UI checks. A preserved release key is reused
   when retrying a failed build into a new directory; it is never regenerated.

Run `audit_v2_artifacts --root <working-root> --out <audit-json>` after development
frames; add `--final` after test/holdout/replay builds. It independently checks
all seven physical files per date, complete partition ranges, declared source
counts, frame/spine counts, positive retention and checksums. The final audit
also records the global `ope_env` context-only row count; daily manifests count
personalized-spine context separately. Neither is a standalone `ope_env` outcome
metric. The freeze preserves the original development-store source record before
the live store sidecar is advanced to the final period.

Keep incomplete or superseded outputs for diagnosis. Move a failed partition
to a separately named directory before retrying; do not silently overwrite it.
Daily resumes require exact input, code and file checksums. Raw source exports
and derived artifacts remain on approved scratch, outside Git.

## Rollback and promotion

UI rollback: open `http://localhost:5173/?mode=v1`; the original static fixture
and V1 adapter are retained unchanged. The recorded baseline tag is
`v1.0.1-historical-workbench`.

Service rollback: stop the candidate API and start it against an earlier intact
immutable release directory. It verifies that directory before serving it;
never alter a live database or manifest in place. If no earlier V2 release is
available, stop the V2 API and use V1. A failed candidate does not replace V1.

Promotion requires all quality guardrails, artifact/privacy/security checks,
clean CI, real API/UI performance, five real users, and an independent review.
Private hosting additionally requires a named authenticated access boundary.
The local-only implementation intentionally refuses a nonlocal bind.

The independent-review checklist and unassisted human-study protocol are in
[`V2_ACCEPTANCE.md`](V2_ACCEPTANCE.md). An empty protocol is not passing evidence.
