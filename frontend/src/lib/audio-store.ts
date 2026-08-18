/**
 * Global audio playback store.
 *
 * Rules:
 * - Owns ONE HTMLAudioElement wired via bindAudio() from <GlobalAudio>.
 * - All public timestamps are integer milliseconds.
 * - Converts to/from seconds only at the element boundary.
 * - No Audio() construction at module scope (SSR safety).
 * - Per-segment position persisted to localStorage key `pos:<segmentId>`.
 * - A start position is applied on `loadedmetadata`, never next to the `src`
 *   assignment: the load algorithm the assignment starts resets currentTime.
 */

import { create } from "zustand";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PlaybackRate = 0.75 | 1 | 1.25 | 1.5;

/**
 * `HTMLMediaElement.HAVE_METADATA` — duration and dimensions are known, so the
 * element accepts a seek that will stick. Spelled out rather than read off the
 * constructor because the store must not touch DOM globals at module scope.
 */
const HAVE_METADATA = 1;

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
  /**
   * Position waiting for the element to report metadata, or null when nothing
   * is pending. Assigning `src` restarts the load algorithm, which resets
   * `currentTime` to 0 — so a start position asked for before the resource is
   * ready has to be re-applied on `loadedmetadata`.
   */
  _pendingSeekMs: number | null;
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

/** Frees an offline blob source once the element has stopped pointing at it. */
function revokeIfObjectUrl(url: string): void {
  if (typeof URL === "undefined" || !url.startsWith("blob:")) return;
  URL.revokeObjectURL(url);
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
  _pendingSeekMs: null,

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
    // The one place a start position can actually be applied: before this
    // fires, the element has no duration and any `currentTime` write is
    // discarded by the resource-load algorithm.
    const onLoadedMetadata = () => {
      const { _el: audioEl, _pendingSeekMs } = get();
      if (!audioEl || _pendingSeekMs === null) return;
      audioEl.currentTime = _pendingSeekMs / 1000;
      set({ _pendingSeekMs: null, positionMs: Math.floor(_pendingSeekMs) });
    };

    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("timeupdate", onTimeUpdate);
    el.addEventListener("ended", onEnded);
    el.addEventListener("loadedmetadata", onLoadedMetadata);

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

    // An offline track is played from an object URL owned by whoever built the
    // track; the store is the only place that knows when it stops being used.
    if (current && current.audioUrl !== track.audioUrl) {
      revokeIfObjectUrl(current.audioUrl);
    }

    if (_el) {
      if (_el.src === track.audioUrl && _el.readyState >= HAVE_METADATA) {
        // Same resource, already loaded: nothing resets, so seek right away.
        _el.currentTime = startMs / 1000;
        set({ _pendingSeekMs: null });
      } else {
        // Assigning `src` is itself the load trigger (an explicit load() only
        // restarts the same algorithm) and it zeroes currentTime, so the start
        // position is parked until `loadedmetadata`.
        set({ _pendingSeekMs: startMs });
        _el.src = track.audioUrl;
      }

      if (options.autoplay !== false) {
        _el.play().catch(() => {
          // Autoplay policy refused the gesture — the transport stays in its
          // paused state and the listener taps play.
          set({ isPlaying: false });
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
    const { _el, current, _pendingSeekMs } = get();
    if (!_el || !current) return;
    const clamped = Math.max(0, Math.min(ms, current.durationMs));
    _el.currentTime = clamped / 1000;
    // A seek issued while the resource is still loading must also replace the
    // parked position, or `loadedmetadata` would drag playback back.
    if (_pendingSeekMs !== null) set({ _pendingSeekMs: clamped });
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
