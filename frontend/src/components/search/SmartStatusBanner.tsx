import type { SmartStatus } from "@/types/models";

export const STATUS_COPY: Record<Exclude<SmartStatus, "answered">, string> = {
  partial: "وجدت مقاطع ذات صلة لكن دون إجابة صريحة.",
  not_found: "لم أجد في الأرشيف ما يجيب عن هذا السؤال، وهذه أقرب المقاطع إليه.",
  degraded: "تعذّر توليد الإجابة الآن، وهذه أقرب المقاطع لسؤالك.",
};

/** One line above the answer for every status but a full answer. */
export default function SmartStatusBanner({ status }: { status: SmartStatus }) {
  if (status === "answered") return null;
  return (
    <p className="smart-banner mt-4" data-status={status} role="status">
      {STATUS_COPY[status]}
    </p>
  );
}
