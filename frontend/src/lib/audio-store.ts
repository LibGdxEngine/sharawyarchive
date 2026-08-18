/**
 * Global audio playback store.
 *
 * Rules:
 * - Owns ONE HTMLAudioElement wired via bindAudio() from <GlobalAudio>.
 * - All public timestamps are integer milliseconds.
 * - Converts to/from seconds only at the element boundary.
 * - No Audio() construction at module scope (SSR safety).
 * - Per-segment position persisted to localStorage key `pos:<segmentId>`.
 */

import { create } from "zustand";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PlaybackRate = 0.75 | 1 | 1.25 | 1.5;

export interface Track {
  segmentId: number;
  title: string;
  audioUrl: string;
  durationMs: number;
}

interface AudioState {
  current: Track | null;
  isPlaying: boolean;
  /** Coarse position (~4 Hz) — good enough for progress UI. Player page uses rAF directly. */
  positionMs: number;
  rate: PlaybackRate;
  sleepTimerHandle: ReturnType<typeof setTimeout> | null;

  // Internal — not surfaced to consumers
  _el: HTMLAudioElement | null;
  _persistInterval: ReturnType<typeof setInterval> | null;
}

interface AudioActions {
  /** Called once by <GlobalAudio> on mount to wire the hidden <audio> element. */
  bindAudio(el: HTMLAudioElement): void;

  load(track: Track, options?: { startMs?: number; autoplay?: boolean }): void;
  play(): void;
  pause(): void;
  toggle(): void;
  seekMs(ms: number): void;
  seekBy(deltaMs: number): void;
  setRate(rate: PlaybackRate): void;
  setSleepTimer(minutes: number | null): void;
}

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

const STORAGE_KEY = (segmentId: number) => `pos:${segmentId}`;

export function getSavedPositionMs(segmentId: number): number {
  if (typeof window === "undefined") return 0;
  const raw = localStorage.getItem(STORAGE_KEY(segmentId));
  if (raw === null) return 0;
  const val = parseInt(raw, 10);
  return isNaN(val) ? 0 : val;
}

function savePositionMs(segmentId: number, ms: number): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY(segmentId), String(Math.floor(ms)));
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

type FullState = AudioState & AudioActions;

export const useAudioStore = create<FullState>()((set, get) => ({
  // State
  current: null,
  isPlaying: false,
  positionMs: 0,
  rate: 1,
  sleepTimerHandle: null,
  _el: null,
  _persistInterval: null,

  // ---------------------------------------------------------------------------
  // bindAudio — called once from GlobalAudio
  // ---------------------------------------------------------------------------
  bindAudio(el: HTMLAudioElement) {
    const { _el: prev } = get();
    if (prev === el) return;

    // Detach old listeners if element is being replaced
    if (prev) {
      prev.onplay = null;
      prev.onpause = null;
      prev.ontimeupdate = null;
      prev.onended = null;
    }

    const onPlay = () => set({ isPlaying: true });
    const onPause = () => {
      set({ isPlaying: false });
      const { current, _el } = get();
      if (current && _el) {
        savePositionMs(current.segmentId, _el.currentTime * 1000);
      }
    };
    const onTimeUpdate = () => {
      const { _el: audioEl } = get();
      if (audioEl) {
        set({ positionMs: Math.floor(audioEl.currentTime * 1000) });
      }
    };
    const onEnded = () => {
      const { current } = get();
      if (current) savePositionMs(current.segmentId, 0);
      set({ isPlaying: false, positionMs: 0 });
    };

    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("timeupdate", onTimeUpdate);
    el.addEventListener("ended", onEnded);

    // Persist position every 5 seconds while playing
    const persistInterval = setInterval(() => {
      const { _el: audioEl, current, isPlaying: playing } = get();
      if (audioEl && current && playing) {
        savePositionMs(current.segmentId, audioEl.currentTime * 1000);
      }
    }, 5000);

    // Save position on page unload
    const onBeforeUnload = () => {
      const { _el: audioEl, current } = get();
      if (audioEl && current) {
        savePositionMs(current.segmentId, audioEl.currentTime * 1000);
      }
    };
    window.addEventListener("beforeunload", onBeforeUnload);

    set({ _el: el, _persistInterval: persistInterval });
  },

  // ---------------------------------------------------------------------------
  // load
  // ---------------------------------------------------------------------------
  load(track: Track, options: { startMs?: number; autoplay?: boolean } = {}) {
    const { _el, _persistInterval, sleepTimerHandle, current } = get();

    // Save position of previous track before loading new one
    if (_el && current) {
      savePositionMs(current.segmentId, _el.currentTime * 1000);
    }

    // Clear existing sleep timer
    if (sleepTimerHandle !== null) {
      clearTimeout(sleepTimerHandle);
    }

    // Clear persist interval (will be reset on bindAudio or kept as-is)
    if (_persistInterval !== null) {
      clearInterval(_persistInterval);
    }

    const savedMs = getSavedPositionMs(track.segmentId);
    const startMs = options.startMs ?? savedMs;

    set({
      current: track,
      isPlaying: false,
      positionMs: startMs,
      sleepTimerHandle: null,
    });

    if (_el) {
      _el.src = track.audioUrl;
      _el.currentTime = startMs / 1000;
      _el.load();

      if (options.autoplay !== false) {
        _el.play().catch(() => {
          // Autoplay blocked — ignore, user must tap play
        });
      }

      // Restart persist interval
      const persistInterval = setInterval(() => {
        const { _el: audioEl, current: cur, isPlaying: playing } = get();
        if (audioEl && cur && playing) {
          savePositionMs(cur.segmentId, audioEl.currentTime * 1000);
        }
      }, 5000);
      set({ _persistInterval: persistInterval });
    }
  },

  // ---------------------------------------------------------------------------
  // play / pause / toggle
  // ---------------------------------------------------------------------------
  play() {
    const { _el } = get();
    if (_el) {
      _el.play().catch(() => undefined);
    }
  },

  pause() {
    const { _el } = get();
    if (_el) {
      _el.pause();
    }
  },

  toggle() {
    const { isPlaying } = get();
    if (isPlaying) {
      get().pause();
    } else {
      get().play();
    }
  },

  // ---------------------------------------------------------------------------
  // Seeking
  // ---------------------------------------------------------------------------
  seekMs(ms: number) {
    const { _el, current } = get();
    if (!_el || !current) return;
    const clamped = Math.max(0, Math.min(ms, current.durationMs));
    _el.currentTime = clamped / 1000;
    set({ positionMs: Math.floor(clamped) });
  },

  seekBy(deltaMs: number) {
    const { positionMs } = get();
    get().seekMs(positionMs + deltaMs);
  },

  // ---------------------------------------------------------------------------
  // Rate
  // ---------------------------------------------------------------------------
  setRate(rate: PlaybackRate) {
    const { _el } = get();
    if (_el) {
      _el.playbackRate = rate;
    }
    set({ rate });
  },

  // ---------------------------------------------------------------------------
  // Sleep timer
  // ---------------------------------------------------------------------------
  setSleepTimer(minutes: number | null) {
    const { sleepTimerHandle } = get();
    if (sleepTimerHandle !== null) {
      clearTimeout(sleepTimerHandle);
      set({ sleepTimerHandle: null });
    }
    if (minutes !== null) {
      const handle = setTimeout(() => {
        get().pause();
        set({ sleepTimerHandle: null });
      }, minutes * 60 * 1000);
      set({ sleepTimerHandle: handle });
    }
  },
}));
