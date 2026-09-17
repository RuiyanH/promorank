"use client";

import Link from "next/link";
import { ReplayExperience } from "./ReplayExperience";
import { replayEnabled, subscribeReplayMode } from "@/lib/replay-runtime.mjs";
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import {
  CANONICAL_SOURCES,
  formatPercent,
  humanizeSource,
  recommendationSubtitle,
  recommendationTitle,
  validateRelease,
  type DemoCustomer,
  type DemoRelease,
  type Recommendation,
  type SourceName,
} from "@/lib/release-runtime.mjs";
import {
  clearFeedback,
  readFeedback,
  saveFeedback,
  type FeedbackRecord,
  type FeedbackSignal,
} from "@/lib/feedback";

type View = "overview" | "customers" | "customer" | "quality";
type LoadState =
  | { status: "loading" }
  | { status: "ready"; release: DemoRelease }
  | { status: "unavailable"; message: string }
  | { status: "corrupt"; message: string }
  | { status: "invalid"; message: string };

function ReleaseStamp({ release }: { release: DemoRelease }) {
  return (
    <dl className="release-stamp" aria-label="Release details">
      <div><dt>As of</dt><dd>{release.meta.as_of}</dd></div>
      <div><dt>Release</dt><dd>{release.meta.release_id}</dd></div>
      <div><dt>Ranking</dt><dd><code>{release.meta.ranking_mode}</code></dd></div>
      <div><dt>Provenance</dt><dd>{release.meta.provenance_status}</dd></div>
    </dl>
  );
}

function LoadingState() {
  return (
    <section className="page-section" aria-live="polite" aria-busy="true">
      <div className="eyebrow">Historical release</div>
      <h1>Loading the evaluation snapshot</h1>
      <p className="lede">Checking the release contract before anything is shown.</p>
      <div className="loading-grid" role="status" aria-label="Loading release">
        <span /><span /><span />
      </div>
    </section>
  );
}

function FailureState({ kind, message, retry }: { kind: "unavailable" | "corrupt" | "invalid"; message: string; retry: () => void }) {
  const copy = {
    unavailable: ["Release unavailable", "The historical snapshot could not be reached."],
    corrupt: ["Release file is corrupt", "The snapshot is not readable JSON and has been blocked."],
    invalid: ["Release failed validation", "The snapshot does not match the approved safety contract and has been blocked."],
  }[kind];
  return (
    <section className="page-section compact-state" role="alert">
      <div className="state-mark" aria-hidden="true">!</div>
      <div className="eyebrow">Safe failure</div>
      <h1>{copy[0]}</h1>
      <p className="lede">{copy[1]}</p>
      <p className="error-detail">{message}</p>
      <button className="button primary" type="button" onClick={retry}>Try again</button>
    </section>
  );
}

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <article className="metric-card">
      <p>{label}</p>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}

