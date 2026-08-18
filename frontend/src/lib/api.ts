import { pickChunkForWord } from "@/lib/correction-selection";
import type {
  Surah,
  SurahDetail,
  AyahDetail,
  Segment,
  SegmentChunk,
  Transcript,
  SearchChunkResult,
  SearchResponse,
  Topic,
  TopicDetail,
  CorrectionResponse,
  ClipCreateResponse,
  Clip,
} from "@/types/models";

const BASE_URL =
  (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api").replace(
    /\/$/,
    ""
  );

/**
 * A non-2xx API response.
 *
 * Carries the status so callers can tell apart the cases the UI has words for
 * — 429 (throttled) and 404 (endpoint or object missing) — from a generic
 * failure. Extends Error, so existing `catch {}` sites are unaffected.
 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, path: string) {
    super(`API ${status}: ${path}`);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "Accept-Encoding": "gzip",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new ApiError(res.status, path);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Surahs
// ---------------------------------------------------------------------------

export function getSurahs(): Promise<Surah[]> {
  return apiFetch<Surah[]>("/surahs/");
}

export function getSurah(n: number, page = 1): Promise<SurahDetail> {
  return apiFetch<SurahDetail>(`/surahs/${n}/?page=${page}`);
}

// ---------------------------------------------------------------------------
// Ayahs
// ---------------------------------------------------------------------------

export function getAyah(surah: number, ayah: number): Promise<AyahDetail> {
  return apiFetch<AyahDetail>(`/ayahs/${surah}/${ayah}/`);
}

// ---------------------------------------------------------------------------
// Segments
// ---------------------------------------------------------------------------

export function getSegment(id: number): Promise<Segment> {
  return apiFetch<Segment>(`/segments/${id}/`);
}

/**
 * Chunk map of a segment — word ranges paired with the chunk ids corrections
 * are filed against. Throws ApiError(404) where the deployment predates the
 * endpoint, which the correction UI reports as "unavailable" rather than an
 * error.
 */
export function getSegmentChunks(id: number): Promise<SegmentChunk[]> {
  return apiFetch<SegmentChunk[]>(`/segments/${id}/chunks/`);
}

/**
 * Passages elsewhere in the archive that sit near this segment in embedding
 * space. Returns the search-result shape, so the same renderer handles them.
 */
export function getRelated(id: number): Promise<SearchChunkResult[]> {
  return apiFetch<SearchChunkResult[]>(`/segments/${id}/related/`);
}

export function getTranscript(id: number, version?: number): Promise<Transcript> {
  const qs = version !== undefined ? `?v=${version}` : "";
  return apiFetch<Transcript>(`/segments/${id}/transcript/${qs}`, {
    next: { revalidate: false },
    cache: "force-cache",
  } as RequestInit);
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

export interface SearchParams {
  q: string;
  mode?: "hybrid" | "lexical" | "semantic";
  kind?: "recitation" | "khawatir";
  surah?: number;
  page?: number;
}

export function search(params: SearchParams): Promise<SearchResponse> {
  const sp = new URLSearchParams({ q: params.q });
  if (params.mode) sp.set("mode", params.mode);
  if (params.kind) sp.set("kind", params.kind);
  if (params.surah !== undefined) sp.set("surah", String(params.surah));
  if (params.page !== undefined) sp.set("page", String(params.page));
  return apiFetch<SearchResponse>(`/search/?${sp.toString()}`);
}

// ---------------------------------------------------------------------------
// Topics
// ---------------------------------------------------------------------------

export function getTopics(): Promise<Topic[]> {
  return apiFetch<Topic[]>("/topics/");
}

export function getTopic(slug: string): Promise<TopicDetail> {
  return apiFetch<TopicDetail>(`/topics/${slug}/`);
}

// ---------------------------------------------------------------------------
// Corrections
// ---------------------------------------------------------------------------

export interface CorrectionPayload {
  chunk_id: number;
  word_start: number;
  word_end: number;
  suggested_text: string;
}

export function postCorrection(
  payload: CorrectionPayload
): Promise<CorrectionResponse> {
  return apiFetch<CorrectionResponse>("/corrections/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Submit a correction for a word range of a segment.
 *
 * The transcript view knows word indices; the corrections endpoint is keyed by
 * `chunk_id`. This resolves the gap by reading the segment's chunk map first
 * and posting against the chunk that owns `wordStart`.
 *
 * Throws ApiError — 404 when the chunk map is missing or empty, 429 when the
 * IP throttle has tripped.
 */
export async function postCorrectionForWords(
  segmentId: number,
  wordStart: number,
  wordEnd: number,
  suggestedText: string
): Promise<CorrectionResponse> {
  const chunks = await getSegmentChunks(segmentId);
  const chunk = pickChunkForWord(chunks, wordStart);
  if (chunk === null) {
    throw new ApiError(404, `/segments/${segmentId}/chunks/`);
  }
  return postCorrection({
    chunk_id: chunk.chunk_id,
    word_start: wordStart,
    word_end: wordEnd,
    suggested_text: suggestedText,
  });
}

// ---------------------------------------------------------------------------
// Clips
// ---------------------------------------------------------------------------

export interface ClipPayload {
  segment_id: number;
  start_ms: number;
  end_ms: number;
  preset: string;
}

export function createClip(payload: ClipPayload): Promise<ClipCreateResponse> {
  return apiFetch<ClipCreateResponse>("/clips/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getClip(id: string): Promise<Clip> {
  return apiFetch<Clip>(`/clips/${id}/`);
}
