"use client";

/**
 * InstallPrompt — Listens for the `beforeinstallprompt` event and shows a
 * one-time, unobtrusive banner inviting the user to install the PWA.
 *
 * Dismissed state persisted in localStorage under "pwa:install-dismissed".
 * Once dismissed it will not re-appear in the same browser.
 */

import { useState, useEffect, useRef } from "react";

const DISMISSED_KEY = "pwa:install-dismissed";

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  readonly userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export default function InstallPrompt() {
  const [visible, setVisible] = useState(false);
  const promptRef = useRef<BeforeInstallPromptEvent | null>(null);

  useEffect(() => {
    // Never show if already dismissed
    if (localStorage.getItem(DISMISSED_KEY) === "1") return;

    const handler = (e: Event) => {
      e.preventDefault();
      promptRef.current = e as BeforeInstallPromptEvent;
      setVisible(true);
    };

    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);

  const handleInstall = async () => {
    const deferredPrompt = promptRef.current;
    if (!deferredPrompt) return;
    await deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === "accepted" || outcome === "dismissed") {
      localStorage.setItem(DISMISSED_KEY, "1");
      setVisible(false);
    }
  };

  const handleDismiss = () => {
    localStorage.setItem(DISMISSED_KEY, "1");
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <div
      role="dialog"
      aria-label="تثبيت التطبيق"
      className="fixed bottom-[calc(var(--player-bar-height)+0.75rem)] start-4 end-4 z-40 flex items-center justify-between gap-3 rounded-lg px-4 py-3 shadow-md sm:start-auto sm:end-4 sm:w-80"
      style={{
        backgroundColor: "var(--color-surface)",
        border: "1px solid var(--color-border)",
      }}
    >
      <p className="text-sm" style={{ color: "var(--color-ink)" }}>
        أضِف إلى الشاشة الرئيسية
      </p>
      <div className="flex shrink-0 items-center gap-2">
        <button
          onClick={() => void handleInstall()}
          className="rounded px-3 py-1 text-xs font-medium"
          style={{
            backgroundColor: "var(--color-accent)",
            color: "#ffffff",
          }}
        >
          تثبيت
        </button>
        <button
          onClick={handleDismiss}
          aria-label="إغلاق"
          className="rounded px-2 py-1 text-xs"
          style={{ color: "var(--color-ink-muted)" }}
        >
          ✕
        </button>
      </div>
    </div>
  );
}
