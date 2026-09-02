"use client";

import { useState } from "react";
import { postSmartFeedback } from "@/lib/api";

interface SmartFeedbackProps {
  queryId: string;
}

type Sent = "idle" | "sending" | "sent" | "failed";

/** A thumb up or down on this answer — recorded against its query id. */
export default function SmartFeedback({ queryId }: SmartFeedbackProps) {
  const [state, setState] = useState<Sent>("idle");

  const send = async (vote: "up" | "down") => {
    setState("sending");
    try {
      await postSmartFeedback(queryId, { vote });
      setState("sent");
    } catch {
      setState("failed");
    }
  };

  if (state === "sent") {
    return <p className="mt-6 text-xs text-[var(--color-ink-muted)]">شكرًا لك، سُجّل رأيك.</p>;
  }
  return (
    <div className="mt-6 flex flex-wrap items-center gap-3 text-xs text-[var(--color-ink-muted)]">
      <span>هل كانت الإجابة مفيدة؟</span>
      <button type="button" className="chunk-chip" disabled={state === "sending"} onClick={() => send("up")}>
        نعم
      </button>
      <button type="button" className="chunk-chip" disabled={state === "sending"} onClick={() => send("down")}>
        لا
      </button>
      {state === "failed" ? <span>تعذّر إرسال الرأي الآن.</span> : null}
    </div>
  );
}
