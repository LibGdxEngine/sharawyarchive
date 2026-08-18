import type {
  Surah,
  SurahDetail,
  AyahDetail,
  Segment,
  Transcript,
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
    throw new Error(`API ${res.status}: ${path}`);
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
