import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { classifySmartError, fetchTransport } from "./smart-transport";
import { stubFetch } from "@/test/fetch-stub";

describe("classifySmartError", () => {
  it("maps API statuses to the copy the UI has", () => {
    expect(classifySmartError(new ApiError(429, "/x", 42))).toEqual({
      error: "rate_limited",
      retryAfter: 42,
    });
    expect(classifySmartError(new ApiError(503, "/x")).error).toBe("unavailable");
    expect(classifySmartError(new ApiError(404, "/x")).error).toBe("unavailable");
    expect(classifySmartError(new ApiError(400, "/x")).error).toBe("invalid");
    expect(classifySmartError(new ApiError(500, "/x")).error).toBe("network");
    expect(classifySmartError(new DOMException("x", "AbortError")).error).toBe("timeout");
    expect(classifySmartError(new TypeError("fetch failed")).error).toBe("network");
  });
});

describe("fetchTransport", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the question and yields one result", async () => {
    const { calls } = stubFetch([{ body: { query_id: "q1", status: "answered" } }]);
    const events = [];
    for await (const event of fetchTransport("سؤال", {
      signal: new AbortController().signal,
      filters: { surah: 2 },
    })) {
      events.push(event);
    }
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ type: "result", response: { query_id: "q1" } });
    expect(calls[0].url.endsWith("/search/smart/")).toBe(true);
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ question: "سؤال", filters: { surah: 2 } });
  });

  it("turns a failure into an error event with Retry-After", async () => {
    stubFetch([{ status: 429, headers: { "Retry-After": "7" }, body: { detail: "slow down" } }]);
    const events = [];
    for await (const event of fetchTransport("سؤال", { signal: new AbortController().signal })) {
      events.push(event);
    }
    expect(events).toEqual([{ type: "error", error: "rate_limited", retryAfter: 7 }]);
  });
});
