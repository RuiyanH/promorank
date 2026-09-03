import assert from "node:assert/strict";
import test from "node:test";
import { parseFeedback, removeFeedback, upsertFeedback } from "../lib/feedback-runtime.mjs";

const identity = { release_id:"fixture-release-v1", customer_ref:"demo_0123456789abcdef", article_id:"1000000000" };
const firstEventId = "11111111-1111-4111-8111-111111111111";
const secondEventId = "22222222-2222-4222-8222-222222222222";

test("feedback upsert is idempotent for the same structured signal", () => {
  const first = upsertFeedback([], identity, "relevant", () => "2026-01-01T00:00:00.000Z", () => firstEventId);
  const second = upsertFeedback(first, identity, "relevant", () => "2027-01-01T00:00:00.000Z", () => secondEventId);
  assert.strictEqual(second, first);
  assert.equal(second.length, 1);
  assert.equal(second[0].event_id, firstEventId);
  assert.deepEqual(Object.keys(second[0]).sort(), ["article_id", "customer_ref", "event_id", "release_id", "saved_at", "schema_version", "signal"]);
});

test("feedback changes in place, clears by identity, and ignores malformed storage", () => {
  const first = upsertFeedback([], identity, "relevant", () => "2026-01-01T00:00:00.000Z", () => firstEventId);
  const changed = upsertFeedback(first, identity, "not_relevant", () => "2026-01-02T00:00:00.000Z", () => secondEventId);
  assert.equal(changed.length, 1);
  assert.equal(changed[0].signal, "not_relevant");
  assert.equal(changed[0].event_id, secondEventId);
  assert.deepEqual(removeFeedback(changed, identity), []);
  assert.deepEqual(parseFeedback("not json"), []);
});

test("exact duplicate event IDs collapse idempotently", () => {
  const [event] = upsertFeedback([], identity, "relevant", () => "2026-01-01T00:00:00.000Z", () => firstEventId);
  const parsed = parseFeedback(JSON.stringify([event, structuredClone(event)]));
  assert.deepEqual(parsed, [event]);
});

test("conflicting payloads for one event ID are quarantined deterministically", () => {
  const [event] = upsertFeedback([], identity, "relevant", () => "2026-01-01T00:00:00.000Z", () => firstEventId);
  const conflict = { ...event, signal:"not_relevant" };
  assert.deepEqual(parseFeedback(JSON.stringify([event, conflict])), []);
  assert.deepEqual(parseFeedback(JSON.stringify([conflict, event])), []);
});

test("latest distinct event wins for one item with a stable tie-break", () => {
  const [older] = upsertFeedback([], identity, "relevant", () => "2026-01-01T00:00:00.000Z", () => firstEventId);
  const [newer] = upsertFeedback([], identity, "not_relevant", () => "2026-01-02T00:00:00.000Z", () => secondEventId);
  assert.deepEqual(parseFeedback(JSON.stringify([newer, older])), [newer]);
});

test("feedback parser rejects invalid UUIDs and extra free-text fields", () => {
  const [event] = upsertFeedback([], identity, "relevant", () => "2026-01-01T00:00:00.000Z", () => firstEventId);
  assert.deepEqual(parseFeedback(JSON.stringify([{ ...event, event_id:"not-a-uuid" }])), []);
  assert.deepEqual(parseFeedback(JSON.stringify([{ ...event, comment:"free text" }])), []);
});
