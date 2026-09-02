/**
 * How a smart-search question reaches the API and how its answer comes back.
 *
 * `useSmartSearch` consumes a stream of {@link SmartEvent}s, whichever
 * transport produced them. Today there is one transport — a single POST that
 * yields one `result` (or one `error`) — and the shape is chosen so that a
 * streaming transport (server-sent `stage`/`passages`/`result` events) can
 * replace it without the components noticing.
 */

import { ApiError, apiUrl, parseRetryAfter, smartSearch } from "@/lib/api";
import type { SmartFilters, SmartPassage, SmartResponse } from "@/types/models";

export type SmartStage = "retrieve" | "rerank" | "generate";

export type SmartErrorKind =
  | "rate_limited"
  | "unavailable"
  | "invalid"
  | "timeout"
  | "network";

export type SmartEvent =
  | { type: "stage"; stage: SmartStage }
  | { type: "passages"; passages: SmartPassage[] }
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

// ---------------------------------------------------------------------------
// Streaming (server-sent events)
// ---------------------------------------------------------------------------

export interface SseMessage {
  event: string;
  data: string;
}

/**
 * Parse a `text/event-stream` body. Handles messages split across chunks,
 * multi-line `data:`, comment lines (`: ping`) and both newline flavours.
 */
export async function* parseSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const message = parseBlock(block);
        if (message !== null) yield message;
        boundary = buffer.indexOf("\n\n");
      }
      if (done) {
        const tail = parseBlock(buffer);
        if (tail !== null) yield tail;
        return;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseBlock(block: string): SseMessage | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length === 0 ? null : { event, data: data.join("\n") };
}

const STAGES: SmartStage[] = ["retrieve", "rerank", "generate"];

function toEvent(message: SseMessage): SmartEvent | null {
  let payload: unknown;
  try {
    payload = JSON.parse(message.data);
  } catch {
    return null;
  }
  if (typeof payload !== "object" || payload === null) return null;
  const body = payload as Record<string, unknown>;
  switch (message.event) {
    case "stage": {
      const stage = body.stage;
      return typeof stage === "string" && (STAGES as string[]).includes(stage)
        ? { type: "stage", stage: stage as SmartStage }
        : null;
    }
    case "passages":
      return Array.isArray(body.passages)
        ? { type: "passages", passages: body.passages as SmartPassage[] }
        : null;
    case "result":
      return { type: "result", response: body as unknown as SmartResponse };
    case "error":
      return { type: "error", error: "network", retryAfter: null };
    default:
      return null;
  }
}

/**
 * The same POST with `Accept: text/event-stream`: stages and passages arrive
 * as the server produces them, the verified answer last. A server (or proxy)
 * that answers in one piece — plain JSON — is handled like the fetch transport,
 * so the flag can be on before the edge is confirmed to pass streams through.
 */
export async function* streamTransport(
  question: string,
  { signal, filters, debug }: TransportOptions,
): AsyncGenerator<SmartEvent> {
  const body: Record<string, unknown> = { question };
  if (filters !== undefined) body.filters = filters;
  if (debug) body.debug = true;
  let res: Response;
  try {
    res = await fetch(apiUrl("/search/smart/"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    yield { type: "error", ...classifySmartError(error) };
    return;
  }
  if (!res.ok) {
    yield {
      type: "error",
      ...classifySmartError(new ApiError(res.status, "/search/smart/", parseRetryAfter(res))),
    };
    return;
  }
  const contentType = res.headers.get("Content-Type") ?? "";
  if (!contentType.includes("text/event-stream") || res.body === null) {
    yield { type: "result", response: (await res.json()) as SmartResponse };
    return;
  }
  let sawResult = false;
  try {
    for await (const message of parseSse(res.body)) {
      const event = toEvent(message);
      if (event === null) continue;
      if (event.type === "result" || event.type === "error") sawResult = true;
      yield event;
    }
  } catch (error) {
    yield { type: "error", ...classifySmartError(error) };
    return;
  }
  if (!sawResult) yield { type: "error", error: "network", retryAfter: null };
}

/** Streaming when the build opted in (`NEXT_PUBLIC_SMART_STREAMING=1`), else one POST. */
export const defaultTransport: SmartTransport =
  process.env.NEXT_PUBLIC_SMART_STREAMING === "1" ? streamTransport : fetchTransport;
