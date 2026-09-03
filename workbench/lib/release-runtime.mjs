export const CANONICAL_SOURCES = Object.freeze([
  "ann",
  "repurchase",
  "category_pop",
  "global_pop",
  "covisit",
]);

const sourceSet = new Set(CANONICAL_SOURCES);
const reasonSet = new Set([
  "similar_patterns",
  "previously_purchased",
  "preferred_category",
  "historically_popular",
  "frequently_together",
  "multiple_sources",
]);
const forbiddenKeys = new Set([
  "customer_id",
  "customer_hash",
  "price",
  "inventory",
  "probability",
  "confidence",
]);

export class ReleaseValidationError extends Error {
  constructor(message) {
    super(message);
    this.name = "ReleaseValidationError";
  }
}

function fail(path, message) {
  throw new ReleaseValidationError(`${path}: ${message}`);
}

function objectAt(value, path) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail(path, "expected an object");
  }
  return value;
}

function stringAt(value, path) {
  if (typeof value !== "string" || value.trim() === "") {
    fail(path, "expected a non-empty string");
  }
  return value;
}

function plainStringAt(value, path) {
  if (typeof value !== "string") fail(path, "expected a string");
  return value;
}

function numberAt(value, path, options = {}) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    fail(path, "expected a finite number");
  }
  if (options.integer && !Number.isInteger(value)) fail(path, "expected an integer");
  if (options.min !== undefined && value < options.min) fail(path, `must be at least ${options.min}`);
  if (options.max !== undefined && value > options.max) fail(path, `must be at most ${options.max}`);
  return value;
}

function arrayAt(value, path) {
  if (!Array.isArray(value)) fail(path, "expected an array");
  return value;
}

function assertAllowedKeys(record, allowed, path) {
  for (const key of Object.keys(record)) {
    if (!allowed.has(key)) fail(`${path}.${key}`, "unexpected field");
  }
}

function assertNoForbiddenKeys(value, path = "release") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNoForbiddenKeys(item, `${path}[${index}]`));
    return;
  }
  if (value === null || typeof value !== "object") return;
  for (const [key, nested] of Object.entries(value)) {
    if (forbiddenKeys.has(key.toLowerCase())) fail(`${path}.${key}`, "field is forbidden in the browser release");
    assertNoForbiddenKeys(nested, `${path}.${key}`);
  }
}

function validateSource(source, path) {
  const value = stringAt(source, path);
  if (!sourceSet.has(value)) fail(path, "unknown candidate source");
  return value;
}

function validateRecommendation(value, path) {
  const record = objectAt(value, path);
  assertAllowedKeys(
    record,
    new Set([
      "position",
      "article_id",
      "metadata",
      "fusion_score",
      "source_evidence",
      "reason",
    ]),
    path,
  );

  const evidence = arrayAt(record.source_evidence, `${path}.source_evidence`).map((item, index) => {
    const evidencePath = `${path}.source_evidence[${index}]`;
    const sourceRecord = objectAt(item, evidencePath);
    assertAllowedKeys(sourceRecord, new Set(["source", "source_rank"]), evidencePath);
    return {
      source: validateSource(sourceRecord.source, `${evidencePath}.source`),
      source_rank: numberAt(sourceRecord.source_rank, `${evidencePath}.source_rank`, { integer: true, min: 1 }),
    };
  });
  if (evidence.length === 0) fail(`${path}.source_evidence`, "must include at least one source");
  if (new Set(evidence.map(({ source }) => source)).size !== evidence.length) {
    fail(`${path}.source_evidence`, "contains a duplicate source");
  }

  const metadata = objectAt(record.metadata, `${path}.metadata`);
  const metadataKeys = [
    "product_name",
    "product_type_name",
    "colour_group_name",
    "department_name",
    "index_group_name",
    "garment_group_name",
  ];
  assertAllowedKeys(metadata, new Set(metadataKeys), `${path}.metadata`);
  const normalizedMetadata = Object.fromEntries(
    metadataKeys.map((key) => [key, plainStringAt(metadata[key], `${path}.metadata.${key}`)]),
  );

  const reason = objectAt(record.reason, `${path}.reason`);
  assertAllowedKeys(reason, new Set(["code", "text"]), `${path}.reason`);
  const reasonCode = stringAt(reason.code, `${path}.reason.code`);
  if (!reasonSet.has(reasonCode)) fail(`${path}.reason.code`, "unknown reason code");

  return {
    position: numberAt(record.position, `${path}.position`, { integer: true, min: 1, max: 12 }),
    article_id: stringAt(record.article_id, `${path}.article_id`),
    metadata: normalizedMetadata,
    fusion_score: numberAt(record.fusion_score, `${path}.fusion_score`, { min: Number.MIN_VALUE }),
    source_evidence: evidence,
    reason: {
      code: reasonCode,
      text: stringAt(reason.text, `${path}.reason.text`),
    },
  };
}

