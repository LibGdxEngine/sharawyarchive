/**
 * How a smart-search question reaches the API and how its answer comes back.
 *
 * `useSmartSearch` consumes a stream of {@link SmartEvent}s, whichever
 * transport produced them. Today there is one transport — a single POST that
 * yields one `result` (or one `error`) — and the shape is chosen so that a
 * streaming transport (server-sent `stage`/`passages`/`result` events) can
 * replace it without the components noticing.
 */

import { ApiError, smartSearch } from "@/lib/api";
import type { SmartFilters, SmartResponse } from "@/types/models";

export type SmartStage = "retrieve" | "rerank" | "generate";

export type SmartErrorKind =
  | "rate_limited"
  | "unavailable"
  | "invalid"
  | "timeout"
  | "network";

export type SmartEvent =
  | { type: "stage"; stage: SmartStage }
  | { type: "result"; response: SmartResponse }
  | { type: "error"; error: SmartErrorKind; retryAfter: number | null };

export interface TransportOptions {
  signal: AbortSignal;
  filters?: SmartFilters;
  debug?: boolean;
}

export type SmartTransport = (
  question: string,
  options: TransportOptions,
) => AsyncIterable<SmartEvent>;

/** What went wrong, in the terms the UI has copy for. */
export function classifySmartError(error: unknown): {
  error: SmartErrorKind;
  retryAfter: number | null;
} {
  if (error instanceof ApiError) {
    if (error.status === 429) return { error: "rate_limited", retryAfter: error.retryAfter };
    if (error.status === 404 || error.status === 503) {
      return { error: "unavailable", retryAfter: null };
    }
    if (error.status === 400) return { error: "invalid", retryAfter: null };
    return { error: "network", retryAfter: null };
  }
  if (error instanceof DOMException && error.name === "AbortError") {
    return { error: "timeout", retryAfter: null };
  }
  return { error: "network", retryAfter: null };
}

/** One POST, one event. */
export async function* fetchTransport(
  question: string,
  options: TransportOptions,
): AsyncGenerator<SmartEvent> {
  try {
    const response = await smartSearch(question, options);
    yield { type: "result", response };
  } catch (error) {
    yield { type: "error", ...classifySmartError(error) };
  }
}
