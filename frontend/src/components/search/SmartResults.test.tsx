import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SmartResults from "./SmartResults";
import { CLIENT_TIMEOUT_MS, STAGE_AT_MS, STAGE_MESSAGES } from "./useSmartSearch";
import type { SmartEvent, SmartTransport } from "@/lib/smart-transport";
import type { SmartResponse } from "@/types/models";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/search",
  useSearchParams: () => new URLSearchParams(),
}));

const RESPONSE: SmartResponse = {
  query_id: "11111111-1111-1111-1111-111111111111",
  mode: "smart",
  status: "answered",
  answer_md: "قال الشيخ صراحةً إن الصبر أول الأمر [1]. واستشهد بقوله تعالى [[ayah:2:255]] [1].",
  citations: [
    {
      n: 1,
      passage_id: 7,
      chunk_id: 3,
      segment_id: 42,
      segment_title: "خواطر البقرة",
      surah: 2,
      ayah_start: 1,
      ayah_end: 10,
      start_ms: 30000,
      end_ms: 32900,
      quote_display: "الصَّبْرُ عِنْدَ الصَّدْمَةِ",
      listen_url: "/listen/42?t=30000",
    },
  ],
  passages: [
    {
      passage_id: 7,
      chunk_id: null,
      segment_id: 42,
      segment_title: "خواطر البقرة",
      surah: 2,
      ayah_start: 1,
      ayah_end: 10,
      start_ms: 0,
      end_ms: 90000,
      excerpt_display: "الإيمان بالله وحده لا شريك له …",
      score: 3,
    },
  ],
  ayah_refs: [
    { surah: 2, ayah: 255, surah_name_ar: "البقرة", text_uthmani: "ٱللَّهُ لَآ إِلَـٰهَ إِلَّا هُوَ" },
  ],
  followups: ["ما فضل الصبر؟"],
  cache_hit: false,
  debug: null,
};

