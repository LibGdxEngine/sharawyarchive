/**
 * Server-side observability hook.
 *
 * Sentry is opt-in: without SENTRY_DSN nothing is imported, nothing is
 * initialised and `onRequestError` returns immediately, so a deployment with
 * no Sentry account behaves exactly as if this file did not exist. The SDK is
 * pulled in dynamically so it never lands in the server bundle's start-up path
 * on DSN-less deployments.
 */

import type { Instrumentation } from "next";

const DSN = process.env.SENTRY_DSN ?? "";

export async function register(): Promise<void> {
  if (DSN === "") return;
  const Sentry = await import("@sentry/nextjs");
  Sentry.init({
    dsn: DSN,
    // Errors only by default; tracing is a separate cost decision.
    tracesSampleRate: 0,
  });
}

export const onRequestError: Instrumentation.onRequestError = async (
  error,
  request,
  context
) => {
  if (DSN === "") return;
  const Sentry = await import("@sentry/nextjs");
  Sentry.captureRequestError(error, request, context);
};