function validateCustomer(value, index) {
  const path = `release.customers[${index}]`;
  const record = objectAt(value, path);
  assertAllowedKeys(record, new Set(["customer_ref", "display_label", "recommendations"]), path);
  const recommendations = arrayAt(record.recommendations, `${path}.recommendations`).map((item, itemIndex) =>
    validateRecommendation(item, `${path}.recommendations[${itemIndex}]`),
  );
  if (recommendations.length !== 12) fail(`${path}.recommendations`, "must contain exactly 12 items");
  const positions = recommendations.map(({ position }) => position);
  const articleIds = recommendations.map(({ article_id }) => article_id);
  if (new Set(positions).size !== positions.length) fail(`${path}.recommendations`, "contains duplicate positions");
  if (new Set(articleIds).size !== articleIds.length) fail(`${path}.recommendations`, "contains duplicate article IDs");
  if (positions.some((position, itemIndex) => position !== itemIndex + 1)) {
    fail(`${path}.recommendations`, "positions must be contiguous and sorted");
  }
  return {
    customer_ref: stringAt(record.customer_ref, `${path}.customer_ref`),
    display_label: stringAt(record.display_label, `${path}.display_label`),
    recommendations,
  };
}

function validateMeta(value) {
  const path = "release.meta";
  const record = objectAt(value, path);
  assertAllowedKeys(
    record,
    new Set([
      "schema_version",
      "release_id",
      "as_of",
      "slice",
      "ranking_mode",
      "ranking_version",
      "warning",
      "provenance_status",
      "demo_customer_count",
      "cohort_customer_count",
      "rrf",
    ]),
    path,
  );
  if (record.ranking_mode !== "baseline_fusion") fail(`${path}.ranking_mode`, "must be baseline_fusion");
  if (record.schema_version !== "1.0.0") fail(`${path}.schema_version`, "unsupported schema version");
  if (record.provenance_status !== "backfilled") fail(`${path}.provenance_status`, "must be backfilled");
  if (record.ranking_version !== "equal-weight-rrf-v1") fail(`${path}.ranking_version`, "unsupported fusion version");
  const rrf = objectAt(record.rrf, `${path}.rrf`);
  assertAllowedKeys(rrf, new Set(["k", "source_weights"]), `${path}.rrf`);
  if (rrf.k !== 60) fail(`${path}.rrf.k`, "must equal 60");
  const sourceWeights = objectAt(rrf.source_weights, `${path}.rrf.source_weights`);
  assertAllowedKeys(sourceWeights, sourceSet, `${path}.rrf.source_weights`);
  for (const source of CANONICAL_SOURCES) {
    if (numberAt(sourceWeights[source], `${path}.rrf.source_weights.${source}`) !== 1) {
      fail(`${path}.rrf.source_weights.${source}`, "must equal 1");
    }
  }
  return {
    schema_version: record.schema_version,
    release_id: stringAt(record.release_id, `${path}.release_id`),
    as_of: stringAt(record.as_of, `${path}.as_of`),
    slice: stringAt(record.slice, `${path}.slice`),
    ranking_mode: record.ranking_mode,
    ranking_version: record.ranking_version,
    warning: stringAt(record.warning, `${path}.warning`),
    provenance_status: record.provenance_status,
    demo_customer_count: numberAt(record.demo_customer_count, `${path}.demo_customer_count`, { integer: true, min: 1 }),
    cohort_customer_count: numberAt(record.cohort_customer_count, `${path}.cohort_customer_count`, { integer: true, min: 1 }),
    rrf: { k: rrf.k, source_weights: Object.fromEntries(CANONICAL_SOURCES.map((source) => [source, sourceWeights[source]])) },
  };
}

