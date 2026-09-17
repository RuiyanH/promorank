# V2 external acceptance checklist

Status: **not performed**. This document is a protocol, not acceptance evidence.
The builder must not sign its own independent review or count automated browser
checks as human participants. V1 remains promoted while any required gate is open.

## Independent release review

A reviewer who did not implement this release should record the reviewed Git
commit, immutable release manifest hash, date, findings and recommendation.
Use `V2_EXECUTION.md`, `V2_RUNBOOK.md`, the aggregate evidence under `artifacts/v2/`
when available, and the draft pull request. Restricted inputs remain local.

- Trace source snapshot, cohort, candidate configuration, feature contract,
  model selection, calibration and final evaluation through their hashes.
- Confirm the final-outcome freeze predates export/evaluation, the eight-model
  grid used only development data, and no failed final gate caused retuning.
- Check active-day versus replay-day semantics, unreachable positives, identical
  RRF candidate sets, uncertainty, segments, coverage and concentration.
- Re-run clean-checkout tests, locked installation and browser-bundle privacy
  checks. Inspect the local-only boundary, errors and signed pagination.
- Verify all 20,000 customers have twelve unique ordered results on both dates.
- Review measured startup/HTTP latency and the limits of that workload; it does
  not establish concurrent production capacity or an operational SLO.
- Exercise V1 rollback and immutable-release readiness failure. A first V2
  candidate has no earlier V2 production release to claim as a tested fallback.
- Explicitly accept or reject the bounded local execution, 100,000-customer
  retriever sample, synthetic Spark/adapter parity coverage and outstanding risks.

Outcome must be `approve`, `changes requested`, or `reject`, with evidence. An
approval cannot override a failed quality gate or missing human study.

## Five-person unassisted workflow study

Recruit five real representative analysts/reviewers. Use only the local/private
workbench on an authorized machine; do not publicly expose the full-cohort API.
Give each person the task text below, without demonstrating the workflow first.
Use a fresh browser profile or clear this study's browser-local reviews between
participants. Collect anonymous participant labels P01–P05, not names or emails.

1. Open V2 and find a specified historical customer using the customer label.
2. Inspect the twelve recommendations and identify the source evidence for one.
3. Change between the two approved historical dates and explain what changed.
4. Record a relevance review, reload, and locate it. Explain where it is stored
   and whether it retrains the model.
5. Open quality evidence and explain the comparison, release status, and why an
   ordering score is neither a purchase probability nor a business-uplift claim.

For each task record completion, elapsed time, any assistance, errors and one
short observation. Do not create fictional participant rows. All five must
complete the workflow without help before `passed_five_users` is recorded;
otherwise preserve failures, fix the usability issue, and repeat the study.

Only after offline, technical, independent and human gates all pass may the
project owner create a newly verified release and explicitly promote it. Private
hosting is a separate decision requiring a named authenticated access boundary.