/** A transport that yields the given events after `delayMs` (fake timers). */
function transportOf(events: SmartEvent[], delayMs = 0): SmartTransport & { calls: AbortSignal[] } {
  const calls: AbortSignal[] = [];
  const transport = async function* (_question: string, { signal }: { signal: AbortSignal }) {
    calls.push(signal);
    if (delayMs > 0) {
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(resolve, delayMs);
        signal.addEventListener("abort", () => {
          clearTimeout(timer);
          reject(new DOMException("aborted", "AbortError"));
        });
      });
    }
    for (const event of events) yield event;
  };
  return Object.assign(transport, { calls });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("SmartResults", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    push.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("renders the answer with chips, the canonical verse, citations and passages", async () => {
    render(
      <SmartResults
        question="ما رأي الشيخ في الصبر"
        kind={undefined}
        transport={transportOf([{ type: "result", response: RESPONSE }])}
      />,
    );
    await flush();

    expect(screen.getByText(/قال الشيخ صراحةً/)).toBeTruthy();
    expect(screen.queryByText(/\[\[ayah/)).toBeNull();
    expect(screen.getByText(/ٱللَّهُ لَآ إِلَـٰهَ/)).toBeTruthy();
    expect(screen.getByText("النص القرآني الموثّق — ليس من التفريغ الآلي")).toBeTruthy();
    expect(screen.getByText("«الصَّبْرُ عِنْدَ الصَّدْمَةِ»")).toBeTruthy();
    expect(screen.getAllByText("نص آلي").length).toBeGreaterThan(0);
    expect(screen.getByText("الاستماع في سياقه").getAttribute("href")).toBe("/listen/42?t=30000");
    expect(screen.getByText("إجابة مولّدة آليًا")).toBeTruthy();

    const chips = screen.getAllByRole("button", { name: "المرجع 1" });
    expect(chips).toHaveLength(2);
    expect(chips[0].getAttribute("aria-controls")).toBe("cite-1");
    const card = document.getElementById("cite-1")!;
    card.scrollIntoView = vi.fn();
    fireEvent.click(chips[0]);
    expect(card.getAttribute("data-active")).toBe("true");
    expect(document.activeElement).toBe(card);

    fireEvent.click(screen.getByRole("button", { name: "ما فضل الصبر؟" }));
    expect(push).toHaveBeenCalledWith("/search?q=%D9%85%D8%A7+%D9%81%D8%B6%D9%84+%D8%A7%D9%84%D8%B5%D8%A8%D8%B1%D8%9F&mode=smart");
  });

  it("shows the passages with the marker when the answer is degraded", async () => {
    const degraded: SmartResponse = {
      ...RESPONSE,
      status: "degraded",
      answer_md: null,
      citations: [],
      ayah_refs: [],
      followups: [],
    };
    render(
      <SmartResults
        question="سؤال"
        kind="khawatir"
        transport={transportOf([{ type: "result", response: degraded }])}
      />,
    );
    await flush();

    expect(screen.getByText("تعذّر توليد الإجابة الآن، وهذه أقرب المقاطع لسؤالك.")).toBeTruthy();
    expect(screen.getByText(/الإيمان بالله وحده/)).toBeTruthy();
    expect(screen.getByText("نتائج من التفريغ الآلي — قد تحتوي على أخطاء")).toBeTruthy();
    expect(screen.queryByText("هل كانت الإجابة مفيدة؟")).toBeNull();
  });

  it("walks the stage messages while waiting and aborts a superseded question", async () => {
    const slow = transportOf([{ type: "result", response: RESPONSE }], 100_000);
    const { rerender } = render(<SmartResults question="أول" kind={undefined} transport={slow} />);
    expect(screen.getByRole("status").textContent).toContain(STAGE_MESSAGES[0]);
    await act(async () => {
      vi.advanceTimersByTime(STAGE_AT_MS[1]);
    });
    expect(screen.getByRole("status").textContent).toContain(STAGE_MESSAGES[1]);
    await act(async () => {
      vi.advanceTimersByTime(STAGE_AT_MS[2] - STAGE_AT_MS[1]);
    });
    expect(screen.getByRole("status").textContent).toContain(STAGE_MESSAGES[2]);

    rerender(<SmartResults question="ثانٍ" kind={undefined} transport={slow} />);
    await flush();
    expect(slow.calls[0].aborted).toBe(true);
    expect(slow.calls).toHaveLength(2);
    expect(slow.calls[1].aborted).toBe(false);
  });

  it("shows streamed passages while the answer is still being written", async () => {
    const early = transportOf(
      [
        { type: "stage", stage: "rerank" },
        { type: "passages", passages: RESPONSE.passages },
        { type: "result", response: RESPONSE },
      ],
      100_000,
    );
    render(<SmartResults question="سؤال" kind={undefined} transport={early} />);
    await flush();
    expect(screen.queryByText(/الإيمان بالله وحده/)).toBeNull();

    // A transport that yields before its delay: emulate by a second, instant one.
    const instant = transportOf([
      { type: "passages", passages: RESPONSE.passages },
    ]);
    render(<SmartResults question="آخر" kind={undefined} transport={instant} />);
    await flush();
    expect(screen.getByText(/الإيمان بالله وحده/)).toBeTruthy();
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
  });

  it("gives up after the client timeout", async () => {
    const stuck = transportOf([{ type: "result", response: RESPONSE }], 10 * CLIENT_TIMEOUT_MS);
    render(<SmartResults question="سؤال" kind={undefined} transport={stuck} />);
    await act(async () => {
      vi.advanceTimersByTime(CLIENT_TIMEOUT_MS + 10);
    });
    await flush();

    expect(screen.getByRole("alert").textContent).toContain("لم تكتمل");
    expect(screen.getByText("تابع بالبحث الدقيق").getAttribute("href")).toBe(
      "/search?q=%D8%B3%D8%A4%D8%A7%D9%84",
    );
  });

  it("counts down a rate limit and offers exact search", async () => {
    render(
      <SmartResults
        question="سؤال"
        kind="khawatir"
        transport={transportOf([{ type: "error", error: "rate_limited", retryAfter: 3 }])}
      />,
    );
    await flush();

    expect(screen.getByTestId("retry-countdown").textContent).toContain("3");
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByTestId("retry-countdown").textContent).toContain("1");
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.queryByTestId("retry-countdown")).toBeNull();
    expect(screen.getByText("تابع بالبحث الدقيق").getAttribute("href")).toBe(
      "/search?q=%D8%B3%D8%A4%D8%A7%D9%84&kind=khawatir",
    );
  });
});