function Overview({ release }: { release: DemoRelease }) {
  return (
    <>
      <section className="hero page-section">
        <div className="hero-copy">
          <div className="eyebrow">Historical candidate exploration</div>
          <h1>See what fed the shortlist—and where it falls short.</h1>
          <p className="lede">Explore a safe demo sample of candidate recommendations, trace every item to its retrieval sources, and review the limits before making product decisions.</p>
          <div className="button-row">
            <Link className="button primary" href="/customers">Browse demo customers <span aria-hidden="true">→</span></Link>
            <Link className="button secondary" href="/quality">Review quality</Link>
          </div>
        </div>
        <ReleaseStamp release={release} />
      </section>

      <section className="page-section section-rule" aria-labelledby="snapshot-heading">
        <div className="section-heading">
          <div><div className="eyebrow">Release snapshot</div><h2 id="snapshot-heading">What this release actually covers</h2></div>
          <p>The smaller browser sample is deliberately separated from full-cohort diagnostics.</p>
        </div>
        <div className="metrics-grid">
          <Metric label="Historical cohort" value={release.meta.cohort_customer_count.toLocaleString()} note="Customers in metric scope" />
          <Metric label="Browsable sample" value={release.meta.demo_customer_count.toLocaleString()} note="Opaque demo customers in this UI" />
          <Metric label="Candidate rows" value={release.diagnostics.union_candidate_rows.toLocaleString()} note="Union before top-12 baseline fusion" />
          <Metric label="Recall ceiling" value={formatPercent(release.diagnostics.candidate_recall_ceiling)} note="Held-out purchases present in candidates" />
        </div>
      </section>

      <section className="page-section split-panel" aria-labelledby="workflow-heading">
        <div>
          <div className="eyebrow">Review workflow</div>
          <h2 id="workflow-heading">From source evidence to a structured judgment</h2>
          <ol className="step-list">
            <li><span>1</span><div><strong>Choose a demo customer</strong><p>References are release-scoped and contain no raw customer identifier.</p></div></li>
            <li><span>2</span><div><strong>Inspect the ordered top 12</strong><p>Equal-weight reciprocal rank fusion combines five candidate sources.</p></div></li>
            <li><span>3</span><div><strong>Record a local signal</strong><p>Mark relevant or not relevant; no free text or shared write is collected.</p></div></li>
          </ol>
        </div>
        <aside className="boundary-card">
          <span className="boundary-kicker">Interpretation boundary</span>
          <h3>An ordering score is not a prediction.</h3>
          <p>The fusion value only combines source ranks. It does not estimate click likelihood, purchase likelihood, uplift, or confidence.</p>
          <Link href="/quality">Read metric definitions <span aria-hidden="true">→</span></Link>
        </aside>
      </section>
    </>
  );
}

function Customers({ release }: { release: DemoRelease }) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return release.customers;
    return release.customers.filter((customer) => customer.display_label.toLowerCase().includes(needle));
  }, [query, release.customers]);

  return (
    <section className="page-section">
      <div className="page-heading-row">
        <div>
          <div className="eyebrow">Browsable sample · {release.meta.demo_customer_count.toLocaleString()} customers</div>
          <h1>Demo customers</h1>
          <p className="lede">Choose an anonymized historical profile to inspect its top-12 candidate slate.</p>
        </div>
        <ReleaseStamp release={release} />
      </div>
      <div className="search-box">
        <label htmlFor="customer-search">Find a demo label</label>
        <input id="customer-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="For example: Demo customer 03" type="search" />
        <span aria-live="polite">{filtered.length} shown</span>
      </div>
      {release.customers.length === 0 ? (
        <EmptyState title="No demo customers in this release" body="The release is valid but its browser sample is empty." />
      ) : filtered.length === 0 ? (
        <EmptyState title="No matching demo label" body="Try a different demo number. Customer references are intentionally not searchable." />
      ) : (
        <div className="customer-grid">
          {filtered.map((customer, index) => {
            const sourceCount = new Set(customer.recommendations.flatMap((item) => item.source_evidence.map(({ source }) => source))).size;
            return (
              <Link className="customer-card" href={`/customers/${encodeURIComponent(customer.customer_ref)}`} key={customer.customer_ref}>
                <span className="customer-number">{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <h2>{customer.display_label}</h2>
                  <p>{customer.recommendations.length} ordered candidates · {sourceCount} contributing sources</p>
                </div>
                <span className="round-arrow" aria-hidden="true">→</span>
              </Link>
            );
          })}
        </div>
      )}
      <p className="scope-note"><strong>Scope reminder:</strong> these {release.meta.demo_customer_count.toLocaleString()} demo customers are only the browser sample. Quality metrics cover {release.meta.cohort_customer_count.toLocaleString()} historical validation customers.</p>
    </section>
  );
}

function SourceChips({ recommendation }: { recommendation: Recommendation }) {
  return (
    <div className="source-chips" aria-label="Contributing candidate sources">
      {recommendation.source_evidence.map(({ source, source_rank }) => (
        <span className={`source-chip source-${source}`} key={source} title={`${humanizeSource(source)} source rank ${source_rank}`}>
          {humanizeSource(source)} · #{source_rank}
        </span>
      ))}
    </div>
  );
}

