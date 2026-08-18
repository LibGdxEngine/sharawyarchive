/**
 * audio-store.test.ts
 *
 * Unit tests for the Zustand audio store.
 * Uses happy-dom environment (configured in vitest.config.ts).
 * Stubs HTMLAudioElement so no real media is loaded.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useAudioStore, getSavedPositionMs } from "./audio-store";
import type { PlaybackRate, Track } from "./audio-store";

// ---------------------------------------------------------------------------
// Stub HTMLAudioElement
// ---------------------------------------------------------------------------

class FakeAudio {
  src = "";
  currentTime = 0;
  playbackRate = 1;
  paused = true;

  private _listeners: Record<string, Array<() => void>> = {};

  addEventListener(event: string, cb: () => void) {
    if (!this._listeners[event]) this._listeners[event] = [];
    this._listeners[event].push(cb);
  }

  removeEventListener(event: string, cb: () => void) {
    if (!this._listeners[event]) return;
    this._listeners[event] = this._listeners[event].filter((fn) => fn !== cb);
  }

  emit(event: string) {
    (this._listeners[event] ?? []).forEach((fn) => fn());
  }

  play = vi.fn().mockResolvedValue(undefined);
  pause = vi.fn().mockImplementation(() => {
    this.paused = true;
    this.emit("pause");
  });
  load = vi.fn();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeTrack(overrides: Partial<Track> = {}): Track {
  return {
    segmentId: 1,
    title: "الفاتحة",
    audioUrl: "https://example.com/audio.opus",
    durationMs: 60_000,
    ...overrides,
  };
}

function resetStore() {
  useAudioStore.setState({
    current: null,
    isPlaying: false,
    positionMs: 0,
    rate: 1,
    sleepTimerHandle: null,
    _el: null,
    _persistInterval: null,
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("audio-store", () => {
  let fakeEl: FakeAudio;

  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    fakeEl = new FakeAudio();
    resetStore();
    // Bind the fake element
    useAudioStore.getState().bindAudio(fakeEl as unknown as HTMLAudioElement);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // -------------------------------------------------------------------------
  // load
  // -------------------------------------------------------------------------
  describe("load()", () => {
    it("sets current track and position to 0 when no saved position", () => {
      const track = makeTrack();
      useAudioStore.getState().load(track, { autoplay: false });

      const state = useAudioStore.getState();
      expect(state.current).toEqual(track);
      expect(state.positionMs).toBe(0);
    });

    it("resumes from localStorage saved position", () => {
      const track = makeTrack({ segmentId: 42 });
      localStorage.setItem("pos:42", "15000");

      useAudioStore.getState().load(track, { autoplay: false });

      expect(useAudioStore.getState().positionMs).toBe(15_000);
      expect(fakeEl.currentTime).toBeCloseTo(15);
    });

    it("respects explicit startMs over saved position", () => {
      const track = makeTrack({ segmentId: 42 });
      localStorage.setItem("pos:42", "15000");

      useAudioStore.getState().load(track, { startMs: 5_000, autoplay: false });

      expect(useAudioStore.getState().positionMs).toBe(5_000);
      expect(fakeEl.currentTime).toBeCloseTo(5);
    });

    it("sets audioEl.src to the track's audioUrl", () => {
      const track = makeTrack({ audioUrl: "https://cdn.example.com/seg1.opus" });
      useAudioStore.getState().load(track, { autoplay: false });

      expect(fakeEl.src).toBe("https://cdn.example.com/seg1.opus");
    });
  });

  // -------------------------------------------------------------------------
  // play / pause / toggle
  // -------------------------------------------------------------------------
  describe("play/pause/toggle", () => {
    it("play() calls el.play()", () => {
      const track = makeTrack();
      useAudioStore.getState().load(track, { autoplay: false });

      useAudioStore.getState().play();
      expect(fakeEl.play).toHaveBeenCalledOnce();
    });

    it("pause() calls el.pause()", () => {
      useAudioStore.getState().load(makeTrack(), { autoplay: false });

      useAudioStore.getState().pause();
      expect(fakeEl.pause).toHaveBeenCalledOnce();
    });

    it("toggle() plays when paused, pauses when playing", () => {
      useAudioStore.getState().load(makeTrack(), { autoplay: false });

      // Start paused
      useAudioStore.setState({ isPlaying: false });
      useAudioStore.getState().toggle();
      expect(fakeEl.play).toHaveBeenCalledOnce();

      // Start playing
      useAudioStore.setState({ isPlaying: true });
      useAudioStore.getState().toggle();
      expect(fakeEl.pause).toHaveBeenCalledOnce();
    });
  });

  // -------------------------------------------------------------------------
  // Seeking
  // -------------------------------------------------------------------------
  describe("seekMs()", () => {
    it("clamps to 0 when seeking before start", () => {
      useAudioStore.getState().load(makeTrack({ durationMs: 60_000 }), { autoplay: false });

      useAudioStore.getState().seekMs(-5_000);

      expect(fakeEl.currentTime).toBe(0);
      expect(useAudioStore.getState().positionMs).toBe(0);
    });

    it("clamps to durationMs when seeking past end", () => {
      useAudioStore.getState().load(makeTrack({ durationMs: 60_000 }), { autoplay: false });

      useAudioStore.getState().seekMs(99_000);

      expect(fakeEl.currentTime).toBeCloseTo(60);
      expect(useAudioStore.getState().positionMs).toBe(60_000);
    });

    it("stores integer ms in positionMs", () => {
      useAudioStore.getState().load(makeTrack({ durationMs: 60_000 }), { autoplay: false });

      useAudioStore.getState().seekMs(30_500);

      expect(Number.isInteger(useAudioStore.getState().positionMs)).toBe(true);
    });
  });

  describe("seekBy()", () => {
    it("seeks forward by delta", () => {
      useAudioStore.getState().load(makeTrack({ durationMs: 60_000 }), { autoplay: false });
      useAudioStore.setState({ positionMs: 20_000 });
      // Update el.currentTime to match
      fakeEl.currentTime = 20;

      useAudioStore.getState().seekBy(10_000);

      expect(useAudioStore.getState().positionMs).toBe(30_000);
    });
  });

  // -------------------------------------------------------------------------
  // Rate
  // -------------------------------------------------------------------------
  describe("setRate()", () => {
    const validRates: PlaybackRate[] = [0.75, 1, 1.25, 1.5];

    it.each(validRates)("accepts rate %s", (rate) => {
      useAudioStore.getState().setRate(rate);
      expect(useAudioStore.getState().rate).toBe(rate);
      expect(fakeEl.playbackRate).toBe(rate);
    });

    it("only accepts the four allowed rates (TypeScript enforces at compile time)", () => {
      // This test ensures the TypeScript type is correct — at runtime we verify
      // the store stores what it receives for the valid set.
      const rates: PlaybackRate[] = [0.75, 1, 1.25, 1.5];
      rates.forEach((r) => {
        useAudioStore.getState().setRate(r);
        expect([0.75, 1, 1.25, 1.5]).toContain(useAudioStore.getState().rate);
      });
    });
  });

  // -------------------------------------------------------------------------
  // Position persistence
  // -------------------------------------------------------------------------
  describe("position persistence", () => {
    it("saves position to localStorage on pause", () => {
      const track = makeTrack({ segmentId: 7 });
      useAudioStore.getState().load(track, { autoplay: false });
      fakeEl.currentTime = 25;

      fakeEl.pause();

      expect(localStorage.getItem("pos:7")).toBe("25000");
    });

    it("getSavedPositionMs returns 0 when no entry exists", () => {
      expect(getSavedPositionMs(999)).toBe(0);
    });

    it("getSavedPositionMs returns saved value", () => {
      localStorage.setItem("pos:5", "12500");
      expect(getSavedPositionMs(5)).toBe(12500);
    });

    it("saves position every 5 seconds while playing", () => {
      const track = makeTrack({ segmentId: 3 });
      useAudioStore.getState().load(track, { autoplay: false });
      useAudioStore.setState({ isPlaying: true });
      fakeEl.currentTime = 10;

      vi.advanceTimersByTime(5100);

      expect(localStorage.getItem("pos:3")).toBe("10000");
    });
  });
});
