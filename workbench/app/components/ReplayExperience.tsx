"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { requestReplay, validateCustomers, validateRecommendations, validateReleases, validateQuality, saveLocalReview, type CustomerPage, type V2Recommendations } from "@/lib/replay-runtime.mjs";

interface Release {release_id:string;status:string;dates:string[];customer_count:number;warning:string;model_available_after:string;calibrator_available_after:string}
type View = "overview" | "customers" | "customer" | "quality";

interface EvaluationSplit {
  model:{active_day_end_to_end_ndcg_at_12:number;candidate_recall_ceiling:number;groups:number;customers:number};
  rrf:{active_day_end_to_end_ndcg_at_12:number};
  bootstrap:{ci95:number[]};promotion_gate:{passed:boolean;failed_rules:string[]};
}

function EvaluationEvidence({value}:{value:Record<string,unknown>}) {
  const report=value.quality as {schema_version?:string;quality_gate_passed?:boolean;test?:EvaluationSplit;holdout?:EvaluationSplit};
  if(report?.schema_version!=="ranker-evaluation.v2" || !report.test || !report.holdout) return <p role="status">Evaluation details are unavailable for this release.</p>;
  return <div className="replay-quality"><h2>{report.quality_gate_passed?"Offline quality gates passed":"Candidate retained · promotion gates not passed"}</h2>
    <p>Independent release review and the five-person usability study are still required. Passing an offline comparison does not establish business impact.</p>
    <div className="table-scroll"><table><caption>Trained ranker versus identical-candidate RRF · end-to-end NDCG@12</caption><thead><tr><th scope="col">Period</th><th scope="col">Ranker</th><th scope="col">RRF baseline</th><th scope="col">Relative change</th><th scope="col">Gate</th></tr></thead><tbody>
      {(["test","holdout"] as const).map(name=>{const row=report[name]!;const model=row.model.active_day_end_to_end_ndcg_at_12;const base=row.rrf.active_day_end_to_end_ndcg_at_12;return <tr key={name}><th scope="row">{name==="test"?"Test · Sep 9–15":"Holdout · Sep 16–22"}</th><td>{model.toFixed(4)}</td><td>{base.toFixed(4)}</td><td>{base?`${((model/base-1)*100).toFixed(1)}%`:"Not defined"}</td><td>{row.promotion_gate.passed?"Passed":"Not passed"}</td></tr>;})}
    </tbody></table></div>
    {(["test","holdout"] as const).map(name=>{const row=report[name]!;return <section key={name}><h3>{name==="test"?"Test evidence":"Holdout evidence"}</h3><p>{row.model.groups.toLocaleString()} active customer-days · {row.model.customers.toLocaleString()} customers · candidate recall ceiling {(row.model.candidate_recall_ceiling*100).toFixed(1)}%.</p><p>95% paired customer-cluster interval for absolute NDCG change: {row.bootstrap.ci95.map(x=>x.toFixed(4)).join(" to ")}.</p>{!row.promotion_gate.passed&&<p className="scope-note">Unmet checks: {row.promotion_gate.failed_rules.map(x=>x.replaceAll("_"," ")).join(", ")}.</p>}</section>;})}
    <details><summary>Artifact versions and complete offline diagnostics</summary><pre>{JSON.stringify(value,null,2)}</pre></details>
  </div>;
}

