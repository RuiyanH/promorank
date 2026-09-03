import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { ReleaseValidationError, validateRelease } from "../lib/release-runtime.mjs";
import { makeReleaseFixture } from "./fixtures/release.fixture.mjs";

function clone(value) { return structuredClone(value); }

test("accepts the small schema-conformant test fixture", () => {
  const release = validateRelease(makeReleaseFixture());
  assert.equal(release.customers.length, 1);
  assert.equal(release.customers[0].recommendations.length, 12);
  assert.equal(release.meta.ranking_mode, "baseline_fusion");
});

test("accepts the generated historical release", async () => {
  const text = await readFile(new URL("../public/data/demo-release.json", import.meta.url), "utf8");
  const release = validateRelease(JSON.parse(text));
  assert.equal(release.meta.provenance_status, "backfilled");
  assert.equal(release.meta.demo_customer_count, release.customers.length);
  assert.equal(release.diagnostics.source_metrics.length, 5);
});

test("rejects unknown fields, raw identifiers, duplicate items, and incomplete source metrics", () => {
  const cases = [];
  const unknown = clone(makeReleaseFixture()); unknown.meta.live = true; cases.push(unknown);
  const rawId = clone(makeReleaseFixture()); rawId.customers[0].customer_id = "raw"; cases.push(rawId);
  const duplicate = clone(makeReleaseFixture()); duplicate.customers[0].recommendations[1].article_id = duplicate.customers[0].recommendations[0].article_id; cases.push(duplicate);
  const incomplete = clone(makeReleaseFixture()); incomplete.diagnostics.source_metrics.pop(); cases.push(incomplete);
  for (const candidate of cases) assert.throws(() => validateRelease(candidate), ReleaseValidationError);
});

test("rejects a zero fusion score because it is an ordering contribution", () => {
  const fixture = clone(makeReleaseFixture());
  fixture.customers[0].recommendations[0].fusion_score = 0;
  assert.throws(() => validateRelease(fixture), /fusion_score/);
});