function FeedbackControls({ release, customer, recommendation, feedback, onChange }: {
  release: DemoRelease;
  customer: DemoCustomer;
  recommendation: Recommendation;
  feedback: FeedbackRecord[];
  onChange: (next: FeedbackRecord[]) => void;
}) {
  const identity = { release_id: release.meta.release_id, customer_ref: customer.customer_ref, article_id: recommendation.article_id };
  const selected = feedback.find((item) => item.release_id === identity.release_id && item.customer_ref === identity.customer_ref && item.article_id === identity.article_id)?.signal;
  const choose = (signal: FeedbackSignal) => onChange(saveFeedback(feedback, identity, signal));
  return (
    <div className="feedback-controls" aria-label={`Local review for ${recommendationTitle(recommendation)}`}>
      <span>Useful candidate?</span>
      <button type="button" aria-pressed={selected === "relevant"} onClick={() => choose("relevant")}>Relevant</button>
      <button type="button" aria-pressed={selected === "not_relevant"} onClick={() => choose("not_relevant")}>Not relevant</button>
      {selected ? <button className="clear-feedback" type="button" onClick={() => onChange(clearFeedback(feedback, identity))}>Clear</button> : null}
    </div>
  );
}

function CandidateCard({ recommendation, active, onSelect }: { recommendation: Recommendation; active: boolean; onSelect: () => void }) {
  return (
    <article className={`candidate-card${active ? " active" : ""}`}>
      <button className="candidate-main" type="button" onClick={onSelect} aria-expanded={active}>
        <span className="rank-number" aria-label={`Position ${recommendation.position}`}>{String(recommendation.position).padStart(2, "0")}</span>
        <span className="candidate-copy">
          <span className="candidate-type">{recommendation.metadata.index_group_name}</span>
          <strong>{recommendationTitle(recommendation)}</strong>
          <small>{recommendationSubtitle(recommendation)}</small>
          <span className="reason-line">{recommendation.reason.text}</span>
        </span>
        <span className="inspect-label">Inspect <span aria-hidden="true">↗</span></span>
      </button>
      <SourceChips recommendation={recommendation} />
    </article>
  );
}

function CandidateDetail({ release, customer, recommendation, feedback, onFeedback, close }: {
  release: DemoRelease;
  customer: DemoCustomer;
  recommendation: Recommendation;
  feedback: FeedbackRecord[];
  onFeedback: (next: FeedbackRecord[]) => void;
  close: () => void;
}) {
  return (
    <aside className="detail-panel" aria-label={`Details for ${recommendationTitle(recommendation)}`}>
      <button className="panel-close" type="button" onClick={close} aria-label="Close candidate details">×</button>
      <div className="eyebrow">Position {recommendation.position} · Article {recommendation.article_id}</div>
      <h2>{recommendationTitle(recommendation)}</h2>
      <p className="detail-subtitle">{recommendation.metadata.product_type_name} · {recommendation.metadata.colour_group_name}</p>
      <div className="reason-box"><span>Why it appeared</span><strong>{recommendation.reason.text}</strong><small>Reason code: <code>{recommendation.reason.code}</code></small></div>
      <h3>Candidate evidence</h3>
      <SourceChips recommendation={recommendation} />
      <dl className="metadata-list">
        <div><dt>Department</dt><dd>{recommendation.metadata.department_name}</dd></div>
        <div><dt>Index group</dt><dd>{recommendation.metadata.index_group_name}</dd></div>
        <div><dt>Garment group</dt><dd>{recommendation.metadata.garment_group_name}</dd></div>
        <div><dt>Fusion order value</dt><dd>{recommendation.fusion_score.toFixed(6)}</dd></div>
      </dl>
      <p className="score-warning">This ordering value is not a probability or confidence score.</p>
      <FeedbackControls release={release} customer={customer} recommendation={recommendation} feedback={feedback} onChange={onFeedback} />
    </aside>
  );
}

