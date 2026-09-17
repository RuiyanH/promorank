const refPattern = /^v2c_[0-9a-f]{24}$/;
const sources = new Set(["ann", "repurchase", "category_pop", "global_pop", "covisit"]);
const releasePattern = /^[a-zA-Z0-9_-]{1,100}$/;
const approvedDates = new Set(["2020-09-09","2020-09-16"]);
const depths={ann:50,repurchase:30,category_pop:40,global_pop:40,covisit:40};

function exact(value, keys) {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join("|") !== [...keys].sort().join("|")) throw new Error("Historical response failed validation.");
}

export function validateRecommendations(value) {
  exact(value, ["schema_version", "release_id", "as_of", "ranking_mode", "score_semantics", "warning", "model_available_after", "calibrator_available_after", "customer_ref", "recommendations"]);
  if (value.schema_version !== "workbench-api.v2" || value.ranking_mode !== "trained_ranker" || value.score_semantics !== "ordering_only" || !refPattern.test(value.customer_ref) || !Array.isArray(value.recommendations) || value.recommendations.length < 1 || value.recommendations.length > 12) throw new Error("Invalid V2 historical response.");
  if (!releasePattern.test(value.release_id) || !approvedDates.has(value.as_of) || value.model_available_after!=="2020-08-25" || value.calibrator_available_after!=="2020-09-01" || typeof value.warning!=="string") throw new Error("Replay date precedes model availability or release is invalid.");
  const articles = new Set();
  let previous = null;
  for (const [index, row] of value.recommendations.entries()) {
    exact(row, ["position", "article_id", "ordering_score", "source_evidence", "article_metadata"]);
    if (row.position !== index + 1 || typeof row.article_id!=="string" || !/^\d{10}$/.test(row.article_id) || !Number.isFinite(row.ordering_score) || articles.has(row.article_id)) throw new Error("Invalid ranked article.");
    if (previous && (row.ordering_score > previous.ordering_score || (row.ordering_score === previous.ordering_score && row.article_id < previous.article_id))) throw new Error("Invalid recommendation order.");
    previous = row; articles.add(row.article_id);
    if (!Array.isArray(row.source_evidence) || !row.source_evidence.length || new Set(row.source_evidence.map(x => x.source)).size !== row.source_evidence.length) throw new Error("Missing or duplicate source evidence.");
    for (const source of row.source_evidence) {
      exact(source, ["source", "display_name", "source_rank"]);
      if (!sources.has(source.source) || !Number.isInteger(source.source_rank) || source.source_rank < 1 || source.source_rank>depths[source.source] || source.display_name !== (source.source === "ann" ? "embedding_retrieval" : source.source)) throw new Error("Invalid candidate source.");
    }
    exact(row.article_metadata, ["product_type_name", "metadata_status"]);
    if (!(row.article_metadata.product_type_name === null || typeof row.article_metadata.product_type_name === "string") || !["static_snapshot_attribute", "partial_static_snapshot"].includes(row.article_metadata.metadata_status)) throw new Error("Invalid static metadata.");
  }
  return value;
}

export function validateCustomers(value) {
  exact(value, ["schema_version", "release_id", "customers", "next_cursor"]);
  if (value.schema_version !== "workbench-customers.v2" || !releasePattern.test(value.release_id) || !Array.isArray(value.customers) || value.customers.length > 100 || new Set(value.customers.map(x=>x?.customer_ref)).size!==value.customers.length || !(value.next_cursor === null || typeof value.next_cursor === "string")) throw new Error("Invalid customer page.");
  for (const customer of value.customers) {
    exact(customer, ["customer_ref", "display_label"]);
    if (!refPattern.test(customer.customer_ref) || !/^Historical customer [0-9]{5}$/.test(customer.display_label)) throw new Error("Invalid historical customer.");
  }
  return value;
}

export function validateReleases(value) {
  exact(value,["schema_version","releases"]);
  if(value.schema_version!=="workbench-releases.v2" || !Array.isArray(value.releases) || !value.releases.length) throw new Error("Invalid historical release list.");
  for(const release of value.releases) {
    exact(release,["release_id","status","dates","customer_count","ranking_mode","score_semantics","warning","model_available_after","calibrator_available_after"]);
    if(!releasePattern.test(release.release_id) || !["candidate","verified"].includes(release.status) || release.ranking_mode!=="trained_ranker" || release.score_semantics!=="ordering_only" || !Number.isInteger(release.customer_count) || release.customer_count<1 || release.customer_count>20000 || !Array.isArray(release.dates) || release.dates.join(",")!=="2020-09-09,2020-09-16" || release.model_available_after!=="2020-08-25" || release.calibrator_available_after!=="2020-09-01" || typeof release.warning!=="string") throw new Error("Release contract failed validation.");
  }
  return value;
}

