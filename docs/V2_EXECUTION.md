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

## Open verification

Real-data G0b, full V2 evaluation, integration, UI, release and operational
verification are pending. This file will be updated with terminal results.
