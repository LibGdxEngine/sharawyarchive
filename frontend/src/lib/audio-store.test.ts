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
//
// The stub reproduces the one media behaviour every seek depends on: starting
// the resource-load algorithm — by assigning `src`, or by calling `load()` —
// rewinds the element and throws away what it knew about the resource. A stub
// that skipped this would let a store that seeks too early pass.
// ---------------------------------------------------------------------------

const HAVE_NOTHING = 0;
const HAVE_METADATA = 1;

class FakeAudio {
  currentTime = 0;
  playbackRate = 1;
  paused = true;
  readyState = HAVE_NOTHING;

  private _src = "";
  private _listeners: Record<string, Array<() => void>> = {};

  get src(): string {
    return this._src;
  }

  set src(value: string) {
    this._src = value;
    this._resetResource();
  }

  /** The element reaching HAVE_METADATA — driven by the test, as by a network. */
  fireLoadedMetadata() {
    this.readyState = HAVE_METADATA;
    this.emit("loadedmetadata");
  }

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
  load = vi.fn().mockImplementation(() => {
    this._resetResource();
  });

  private _resetResource() {
    this.currentTime = 0;
    this.readyState = HAVE_NOTHING;
  }
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
    _pendingSeekMs: null,
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
      fakeEl.fireLoadedMetadata();

      expect(useAudioStore.getState().positionMs).toBe(15_000);
      expect(fakeEl.currentTime).toBeCloseTo(15);
    });

    it("respects explicit startMs over saved position", () => {
      const track = makeTrack({ segmentId: 42 });
      localStorage.setItem("pos:42", "15000");

      useAudioStore.getState().load(track, { startMs: 5_000, autoplay: false });
      fakeEl.fireLoadedMetadata();

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
  // Start position vs. the resource-load algorithm
  //
  // `?t=` deep links, "play from here" in search results and per-segment resume
  // all arrive here: a position asked for while the element is still empty.
  // -------------------------------------------------------------------------
  describe("start position", () => {
    it("lands on startMs once the element reports metadata", () => {
      useAudioStore
        .getState()
        .load(makeTrack(), { startMs: 30_000, autoplay: false });

      // Nothing to seek yet — the element has no duration.
      expect(fakeEl.currentTime).toBe(0);

      fakeEl.fireLoadedMetadata();

      expect(fakeEl.currentTime).toBeCloseTo(30);
      expect(useAudioStore.getState().positionMs).toBe(30_000);
    });

    it("survives the reset that assigning src performs", () => {
      // Regression: the store used to write currentTime and then call load(),
      // whose reset silently threw the position away and started at 0.
      fakeEl.currentTime = 99;

      useAudioStore
        .getState()
        .load(makeTrack(), { startMs: 12_000, autoplay: false });

      expect(fakeEl.src).toBe("https://example.com/audio.opus");
      expect(fakeEl.currentTime).toBe(0); // the reset really happened
      expect(fakeEl.readyState).toBe(0);

      fakeEl.fireLoadedMetadata();

      expect(fakeEl.currentTime).toBeCloseTo(12);
    });

    it("seeks immediately when the same resource is already loaded", () => {
      const track = makeTrack();
      useAudioStore.getState().load(track, { startMs: 5_000, autoplay: false });
      fakeEl.fireLoadedMetadata();

      useAudioStore.getState().load(track, { startMs: 20_000, autoplay: false });

      // No second metadata event: the resource never went away.
      expect(fakeEl.currentTime).toBeCloseTo(20);
      expect(useAudioStore.getState().positionMs).toBe(20_000);
    });

    it("lets a seek made during loading win over the parked position", () => {
      useAudioStore
        .getState()
        .load(makeTrack({ durationMs: 60_000 }), {
          startMs: 30_000,
          autoplay: false,
        });

      useAudioStore.getState().seekMs(10_000);
      fakeEl.fireLoadedMetadata();

      expect(fakeEl.currentTime).toBeCloseTo(10);
    });

    it("starts playback when autoplay is requested (deep link / play from here)", () => {
      useAudioStore
        .getState()
        .load(makeTrack(), { startMs: 5_000, autoplay: true });

      expect(fakeEl.play).toHaveBeenCalledOnce();

      fakeEl.fireLoadedMetadata();
      expect(fakeEl.currentTime).toBeCloseTo(5);
    });

    it("stays paused when the autoplay policy rejects play()", async () => {
      fakeEl.play.mockRejectedValueOnce(new Error("NotAllowedError"));

      useAudioStore
        .getState()
        .load(makeTrack(), { startMs: 5_000, autoplay: true });
      await Promise.resolve();
      await Promise.resolve();

      expect(useAudioStore.getState().isPlaying).toBe(false);
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
