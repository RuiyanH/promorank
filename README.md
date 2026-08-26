# PromoRank

Retail personalization and promotion allocation, end to end: a point-in-time-correct
feature pipeline on **Spark + Iceberg + dbt**, a **two-stage recommender**
(two-tower retrieval → gradient-boosted ranking) over the H&M dataset
(32M transactions · 1.4M customers · 105k articles), and a **budget-constrained
promotion policy** on top, evaluated off-policy with confidence intervals.

**Status: in progress.** The data platform and retrieval stage are built; the
ranker, decision layer, and counterfactual evaluation are next.

Three things stated up front, because they shape every number in this repo:

- **H&M is a single retailer, not a marketplace** — the honest description is
  retail personalization + promotion allocation.
- **Prices are scaled, not currency** — all revenue results are relative, never
  dollar amounts.
- **There is no logged experiment and no logging policy** — which governs the
  entire causal-evaluation layer.

Where things stand: the two-tower initially *lost* to a popularity baseline
(recall@100 5.53% vs 6.97%). A measured recovery ladder — tests first, confound
kill, information parity — lifted the shipped candidate-set ceiling to **11.93%**.
The full diagnosis and decision log is in
[`docs/STAGE1_RECOVERY.md`](docs/STAGE1_RECOVERY.md).

**Docs:** [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) (build order and
rationale) · [`docs/STAGE1_RECOVERY.md`](docs/STAGE1_RECOVERY.md) (retrieval
recovery) · [`docs/SETUP_MISHA.md`](docs/SETUP_MISHA.md) (Slurm cluster runbook)

**Writeup:** condensed version at
[ruiyanh.github.io/projects/promorank](https://ruiyanh.github.io/projects/promorank/)

Data is never committed (see `.gitignore`); it comes from the
[H&M Kaggle dataset](https://www.kaggle.com/competitions/h-and-m-personalized-fashion-recommendations).
The Python package is still named `marketrank` (the project's working name);
a rename is pending and deliberately not blocking the build.
