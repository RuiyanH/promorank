const customerRefPattern = /^demo_[0-9a-f]{16}$/;
const articleIdPattern = /^\d{10}$/;
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const feedbackKeys = ["article_id", "customer_ref", "event_id", "release_id", "saved_at", "schema_version", "signal"];

function feedbackSignature(record) {
  return JSON.stringify(feedbackKeys.map((key) => record[key]));
}

export function isFeedbackRecord(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  return (
    Object.keys(value).sort().join("|") === feedbackKeys.join("|") &&
    value.schema_version === "1.0.0" &&
    uuidPattern.test(String(value.event_id)) &&
    typeof value.release_id === "string" &&
    value.release_id.length > 0 &&
    customerRefPattern.test(String(value.customer_ref)) &&
    articleIdPattern.test(String(value.article_id)) &&
    (value.signal === "relevant" || value.signal === "not_relevant") &&
    typeof value.saved_at === "string" &&
    Number.isFinite(Date.parse(value.saved_at))
  );
}

export function parseFeedback(serialized) {
  try {
    const parsed = JSON.parse(serialized ?? "[]");
    if (!Array.isArray(parsed)) return [];
    const valid = parsed.filter(isFeedbackRecord);
    const byEventId = new Map();
    const conflictingEventIds = new Set();
    for (const record of valid) {
      const previous = byEventId.get(record.event_id);
      if (!previous) {
        byEventId.set(record.event_id, record);
      } else if (feedbackSignature(previous) !== feedbackSignature(record)) {
        conflictingEventIds.add(record.event_id);
      }
    }

    // A reused event ID with a different payload is ambiguous, so quarantine
    // every copy. Exact retries collapse to one event. This is order-independent.
    const safeEvents = [...byEventId.values()].filter((record) => !conflictingEventIds.has(record.event_id));
    const latestByItem = new Map();
    for (const record of safeEvents) {
      const itemKey = `${record.release_id}\u0000${record.customer_ref}\u0000${record.article_id}`;
      const previous = latestByItem.get(itemKey);
      if (!previous || record.saved_at > previous.saved_at || (record.saved_at === previous.saved_at && record.event_id > previous.event_id)) {
        latestByItem.set(itemKey, record);
      }
    }
    return [...latestByItem.values()].sort((left, right) => left.event_id.localeCompare(right.event_id));
  } catch {
    return [];
  }
}

export function upsertFeedback(
  current,
  identity,
  signal,
  now = () => new Date().toISOString(),
  createEventId = () => globalThis.crypto.randomUUID(),
) {
  if (signal !== "relevant" && signal !== "not_relevant") throw new TypeError("Unsupported feedback signal");
  if (!identity || typeof identity.release_id !== "string" || !customerRefPattern.test(identity.customer_ref) || !articleIdPattern.test(identity.article_id)) {
    throw new TypeError("Invalid feedback identity");
  }
  const index = current.findIndex(
    (item) => item.release_id === identity.release_id && item.customer_ref === identity.customer_ref && item.article_id === identity.article_id,
  );
  if (index >= 0 && current[index].signal === signal) return current;
  const eventId = createEventId();
  if (!uuidPattern.test(eventId)) throw new TypeError("Feedback event ID must be a UUID");
  if (current.some((item) => item.event_id === eventId)) throw new TypeError("Feedback event ID collision");
  const nextRecord = { schema_version:"1.0.0", event_id:eventId, ...identity, signal, saved_at:now() };
  return index >= 0 ? current.map((item, itemIndex) => itemIndex === index ? nextRecord : item) : [...current,nextRecord];
}

export function removeFeedback(current, identity) {
  return current.filter(
    (item) => item.release_id !== identity.release_id || item.customer_ref !== identity.customer_ref || item.article_id !== identity.article_id,
  );
}
