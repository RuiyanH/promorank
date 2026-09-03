"use client";

import { parseFeedback, removeFeedback, upsertFeedback } from "./feedback-runtime.mjs";

export type FeedbackSignal = "relevant" | "not_relevant";

export interface FeedbackRecord {
  schema_version: "1.0.0";
  event_id: string;
  release_id: string;
  customer_ref: string;
  article_id: string;
  signal: FeedbackSignal;
  saved_at: string;
}

const STORAGE_KEY = "marketrank-feedback-v1";

export function readFeedback(): FeedbackRecord[] {
  if (typeof window === "undefined") return [];
  return parseFeedback(window.localStorage.getItem(STORAGE_KEY));
}

export function saveFeedback(
  current: FeedbackRecord[],
  identity: Pick<FeedbackRecord, "release_id" | "customer_ref" | "article_id">,
  signal: FeedbackSignal,
): FeedbackRecord[] {
  const next = upsertFeedback(current, identity, signal);
  if (next === current) return current;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  return next;
}

export function clearFeedback(
  current: FeedbackRecord[],
  identity: Pick<FeedbackRecord, "release_id" | "customer_ref" | "article_id">,
): FeedbackRecord[] {
  const next = removeFeedback(current, identity);
  if (next.length !== current.length) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  return next;
}
