import { afterEach, describe, expect, it, vi } from "vitest";
import { parseSse, streamTransport, type SmartEvent } from "./smart-transport";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect<T>(iterable: AsyncIterable<T>): Promise<T[]> {
  const items: T[] = [];
  for await (const item of iterable) items.push(item);
  return items;
}

describe("parseSse", () => {
  it("reassembles messages split across chunks and skips comments", async () => {
    const messages = await collect(
      parseSse(
        streamOf([
          "event: stage\ndata: {\"stage\": \"retr",
          "ieve\"}\n\n: ping\n\nevent: result\r\ndata: {\"a\": 1}\r\ndata: \n\n",
          "data: tail",
        ]),
      ),
    );
    expect(messages).toEqual([
      { event: "stage", data: '{"stage": "retrieve"}' },
      { event: "result", data: '{"a": 1}\n' },
      { event: "message", data: "tail" },
    ]);
  });
});

describe("streamTransport", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function stubStream(body: string, headers: Record<string, string>, status = 200) {
    const fetchMock = vi.fn(async () => new Response(streamOf([body]), { status, headers }));
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("maps stage, passages and result events", async () => {
    const fetchMock = stubStream(
      [
        'event: stage\ndata: {"stage": "retrieve"}',
        'event: passages\ndata: {"passages": [{"passage_id": 7}]}',
        'event: bogus\ndata: {}',
        'event: stage\ndata: {"stage": "nonsense"}',
        'event: result\ndata: {"query_id": "q1", "status": "answered"}',
      ].join("\n\n") + "\n\n",
      { "Content-Type": "text/event-stream" },
    );

    const events = await collect(
      streamTransport("سؤال", { signal: new AbortController().signal, debug: true }),
    );

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).Accept).toBe("text/event-stream");
    expect(JSON.parse(String(init.body))).toEqual({ question: "سؤال", debug: true });
    expect(events).toEqual<SmartEvent[]>([
      { type: "stage", stage: "retrieve" },
      { type: "passages", passages: [{ passage_id: 7 } as never] },
      { type: "result", response: { query_id: "q1", status: "answered" } as never },
    ]);
  });

  it("falls back to a plain JSON answer when nothing streams", async () => {
    stubStream('{"query_id": "q2", "status": "partial"}', { "Content-Type": "application/json" });

    const events = await collect(streamTransport("س", { signal: new AbortController().signal }));

    expect(events).toEqual([{ type: "result", response: { query_id: "q2", status: "partial" } }]);
  });

  it("turns an HTTP failure into an error event", async () => {
    stubStream('{"detail": "off"}', { "Content-Type": "application/json" }, 503);

    const events = await collect(streamTransport("س", { signal: new AbortController().signal }));

    expect(events).toEqual([{ type: "error", error: "unavailable", retryAfter: null }]);
  });

  it("reports a stream that ended without a result", async () => {
    stubStream('event: stage\ndata: {"stage": "rerank"}\n\n', { "Content-Type": "text/event-stream" });

    const events = await collect(streamTransport("س", { signal: new AbortController().signal }));

    expect(events).toEqual([
      { type: "stage", stage: "rerank" },
      { type: "error", error: "network", retryAfter: null },
    ]);
  });
});
