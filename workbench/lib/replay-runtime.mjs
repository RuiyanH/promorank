const refPattern = /^v2c_[0-9a-f]{24}$/;
const sources = new Set(["ann", "repurchase", "category_pop", "global_pop", "covisit"]);

function exact(value, keys) {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join("|") !== [...keys].sort().join("|")) throw new Error("Historical response failed validation.");
}

export function validateRecommendations(value) {
  exact(value, ["schema_version", "release_id", "as_of", "ranking_mode", "score_semantics", "warning", "model_available_after", "calibrator_available_after", "customer_ref", "recommendations"]);
  if (value.schema_version !== "workbench-api.v2" || value.ranking_mode !== "trained_ranker" || value.score_semantics !== "ordering_only" || !refPattern.test(value.customer_ref) || !Array.isArray(value.recommendations) || value.recommendations.length < 1 || value.recommendations.length > 12) throw new Error("Invalid V2 historical response.");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value.as_of) || value.as_of <= value.model_available_after || value.as_of <= value.calibrator_available_after) throw new Error("Replay date precedes model availability.");
  const articles = new Set();
  let previous = null;
  for (const [index, row] of value.recommendations.entries()) {
    exact(row, ["position", "article_id", "ordering_score", "source_evidence", "article_metadata"]);
    if (row.position !== index + 1 || !/^\d{10}$/.test(row.article_id) || !Number.isFinite(row.ordering_score) || articles.has(row.article_id)) throw new Error("Invalid ranked article.");
    if (previous && (row.ordering_score > previous.ordering_score || (row.ordering_score === previous.ordering_score && row.article_id < previous.article_id))) throw new Error("Invalid recommendation order.");
    previous = row; articles.add(row.article_id);
    if (!Array.isArray(row.source_evidence) || !row.source_evidence.length || new Set(row.source_evidence.map(x => x.source)).size !== row.source_evidence.length) throw new Error("Missing or duplicate source evidence.");
    for (const source of row.source_evidence) {
      exact(source, ["source", "display_name", "source_rank"]);
      if (!sources.has(source.source) || !Number.isInteger(source.source_rank) || source.source_rank < 1 || source.display_name !== (source.source === "ann" ? "embedding_retrieval" : source.source)) throw new Error("Invalid candidate source.");
    }
    exact(row.article_metadata, ["product_type_name", "metadata_status"]);
    if (!(row.article_metadata.product_type_name === null || typeof row.article_metadata.product_type_name === "string") || !["static_snapshot_attribute", "partial_static_snapshot"].includes(row.article_metadata.metadata_status)) throw new Error("Invalid static metadata.");
  }
  return value;
}

export function validateCustomers(value) {
  exact(value, ["schema_version", "release_id", "customers", "next_cursor"]);
  if (value.schema_version !== "workbench-customers.v2" || !Array.isArray(value.customers) || value.customers.length > 100 || !(value.next_cursor === null || typeof value.next_cursor === "string")) throw new Error("Invalid customer page.");
  for (const customer of value.customers) {
    exact(customer, ["customer_ref", "display_label"]);
    if (!refPattern.test(customer.customer_ref) || typeof customer.display_label !== "string") throw new Error("Invalid historical customer.");
  }
  return value;
}

export function replayEnabled() {
  if (typeof window === "undefined") return false;
  const selected = new URLSearchParams(window.location.search).get("mode");
  if (selected === "v1" || selected === "v2") {
    return selected === "v2";
  }
  try { return window.sessionStorage.getItem("marketrank-mode") === "v2"; } catch { return false; }
}

export function subscribeReplayMode(notify) {
  const selected = new URLSearchParams(window.location.search).get("mode");
  if (selected === "v1" || selected === "v2") {
    try { window.sessionStorage.setItem("marketrank-mode", selected); } catch { /* optional preference */ }
  }
  window.addEventListener("popstate", notify);
  return () => window.removeEventListener("popstate", notify);
}

export function serverReplayMode() { return false; }

export async function requestReplay(path, signal) {
  // This adapter is deliberately local until a private hosted API is verified.
  const response = await fetch(`http://127.0.0.1:8070${path}`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(response.status === 404 ? "This historical customer or release was not found." : "The historical replay service is unavailable. Start the local service and retry.");
  try { return await response.json(); } catch { throw new Error("The historical service returned unreadable data."); }
}

export function saveLocalReview(release, day, customer, article, signal) {
  if (!refPattern.test(customer) || !/^\d{10}$/.test(article) || !["relevant", "not_relevant"].includes(signal)) throw new Error("Invalid review identity.");
  const identity = `${release}:${day}:${customer}:${article}`;
  let records = {};
  try { records = JSON.parse(localStorage.getItem("marketrank-reviews-v2") || "{}"); } catch { /* discard invalid local state */ }
  if (!records || typeof records !== "object" || Array.isArray(records)) records = {};
  records[identity] = { release_id: release, as_of: day, customer_ref: customer, article_id: article, signal };
  localStorage.setItem("marketrank-reviews-v2", JSON.stringify(records));
}
