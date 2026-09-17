import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {validateRecommendations,validateCustomers,saveLocalReview} from "../lib/replay-runtime.mjs";

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
  delete globalThis.localStorage;
});
