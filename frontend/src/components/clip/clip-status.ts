import type { ClipStatus } from "@/types/models";

/**
 * The one Arabic status vocabulary for clip renders.
 *
 * There used to be three copies of this map — the composer, the verse modal
 * and the share page — which is how "تعذّر إنشاء المقطع" and "تعذّر إنشاء هذا
 * المقطع." came to differ by a demonstrative and a full stop.
 */
export const STATUS_LABEL: Record<ClipStatus, string> = {
  queued: "في قائمة الانتظار…",
  rendering: "جارٍ إنشاء المقطع…",
  done: "المقطع جاهز",
  failed: "تعذّر إنشاء المقطع",
};

/** Polling stopped watching, but the worker has not: say so, do not lie. */
export const STILL_RENDERING =
  "ما زال الإنشاء جاريًا — افتح صفحة المقطع بعد قليل.";

/** What to show beside the submit button, given how the poll ended. */
export function statusLine(status: ClipStatus, timedOut: boolean): string {
  return timedOut && status !== "done" && status !== "failed"
    ? STILL_RENDERING
    : STATUS_LABEL[status];
}
