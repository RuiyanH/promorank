import assert from "node:assert/strict";
import test from "node:test";

for(const path of ["/","/customers","/customers/v2c_0123456789abcdef01234567","/quality"]) {
  test(`V2 direct navigation server-renders correct scope at ${path}`,async()=>{
    const workerUrl=new URL("../dist/server/index.js",import.meta.url);
    workerUrl.searchParams.set("test",`v2-${process.pid}-${encodeURIComponent(path)}`);
    const {default:worker}=await import(workerUrl.href);
    const response=await worker.fetch(new Request(`http://localhost${path}?mode=v2`,{headers:{accept:"text/html"}}),{ASSETS:{fetch:async()=>new Response("Not found",{status:404})}},{waitUntil(){},passThroughOnException(){}});
    assert.equal(response.status,200);
    const html=await response.text();
    assert.match(html,/Trained ranking orders historical candidates/);
    assert.match(html,/Historical replay/);
    assert.match(html,/View V1 baseline/);
    assert.doesNotMatch(html,/Candidate-only historical snapshot/);
    assert.doesNotMatch(html,/there is no trained ranker/);
  });
}
