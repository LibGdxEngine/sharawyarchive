// ---------------------------------------------------------------------------
// API response types — mirrors API_CONTRACT.md exactly
// All timestamps are integer milliseconds.
// ---------------------------------------------------------------------------

export interface Surah {
  number: number;
  name_ar: string;
  name_ar_plain: string;
  name_en: string;
  ayah_count: number;
  revelation_place: string;
  segment_count: number;
}

export interface AyahSummary {
  number: number;
  text_uthmani: string;
  juz: number;
  page: number;
  sajda: boolean;
  segment_count: number;
}

export interface PaginatedAyahs {
  count: number;
  page: number;
  page_size: number;
  results: AyahSummary[];
}

export interface SurahDetail {
  number: number;
  name_ar: string;
  name_en: string;
  ayah_count: number;
  revelation_place: string;
  ayahs: PaginatedAyahs;
}

export interface SegmentSummary {
  id: number;
  kind: "recitation" | "khawatir";
  title: string;
  ayah_start: number;
  ayah_end: number;
  duration_ms: number;
}

export interface AyahDetail {
  surah: number;
  number: number;
  text_uthmani: string;
  text_imlaei: string;
  juz: number;
  page: number;
  segments: SegmentSummary[];
}

export interface Source {
  title: string;
  kind: string;
}

export interface Segment {
  id: number;
  kind: "recitation" | "khawatir";
  title: string;
  surah: number;
  ayah_start: number;
  ayah_end: number;
  duration_ms: number;
  ordinal: number;
  audio_url: string;
  waveform_url: string;
  source: Source;
  transcript_version: number;
  is_human_reviewed: boolean;
}

/**
 * Compact transcript word — keys intentionally short for network efficiency.
 * i = index, t = text, s = start_ms, e = end_ms, c = confidence
 */
export interface TranscriptWord {
  i: number;
  t: string;
  s: number;
  e: number;
  c: number;
}

export interface Transcript {
  version: number;
  engine: string;
  is_human_reviewed: boolean;
  words: TranscriptWord[];
}

export interface SearchChunkResult {
  chunk_id: number;
  segment_id: number;
  segment_title: string;
  surah: number;
  ayah_start: number;
  ayah_end: number;
  kind: "recitation" | "khawatir";
  text: string;
  start_ms: number;
  end_ms: number;
}

export interface AyahMatch {
  surah: number;
  number: number;
  text_uthmani: string;
  surah_name_ar: string;
}

export interface SearchResponse {
  query: string;
  mode: "hybrid" | "lexical" | "semantic";
  ayah_matches: AyahMatch[];
  results: SearchChunkResult[];
  page: number;
  total: number;
}

export interface Topic {
  slug: string;
  name_ar: string;
  description_ar: string;
  chunk_count: number;
}

export interface TopicDetail {
  slug: string;
  name_ar: string;
  description_ar: string;
  chunk_count: number;
  chunks: SearchChunkResult[];
}

export interface CorrectionResponse {
  id: number;
  status: "pending";
}

export type ClipStatus = "queued" | "rendering" | "done" | "failed";

export interface ClipCreateResponse {
  id: string;
  status: "queued";
}

export interface Clip {
  id: string;
  status: ClipStatus;
  video_url: string | null;
}
