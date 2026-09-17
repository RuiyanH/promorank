import type { FeedbackRecord, FeedbackSignal } from "./feedback";
export function isFeedbackRecord(value: unknown): value is FeedbackRecord;
export function parseFeedback(serialized: string | null): FeedbackRecord[];
export function upsertFeedback(
  current: FeedbackRecord[],
  identity: Pick<FeedbackRecord, "release_id" | "customer_ref" | "article_id">,
  signal: FeedbackSignal,
  now?: () => string,
  createEventId?: () => string,
): FeedbackRecord[];
export function removeFeedback(
  current: FeedbackRecord[],
  identity: Pick<FeedbackRecord, "release_id" | "customer_ref" | "article_id">,
): FeedbackRecord[];
