export function makeReleaseFixture() {
  const sources = ["ann", "repurchase", "category_pop", "global_pop", "covisit"];
  return {
    meta: {
      schema_version: "1.0.0",
      release_id: "fixture-release-v1",
      as_of: "2020-08-12",
      slice: "val_tune",
      ranking_mode: "baseline_fusion",
      ranking_version: "equal-weight-rrf-v1",
      warning: "Candidate-only baseline with no trained ranker; historical data, not live recommendations.",
      provenance_status: "backfilled",
      demo_customer_count: 1,
      cohort_customer_count: 20000,
      rrf: { k: 60, source_weights: Object.fromEntries(sources.map((source) => [source, 1])) },
    },
    diagnostics: {
      candidate_recall_ceiling: 0.107771,
      mean_candidate_count: 138.1128,
      union_candidate_rows: 2762256,
      source_metrics: sources.map((source, index) => ({
        source,
        candidate_rows: 100 + index,
        solo_recall_ceiling: 0.02 + index / 100,
        reach_customers: 10000 + index,
        reach_fraction: 0.5,
      })),
      definitions: {
        candidate_recall_ceiling: "Held-out purchased pairs found in the union.",
        mean_candidate_count: "Mean unique candidates per customer.",
        source_recall_ceiling: "Held-out purchased pairs found by one source.",
        fusion_score: "Ordering-only reciprocal-rank-fusion value.",
      },
      scope: "Historical validation cohort; the browser exposes a smaller sample.",
    },
    customers: [{
      customer_ref: "demo_0123456789abcdef",
      display_label: "Demo customer 01",
      recommendations: Array.from({ length: 12 }, (_, index) => ({
        position: index + 1,
        article_id: String(1000000000 + index),
        metadata: {
          product_name: `Fixture product ${index + 1}`,
          product_type_name: "Shirt",
          colour_group_name: "Blue",
          department_name: "Fixture department",
          index_group_name: "Fixture index",
          garment_group_name: "Fixture garment",
        },
        fusion_score: 1 / (61 + index),
        source_evidence: [{ source: sources[index % sources.length], source_rank: index + 1 }],
        reason: { code: "similar_patterns", text: "Suggested by the historical similarity source" },
      })),
    }],
  };
}
