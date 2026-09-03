export const CANONICAL_SOURCES: readonly [
  "ann",
  "repurchase",
  "category_pop",
  "global_pop",
  "covisit",
];

export type SourceName = (typeof CANONICAL_SOURCES)[number];

export interface SourceEvidence {
  source: SourceName;
  source_rank: number;
}

export interface Recommendation {
  position: number;
  article_id: string;
  metadata: {
    product_name: string;
    product_type_name: string;
    colour_group_name: string;
    department_name: string;
    index_group_name: string;
    garment_group_name: string;
  };
  fusion_score: number;
  source_evidence: SourceEvidence[];
  reason: { code: string; text: string };
}

export interface DemoCustomer {
  customer_ref: string;
  display_label: string;
  recommendations: Recommendation[];
}

export interface SourceMetric {
  source: SourceName;
  candidate_rows: number;
  solo_recall_ceiling: number;
  reach_customers: number;
  reach_fraction: number;
}

export interface DemoRelease {
  meta: {
    schema_version: string;
    release_id: string;
    as_of: string;
    slice: string;
    ranking_mode: "baseline_fusion";
    ranking_version: "equal-weight-rrf-v1";
    warning: string;
    provenance_status: "backfilled";
    demo_customer_count: number;
    cohort_customer_count: number;
    rrf: {
      k: 60;
      source_weights: Record<SourceName, number>;
    };
  };
  diagnostics: {
    candidate_recall_ceiling: number;
    mean_candidate_count: number;
    union_candidate_rows: number;
    source_metrics: SourceMetric[];
    definitions: {
      candidate_recall_ceiling: string;
      mean_candidate_count: string;
      source_recall_ceiling: string;
      fusion_score: string;
    };
    scope: string;
  };
  customers: DemoCustomer[];
}

export class ReleaseValidationError extends Error {}
export function validateRelease(input: unknown): DemoRelease;
export function formatPercent(value: number): string;
export function humanizeSource(source: SourceName): string;
export function recommendationTitle(recommendation: Recommendation): string;
export function recommendationSubtitle(recommendation: Recommendation): string;