function validateDiagnostics(value) {
  const path = "release.diagnostics";
  const record = objectAt(value, path);
  assertAllowedKeys(record, new Set(["candidate_recall_ceiling", "mean_candidate_count", "union_candidate_rows", "source_metrics", "definitions", "scope"]), path);
  const sourceMetrics = arrayAt(record.source_metrics, `${path}.source_metrics`).map((item, index) => {
    const itemPath = `${path}.source_metrics[${index}]`;
    const metric = objectAt(item, itemPath);
    assertAllowedKeys(metric, new Set(["source", "candidate_rows", "solo_recall_ceiling", "reach_customers", "reach_fraction"]), itemPath);
    return {
      source: validateSource(metric.source, `${itemPath}.source`),
      candidate_rows: numberAt(metric.candidate_rows, `${itemPath}.candidate_rows`, { integer: true, min: 0 }),
      solo_recall_ceiling: numberAt(metric.solo_recall_ceiling, `${itemPath}.solo_recall_ceiling`, { min: 0, max: 1 }),
      reach_customers: numberAt(metric.reach_customers, `${itemPath}.reach_customers`, { integer: true, min: 0 }),
      reach_fraction: numberAt(metric.reach_fraction, `${itemPath}.reach_fraction`, { min: 0, max: 1 }),
    };
  });
  if (sourceMetrics.length !== 5) fail(`${path}.source_metrics`, "must contain exactly five source rows");
  if (new Set(sourceMetrics.map(({ source }) => source)).size !== 5) fail(`${path}.source_metrics`, "must contain each canonical source exactly once");
  const definitionsRecord = objectAt(record.definitions, `${path}.definitions`);
  const definitionKeys = ["candidate_recall_ceiling", "mean_candidate_count", "source_recall_ceiling", "fusion_score"];
  assertAllowedKeys(definitionsRecord, new Set(definitionKeys), `${path}.definitions`);
  const definitions = Object.fromEntries(definitionKeys.map((key) => [key, stringAt(definitionsRecord[key], `${path}.definitions.${key}`)]));
  return {
    candidate_recall_ceiling: numberAt(record.candidate_recall_ceiling, `${path}.candidate_recall_ceiling`, { min: 0, max: 1 }),
    mean_candidate_count: numberAt(record.mean_candidate_count, `${path}.mean_candidate_count`, { min: 0 }),
    union_candidate_rows: numberAt(record.union_candidate_rows, `${path}.union_candidate_rows`, { integer: true, min: 0 }),
    source_metrics: sourceMetrics,
    definitions,
    scope: stringAt(record.scope, `${path}.scope`),
  };
}

export function validateRelease(input) {
  assertNoForbiddenKeys(input);
  const release = objectAt(input, "release");
  assertAllowedKeys(release, new Set(["meta", "diagnostics", "customers"]), "release");
  const meta = validateMeta(release.meta);
  const diagnostics = validateDiagnostics(release.diagnostics);
  const customers = arrayAt(release.customers, "release.customers").map(validateCustomer);
  if (customers.length === 0) fail("release.customers", "must include at least one demo customer");
  if (meta.demo_customer_count !== customers.length) fail("release.meta.demo_customer_count", "does not match customers.length");
  if (new Set(customers.map(({ customer_ref }) => customer_ref)).size !== customers.length) {
    fail("release.customers", "contains duplicate customer references");
  }
  for (const customer of customers) {
    if (!/^demo_[0-9a-f]{16}$/.test(customer.customer_ref)) fail("release.customers.customer_ref", "must be a release-scoped opaque reference");
    if (!/^Demo customer [0-9]{2}$/.test(customer.display_label)) fail("release.customers.display_label", "must be an approved demo label");
    for (const recommendation of customer.recommendations) {
      if (!/^\d{10}$/.test(recommendation.article_id)) fail("release.customers.recommendations.article_id", "must be a ten-digit article ID");
    }
  }
  return { meta, diagnostics, customers };
}

export function formatPercent(value) {
  return new Intl.NumberFormat("en-US", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 2 }).format(value);
}

export function humanizeSource(source) {
  const labels = {
    ann: "Similar items",
    repurchase: "Previous purchase",
    category_pop: "Category popular",
    global_pop: "Overall popular",
    covisit: "Bought together",
  };
  return labels[source] ?? source;
}

export function recommendationTitle(recommendation) {
  return recommendation.metadata.product_name || recommendation.metadata.product_type_name || `Article ${recommendation.article_id}`;
}

export function recommendationSubtitle(recommendation) {
  return [recommendation.metadata.product_type_name, recommendation.metadata.colour_group_name].filter(Boolean).join(" · ") || "Historical catalog item";
}
