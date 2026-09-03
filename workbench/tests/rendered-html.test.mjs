import assert from "node:assert/strict";
import test from "node:test";

async function render(path) {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${encodeURIComponent(path)}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(new Request(`http://localhost${path}`, { headers:{ accept:"text/html" } }), { ASSETS:{ fetch:async () => new Response("Not found",{ status:404 }) } }, { waitUntil(){}, passThroughOnException(){} });
}

for (const [path, title] of [["/", "MarketRank Workbench"], ["/customers", "Demo customers"], ["/customers/demo_0123456789abcdef", "Candidate review"], ["/quality", "Quality"]]) {
  test(`server renders ${path}`, async () => {
    const response = await render(path);
    assert.equal(response.status, 200);
    const html = await response.text();
    assert.match(html, new RegExp(`<title>${title}(?: · MarketRank Workbench)?</title>`, "i"));
    assert.match(html, /Candidate-only historical snapshot/);
    assert.match(html, /Baseline fusion orders retrieved items/);
    assert.match(html, /Skip to content/);
    assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Starter Project/);
  });
}
