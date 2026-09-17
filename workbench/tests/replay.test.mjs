import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {validateRecommendations,validateCustomers,validateQuality,saveLocalReview,readLocalReviews,replayDateUrl} from "../lib/replay-runtime.mjs";

const golden=JSON.parse(readFileSync(new URL("../../tests/fixtures/contracts_v2/api-recommendations.json",import.meta.url)));
test("V2 accepts frozen contract and rejects hybrid, probability, and early dates",()=>{
  assert.equal(validateRecommendations(golden),golden);
  for(const mutate of [x=>x.schema_version="workbench-api.v1",x=>x.recommendations[0].probability=.2,x=>x.as_of="2020-07-15",x=>x.recommendations[0].ordering_score=Infinity,x=>x.customer_id="raw"]){
    const value=structuredClone(golden);mutate(value);assert.throws(()=>validateRecommendations(value));
  }
});
test("V2 customer pages reject restricted identity and malformed references",()=>{
  const page={schema_version:"workbench-customers.v2",release_id:"example",customers:[{customer_ref:golden.customer_ref,display_label:"Historical customer 00001"}],next_cursor:null};
  assert.equal(validateCustomers(page),page);
  page.customers[0].customer_id="raw";assert.throws(()=>validateCustomers(page));
});
test("V2 local review identity separates release and historical date",()=>{
  const values=new Map();globalThis.localStorage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
  saveLocalReview("release_a","2020-09-09",golden.customer_ref,"0000000001","relevant");
  saveLocalReview("release_a","2020-09-09",golden.customer_ref,"0000000001","not_relevant");
  saveLocalReview("release_a","2020-09-16",golden.customer_ref,"0000000001","relevant");
  assert.equal(Object.keys(JSON.parse(values.get("marketrank-reviews-v2"))).length,2);
  assert.equal(readLocalReviews("release_a","2020-09-09",golden.customer_ref)["0000000001"],"not_relevant");
  saveLocalReview("release_a","2020-09-09",golden.customer_ref,"0000000001",null);
  assert.deepEqual(readLocalReviews("release_a","2020-09-09",golden.customer_ref),{});
  assert.equal(readLocalReviews("release_a","2020-09-16",golden.customer_ref)["0000000001"],"relevant");
  delete globalThis.localStorage;
});

test("V2 quality rejects false-looking strings and inconsistent acceptance",()=>{
  const split={model:{active_day_end_to_end_ndcg_at_12:.05,candidate_recall_ceiling:.12,groups:12,customers:10},rrf:{active_day_end_to_end_ndcg_at_12:.03},bootstrap:{ci95:[.01,.03]},promotion_gate:{passed:true,failed_rules:[]}};
  const value={schema_version:"workbench-quality.v2",release_id:"example",status:"candidate",warning:"Historical only",provenance:{},quality:{schema_version:"ranker-evaluation.v2",quality_gate_passed:true,test:split,holdout:structuredClone(split)}};
  assert.equal(validateQuality(value),value);
  for(const mutate of [x=>x.quality.quality_gate_passed="false",x=>x.quality.test.promotion_gate.passed=false,x=>x.quality.test.model.customers=20,x=>x.status="promoted",x=>x.quality.test.model.active_day_end_to_end_ndcg_at_12=1.1]) {
    const changed=structuredClone(value);mutate(changed);assert.throws(()=>validateQuality(changed));
  }
});

test("V2 date links preserve route identity and survive reload without a saved mode",()=>{
  const current=`http://localhost:5173/customers/${golden.customer_ref}?as_of=2020-09-09#main-content`;
  const url=new URL(replayDateUrl(current,"release_a","2020-09-16"));
  assert.equal(url.pathname,`/customers/${golden.customer_ref}`);
  assert.equal(url.searchParams.get("mode"),"v2");
  assert.equal(url.searchParams.get("as_of"),"2020-09-16");
  assert.equal(url.searchParams.get("release"),"release_a");
  assert.equal(url.hash,"#main-content");
  assert.throws(()=>replayDateUrl(current,"release_a","2020-07-15"));
});