export function validateQuality(value) {
  exact(value,["schema_version","release_id","quality","provenance","status","warning"]);
  if(value.schema_version!=="workbench-quality.v2" || !releasePattern.test(value.release_id) || !["candidate","verified"].includes(value.status) || typeof value.warning!=="string" || !value.provenance || typeof value.provenance!=="object" || Array.isArray(value.provenance) || !value.quality || typeof value.quality!=="object" || Array.isArray(value.quality)) throw new Error("Quality response failed validation.");
  const report=value.quality;
  if(report.schema_version==="ranker-evaluation.v2") {
    if(typeof report.quality_gate_passed!=="boolean") throw new Error("Invalid offline acceptance status.");
    for(const split of [report.test,report.holdout]) {
      if(!split?.model || !split.rrf || !Array.isArray(split.bootstrap?.ci95) || split.bootstrap.ci95.length!==2 || !split.bootstrap.ci95.every(Number.isFinite) || typeof split.promotion_gate?.passed!=="boolean" || !Array.isArray(split.promotion_gate.failed_rules) || !split.promotion_gate.failed_rules.every(x=>typeof x==="string")) throw new Error("Offline evaluation failed validation.");
      for(const name of ["active_day_end_to_end_ndcg_at_12","candidate_recall_ceiling","groups","customers"]) if(!Number.isFinite(split.model[name])) throw new Error("Invalid offline metric.");
      if(!Number.isFinite(split.rrf.active_day_end_to_end_ndcg_at_12)) throw new Error("Invalid baseline metric.");
      if(!Number.isInteger(split.model.groups) || !Number.isInteger(split.model.customers) || split.model.customers<1 || split.model.groups<split.model.customers || split.bootstrap.ci95[0]>split.bootstrap.ci95[1]) throw new Error("Invalid evaluation denominators or uncertainty.");
      for(const metric of [split.model.active_day_end_to_end_ndcg_at_12,split.model.candidate_recall_ceiling,split.rrf.active_day_end_to_end_ndcg_at_12]) if(metric<0 || metric>1) throw new Error("Offline ranking metric is out of range.");
    }
    if(report.quality_gate_passed!==[report.test,report.holdout].every(x=>x.promotion_gate.passed)) throw new Error("Inconsistent offline acceptance status.");
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
  let response;
  try { response=await fetch(`http://127.0.0.1:8070${path}`, { signal, cache: "no-store" }); }
  catch(error) {
    if(error?.name==="AbortError") throw new Error("The historical service took too long to respond. Please retry.");
    throw new Error("The local historical replay service is unavailable. Start the service and retry.");
  }
  if (!response.ok) throw new Error(response.status === 404 ? "This historical customer or release was not found." : "The historical replay service is unavailable. Start the local service and retry.");
  try { return await response.json(); } catch { throw new Error("The historical service returned unreadable data."); }
}

function localReviews() {
  let records = {};
  try { records = JSON.parse(localStorage.getItem("marketrank-reviews-v2") || "{}"); } catch { /* discard invalid local state */ }
  if (!records || typeof records !== "object" || Array.isArray(records)) records = {};
  records=Object.fromEntries(Object.entries(records).filter(([id,row])=>row && Object.keys(row).sort().join(",")==="article_id,as_of,customer_ref,release_id,signal" && releasePattern.test(row.release_id) && approvedDates.has(row.as_of) && refPattern.test(row.customer_ref) && /^\d{10}$/.test(row.article_id) && ["relevant","not_relevant"].includes(row.signal) && id===`${row.release_id}:${row.as_of}:${row.customer_ref}:${row.article_id}`));
  return records;
}

export function readLocalReviews(release,day,customer) {
  return Object.fromEntries(Object.values(localReviews()).filter(row=>row.release_id===release && row.as_of===day && row.customer_ref===customer).map(row=>[row.article_id,row.signal]));
}

export function saveLocalReview(release, day, customer, article, signal) {
  if (!releasePattern.test(release) || !approvedDates.has(day) || !refPattern.test(customer) || !/^\d{10}$/.test(article) || !["relevant", "not_relevant", null].includes(signal)) throw new Error("Invalid review identity.");
  const identity = `${release}:${day}:${customer}:${article}`;
  const records=localReviews();
  if(signal===null) delete records[identity];
  else records[identity] = { release_id: release, as_of: day, customer_ref: customer, article_id: article, signal };
  localStorage.setItem("marketrank-reviews-v2", JSON.stringify(records));
}