function CustomerWorkbench({ release, customerRef }: { release: DemoRelease; customerRef: string }) {
  const customer = release.customers.find((item) => item.customer_ref === customerRef);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<FeedbackRecord[]>([]);
  useEffect(() => {
    const timeoutId = window.setTimeout(() => setFeedback(readFeedback()), 0);
    return () => window.clearTimeout(timeoutId);
  }, []);

  if (!/^demo_[0-9a-f]{16}$/.test(customerRef) || !customer) {
    return (
      <section className="page-section compact-state">
        <div className="state-mark" aria-hidden="true">?</div>
        <div className="eyebrow">Demo sample</div>
        <h1>Customer not found</h1>
        <p className="lede">This reference is not present in release {release.meta.release_id}.</p>
        <Link className="button primary" href="/customers">Back to demo customers</Link>
      </section>
    );
  }
  const selected = customer.recommendations.find((item) => item.article_id === selectedId) ?? null;
  const localReviewCount = feedback.filter((item) => item.release_id === release.meta.release_id && item.customer_ref === customer.customer_ref).length;
  const contributingSources = new Set(customer.recommendations.flatMap((item) => item.source_evidence.map(({ source }) => source)));
  const sourcesOutsideTopTwelve = CANONICAL_SOURCES.filter((source) => !contributingSources.has(source));
  return (
    <section className="page-section workbench-section">
      <nav className="breadcrumbs" aria-label="Breadcrumb"><Link href="/customers">Demo customers</Link><span aria-hidden="true">/</span><span>{customer.display_label}</span></nav>
      <div className="page-heading-row">
        <div>
          <div className="eyebrow">Top 12 · {release.meta.ranking_version}</div>
          <h1>{customer.display_label}</h1>
          <p className="lede">Candidate slate ordered by equal-weight reciprocal rank fusion across the available sources.</p>
        </div>
        <div className="review-counter"><strong>{localReviewCount}</strong><span>reviewed locally</span></div>
      </div>
      <div className="workbench-notice"><strong>No trained ranker:</strong> position reflects baseline fusion only. Select any candidate to inspect its evidence and record a local judgment.</div>
      {sourcesOutsideTopTwelve.length > 0 ? (
        <div className="partial-notice" role="status"><strong>Partial top-12 source representation:</strong> {sourcesOutsideTopTwelve.map((source) => humanizeSource(source)).join(", ")} did not contribute to this customer’s visible slate. The five-source release itself is complete.</div>
      ) : null}
      <div className={`candidate-layout${selected ? " has-detail" : ""}`}>
        <div className="candidate-list" aria-label="Ordered recommendation candidates">
          {customer.recommendations.map((recommendation) => (
            <CandidateCard key={recommendation.article_id} recommendation={recommendation} active={recommendation.article_id === selectedId} onSelect={() => setSelectedId(recommendation.article_id)} />
          ))}
        </div>
        {selected ? <CandidateDetail release={release} customer={customer} recommendation={selected} feedback={feedback} onFeedback={setFeedback} close={() => setSelectedId(null)} /> : null}
      </div>
      <ReleaseStamp release={release} />
    </section>
  );
}

