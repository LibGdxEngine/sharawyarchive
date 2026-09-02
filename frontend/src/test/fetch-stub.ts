import { vi } from "vitest";

export interface StubbedResponse {
  status?: number;
  headers?: Record<string, string>;
  body?: unknown;
  /** Resolve only after this many milliseconds (timers may be fake). */
  delayMs?: number;
}

/**
 * A `fetch` that answers from a queue and honours `signal`: an aborted request
 * rejects with a DOMException named AbortError, as the real one does.
 */
export function stubFetch(responses: StubbedResponse[]) {
  const queue = [...responses];
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    calls.push({ url, init });
    const next = queue.shift() ?? { status: 500 };
    return new Promise<Response>((resolve, reject) => {
      const signal = init?.signal;
      const abort = () => reject(new DOMException("aborted", "AbortError"));
      if (signal?.aborted) {
        abort();
        return;
      }
      signal?.addEventListener("abort", abort);
      const finish = () => {
        signal?.removeEventListener("abort", abort);
        resolve(
          new Response(JSON.stringify(next.body ?? {}), {
            status: next.status ?? 200,
            headers: { "Content-Type": "application/json", ...(next.headers ?? {}) },
          }),
        );
      };
      if (next.delayMs) setTimeout(finish, next.delayMs);
      else finish();
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}