export function ReplayExperience({view,customerRef=""}:{view:View;customerRef?:string}) {
  const [releases,setReleases] = useState<Release[]>([]);
  const [releaseId,setReleaseId] = useState("");
  const [day,setDay] = useState("");
  const [query,setQuery] = useState("");
  const [submittedQuery,setSubmittedQuery] = useState("");
  const [cursor,setCursor] = useState<string|null>(null);
  const [page,setPage] = useState<CustomerPage|null>(null);
  const [items,setItems] = useState<V2Recommendations|null>(null);
  const [quality,setQuality] = useState<Record<string,unknown>|null>(null);
  const [error,setError] = useState("");
  const [busy,setBusy] = useState(true);
  const [attempt,setAttempt] = useState(0);
  const [reviewMessage,setReviewMessage] = useState("");
  const selected = releases.find(release => release.release_id===releaseId);

  useEffect(()=> {
    const controller = new AbortController();
    const timer = setTimeout(()=>controller.abort(),10000);
    requestReplay("/api/v2/releases",controller.signal).then(raw=>{
      const value=validateReleases(raw);
      const params=new URLSearchParams(window.location.search);
      const chosen=value.releases.find(r=>r.release_id===params.get("release")) || value.releases[0];
      const requestedDay=params.get("as_of");
      if(requestedDay && !chosen.dates.includes(requestedDay)) throw new Error("Select an approved historical replay date.");
      setReleases(value.releases);setReleaseId(chosen.release_id);setDay(requestedDay || chosen.dates[0]);setError("");
    }).catch(e=>{setError(e.name==="AbortError"?"The service took too long to respond.":e.message);setBusy(false);}).finally(()=>clearTimeout(timer));
    return ()=>{clearTimeout(timer);controller.abort();};
  },[attempt]);

  useEffect(()=>{
    if(!releaseId || !day) return;
    const controller = new AbortController();
    let active=true;
    const timer=setTimeout(()=>controller.abort(),10000);
    async function load() {
      setBusy(true);setError("");setItems(null);setPage(null);setQuality(null);
      try {
        const prefix=`/api/v2/releases/${encodeURIComponent(releaseId)}`;
        if(view==="customer") {
          const result=validateRecommendations(await requestReplay(`${prefix}/customers/${encodeURIComponent(customerRef)}/recommendations?as_of=${day}`,controller.signal));
          if(result.release_id!==releaseId || result.as_of!==day || result.customer_ref!==customerRef) throw new Error("The response does not match the requested historical record.");
          if(active)setItems(result);
        } else if(view==="quality") {
          const result=validateQuality(await requestReplay(`${prefix}/quality`,controller.signal));
          if(result.schema_version!=="workbench-quality.v2" || result.release_id!==releaseId) throw new Error("Quality response failed validation.");
          if(active)setQuality(result);
        } else {
          const params=new URLSearchParams({limit:"24",q:submittedQuery});
          if(cursor)params.set("cursor",cursor);
          const result=validateCustomers(await requestReplay(`${prefix}/customers?${params}`,controller.signal));
          if(result.release_id!==releaseId)throw new Error("Customer page belongs to another release.");
          if(active)setPage(result);
        }
      }catch(e){if(active)setError(e instanceof Error?e.message:"The historical request failed.");}
      finally{clearTimeout(timer);if(active)setBusy(false);}
    }
    void load();return ()=>{active=false;clearTimeout(timer);controller.abort();};
  },[releaseId,day,view,customerRef,cursor,submittedQuery,attempt]);

  function review(article:string,signal:"relevant"|"not_relevant"){
    try {saveLocalReview(releaseId,day,customerRef,article,signal);setReviewMessage(`Saved ${signal.replaceAll("_"," ")} for article ${article}. This stays in your browser and is excluded from training.`);}
    catch{setReviewMessage("Browser storage is unavailable; the review could not be saved.");}
  }

  return <section className="page-section replay-section">
    <div className="page-heading-row"><div><div className="eyebrow">Historical replay · V2</div>
      <h1>{view==="customer"?"Inspect the ranked shortlist":view==="quality"?"Offline evaluation": "Explore historical recommendations"}</h1>
      <p className="lede">{selected?`${selected.customer_count.toLocaleString()} customers in the fixed historical evaluation cohort.`:"Connecting to the local historical replay service."}</p></div>
      {/* A document reload intentionally resets the selected API adapter. */}
      {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
      <a className="button secondary" href="/?mode=v1">View V1 baseline</a></div>
    {selected && <><div className="replay-controls">
      <label>Release<select value={releaseId} onChange={e=>{const r=releases.find(x=>x.release_id===e.target.value)!;setReleaseId(r.release_id);setDay(r.dates[0]);setCursor(null);}}>{releases.map(r=><option key={r.release_id}>{r.release_id}</option>)}</select></label>
      <label>Replay date<select value={day} onChange={e=>setDay(e.target.value)}>{selected.dates.map(d=><option key={d}>{d}</option>)}</select></label>
      <div className="replay-status"><strong>{selected.status==="candidate"?"Candidate release · evaluation pending or gate not passed":"Verified release"}</strong><span>Trained ranker · ordering scores only</span></div>
    </div><p className="scope-note">{selected.warning}</p></>}
    {error && <div role="alert" className="empty-state"><h2>Replay unavailable</h2><p>{error}</p><button className="button primary" onClick={()=>setAttempt(x=>x+1)}>Retry connection</button></div>}
    {busy && <p role="status" aria-live="polite">Loading validated historical records…</p>}
    {!busy && !error && page && <>
      <form className="search-box" onSubmit={e=>{e.preventDefault();setCursor(null);setSubmittedQuery(query);}}><label htmlFor="replay-search">Find a historical label or reference</label><input id="replay-search" type="search" value={query} maxLength={100} onChange={e=>setQuery(e.target.value)} placeholder="Historical customer 00001"/><button className="button primary" type="submit">Search</button></form>
      {!page.customers.length && <div className="empty-state" role="status"><h2>No matching customer</h2><p>Try a different historical label or opaque reference.</p></div>}
      <div className="customer-grid">{page.customers.map(customer=><Link className="customer-card" key={customer.customer_ref} href={`/customers/${customer.customer_ref}?mode=v2&as_of=${day}&release=${releaseId}`}><div><h2>{customer.display_label}</h2><p>Inspect top 12 and contributing sources</p><code>{customer.customer_ref}</code></div></Link>)}</div>
      <div className="button-row">{cursor&&<button className="button secondary" onClick={()=>setCursor(null)}>First page</button>}{page.next_cursor&&<button className="button primary" onClick={()=>setCursor(page.next_cursor)}>Next customers</button>}</div>
    </>}
    {!busy && !error && items && <><p className="scope-note">{items.customer_ref} · {items.as_of}. Article details are static snapshot attributes.</p>
      <div className="replay-items">{items.recommendations.map(item=><article className="replay-item" key={item.article_id}><span className="customer-number">{item.position.toString().padStart(2,"0")}</span><div><h2>{item.article_metadata.product_type_name || "Article details unavailable"}</h2><p>Article {item.article_id}</p><div className="source-tags">{item.source_evidence.map(source=><span key={source.source}>{source.display_name.replaceAll("_"," ")} #{source.source_rank}</span>)}</div><p className="scope-note">Ordering score {item.ordering_score.toFixed(4)}</p><div className="button-row"><button className="button secondary" onClick={()=>review(item.article_id,"relevant")}>Relevant</button><button className="button secondary" onClick={()=>review(item.article_id,"not_relevant")}>Not relevant</button></div></div></article>)}</div><p role="status" aria-live="polite">{reviewMessage}</p><p className="scope-note">Reviews remain in this browser and are excluded from model training.</p></>}
    {!busy && !error && quality && <><p className="lede">Evaluation is conditional on an observed purchase day. End-to-end metrics retain groups whose purchases retrieval missed. RRF uses the same candidates as the trained ranker.</p><EvaluationEvidence value={quality}/></>}
  </section>;
}