function Quality({ release }: { release: DemoRelease }) {
  const sources = new Map(release.diagnostics.source_metrics.map((metric) => [metric.source, metric]));
  return (
    <section className="page-section">
      <div className="page-heading-row">
        <div>
          <div className="eyebrow">Evidence before claims</div>
          <h1>Candidate quality</h1>
          <p className="lede">Diagnostics describe retrieval coverage on a historical validation cohort—not final recommendation quality or business impact.</p>
        </div>
        <ReleaseStamp release={release} />
      </div>
      <div className="metrics-grid quality-metrics">
        <Metric label="Candidate recall ceiling" value={formatPercent(release.diagnostics.candidate_recall_ceiling)} note="Union coverage of held-out purchases" />
        <Metric label="Mean candidate count" value={release.diagnostics.mean_candidate_count.toFixed(2)} note="Before top-12 fusion" />
        <Metric label="Union candidate rows" value={release.diagnostics.union_candidate_rows.toLocaleString()} note="Across the full cohort" />
        <Metric label="Metric scope" value={release.meta.cohort_customer_count.toLocaleString()} note="Historical validation customers" />
      </div>
      <section className="section-rule" aria-labelledby="sources-heading">
        <div className="section-heading"><div><div className="eyebrow">Five-source contract</div><h2 id="sources-heading">Source diagnostics</h2></div><p>All five inputs are required to create this release.</p></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th scope="col">Source</th><th scope="col">Candidate rows</th><th scope="col">Customers reached</th><th scope="col">Reach</th><th scope="col">Solo recall ceiling</th></tr></thead>
            <tbody>
              {CANONICAL_SOURCES.map((source) => {
                const metric = sources.get(source as SourceName);
                return metric ? (
                  <tr key={source}><th scope="row"><span className={`source-chip source-${source}`}>{humanizeSource(source as SourceName)}</span></th><td>{metric.candidate_rows.toLocaleString()}</td><td>{metric.reach_customers.toLocaleString()}</td><td>{formatPercent(metric.reach_fraction)}</td><td>{formatPercent(metric.solo_recall_ceiling)}</td></tr>
                ) : null;
              })}
            </tbody>
          </table>
        </div>
      </section>
      <section className="section-rule" aria-labelledby="definitions-heading">
        <div className="section-heading"><div><div className="eyebrow">Read the numbers correctly</div><h2 id="definitions-heading">Metric definitions</h2></div></div>
        <div className="definition-grid">
          {Object.entries(release.diagnostics.definitions).map(([key, definition]) => (
            <article key={key}><code>{key}</code><p>{definition}</p></article>
          ))}
        </div>
      </section>
      <section className="limitations section-rule" aria-labelledby="limits-heading">
        <div><div className="eyebrow">Known limitations</div><h2 id="limits-heading">What this release cannot establish</h2></div>
        <ul>
          <li>No trained or calibrated final ranker.</li>
          <li>No live catalog, inventory, price, or customer event stream.</li>
          <li>No click, purchase, uplift, or revenue experiment.</li>
          <li>No probability or confidence interpretation for fusion scores.</li>
        </ul>
        <p><strong>Scope:</strong> {release.diagnostics.scope}</p>
      </section>
    </section>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return <div className="empty-state" role="status"><span aria-hidden="true">○</span><h2>{title}</h2><p>{body}</p></div>;
}

function V1ReleaseExperience({ view, customerRef = "" }: { view: View; customerRef?: string }) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const load = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((value) => value + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    async function run() {
      try {
        const response = await fetch("/data/demo-release.json", { signal: controller.signal, cache: "no-store" });
        if (!response.ok) {
          setState({ status: "unavailable", message: `The release request returned ${response.status}.` });
          return;
        }
        let input: unknown;
        try {
          input = await response.json();
        } catch {
          setState({ status: "corrupt", message: "The file could not be parsed as JSON." });
          return;
        }
        try {
          setState({ status: "ready", release: validateRelease(input) });
        } catch (error) {
          const message = error instanceof Error ? error.message : "Unknown release validation error.";
          setState({ status: "invalid", message });
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({ status: "unavailable", message: "The release request did not complete." });
      }
    }
    void run();
    return () => controller.abort();
  }, [attempt]);

  if (state.status === "loading") return <LoadingState />;
  if (state.status !== "ready") return <FailureState kind={state.status} message={state.message} retry={load} />;
  if (view === "overview") return <Overview release={state.release} />;
  if (view === "customers") return <Customers release={state.release} />;
  if (view === "customer") return <CustomerWorkbench release={state.release} customerRef={customerRef} />;
  return <Quality release={state.release} />;
}

export function ReleaseExperience(props: {view: View; customerRef?: string; initialV2?:boolean}) {
  const v2=useSyncExternalStore(subscribeReplayMode,replayEnabled,()=>props.initialV2 || false);
  // Mode switches intentionally reload the document to reset both adapters.
  // eslint-disable-next-line @next/next/no-html-link-for-pages
  return v2 ? <ReplayExperience {...props}/> : <><div className="page-section mode-switch"><a href="/?mode=v2">Open V2 historical replay</a></div><V1ReleaseExperience {...props}/></>;
}
