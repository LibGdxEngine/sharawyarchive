"use client";

import { useEffect, useReducer } from "react";
import {
  fetchTransport,
  type SmartErrorKind,
  type SmartStage,
  type SmartTransport,
} from "@/lib/smart-transport";
import type { SmartFilters, SmartResponse } from "@/types/models";

/** Stage copy by elapsed time — the API does not stream yet, so this is a clock. */
export const STAGE_MESSAGES = [
  "يبحث في الأرشيف…",
  "يرتب المقاطع…",
  "يكتب الإجابة…",
] as const;
export const STAGE_AT_MS = [0, 4_000, 12_000] as const;
export const SLOW_AT_MS = 40_000;
export const CLIENT_TIMEOUT_MS = 60_000;

export interface SmartSearchState {
  phase: "idle" | "loading" | "ready" | "error";
  /** Index into {@link STAGE_MESSAGES}. */
  stage: 0 | 1 | 2;
  slow: boolean;
  response: SmartResponse | null;
  error: SmartErrorKind | null;
  retryAfter: number | null;
}

type Action =
  | { type: "reset" }
  | { type: "start" }
  | { type: "stage"; stage: 1 | 2 }
  | { type: "slow" }
  | { type: "result"; response: SmartResponse }
  | { type: "error"; error: SmartErrorKind; retryAfter: number | null };

const IDLE: SmartSearchState = {
  phase: "idle",
  stage: 0,
  slow: false,
  response: null,
  error: null,
  retryAfter: null,
};

export function reduce(state: SmartSearchState, action: Action): SmartSearchState {
  switch (action.type) {
    case "reset":
      return IDLE;
    case "start":
      return { ...IDLE, phase: "loading" };
    case "stage":
      return state.phase === "loading" ? { ...state, stage: action.stage } : state;
    case "slow":
      return state.phase === "loading" ? { ...state, slow: true } : state;
    case "result":
      // A degraded answer is a *ready* state: there are passages to show.
      return { ...IDLE, phase: "ready", response: action.response };
    case "error":
      return { ...IDLE, phase: "error", error: action.error, retryAfter: action.retryAfter };
  }
}

const STAGE_INDEX: Record<SmartStage, 1 | 2> = {
  retrieve: 1,
  rerank: 1,
  generate: 2,
};

export interface UseSmartSearchOptions {
  filters?: SmartFilters;
  debug?: boolean;
  transport?: SmartTransport;
}

/**
 * Ask `question` and follow the answer through loading, ready and error.
 *
 * One request per distinct question: a new question aborts the previous
 * request. The stage message advances on a timer (the API answers in one
 * piece), `slow` flips at 40 s, and the client gives up at 60 s — the server's
 * own budget is 40 s, so anything past that is a stuck connection.
 */
export function useSmartSearch(
  question: string,
  { filters, debug = false, transport = fetchTransport }: UseSmartSearchOptions = {},
): SmartSearchState {
  const [state, dispatch] = useReducer(reduce, IDLE);
  const filtersKey = JSON.stringify(filters ?? null);

  useEffect(() => {
    const trimmed = question.trim();
    if (trimmed === "") {
      dispatch({ type: "reset" });
      return;
    }
    const controller = new AbortController();
    let timedOut = false;
    dispatch({ type: "start" });
    const timers = [
      setTimeout(() => dispatch({ type: "stage", stage: 1 }), STAGE_AT_MS[1]),
      setTimeout(() => dispatch({ type: "stage", stage: 2 }), STAGE_AT_MS[2]),
      setTimeout(() => dispatch({ type: "slow" }), SLOW_AT_MS),
      setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, CLIENT_TIMEOUT_MS),
    ];
    const parsedFilters = JSON.parse(filtersKey) as SmartFilters | null;

    void (async () => {
      try {
        for await (const event of transport(trimmed, {
          signal: controller.signal,
          filters: parsedFilters ?? undefined,
          debug,
        })) {
          if (controller.signal.aborted && !timedOut) return;
          if (event.type === "stage") {
            dispatch({ type: "stage", stage: STAGE_INDEX[event.stage] });
          } else if (event.type === "result") {
            dispatch({ type: "result", response: event.response });
          } else if (timedOut && event.error === "timeout") {
            dispatch({ type: "error", error: "timeout", retryAfter: null });
          } else if (!controller.signal.aborted || timedOut) {
            dispatch({ type: "error", error: event.error, retryAfter: event.retryAfter });
          }
        }
      } catch {
        if (controller.signal.aborted && !timedOut) return;
        dispatch({ type: "error", error: timedOut ? "timeout" : "network", retryAfter: null });
      }
    })();

    return () => {
      controller.abort();
      for (const timer of timers) clearTimeout(timer);
    };
  }, [question, filtersKey, debug, transport]);

  return state;
}
