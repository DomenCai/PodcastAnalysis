export type Backend = "qwen" | "whisper" | "mimo";
export type JobStatus = "queued" | "running" | "done" | "error";
export type ArtifactName =
  "transcript.txt" | "article.md" | "notes.md" | "mindmap.md";

export type Health = {
  ok: boolean;
  read_only: boolean;
  worker?: "single";
  ffmpeg?: boolean;
  analysis?: {
    backend: "pi" | "agy" | "codex";
    model: string;
    thinking: string | null;
    available: boolean;
    fallback?: {
      backend: "codex";
      model: string;
      thinking: string;
      available: boolean;
      cooldown_seconds: number;
      active: boolean;
      remaining_seconds: number;
      cooldown_until: string | null;
    } | null;
    deai?: { backend: "agy"; model: string; available: boolean } | null;
  };
  backends?: { qwen?: boolean; whisper: boolean; mimo: boolean };
};

export type EpisodeInfo = {
  title?: string;
  description?: string;
  podcast_title?: string;
  url?: string;
  [key: string]: unknown;
};

export type Job = {
  id: string;
  filename: string;
  status: JobStatus;
  stage: string;
  error?: string;
  result_url?: string;
  backend: Backend;
  skip_diarization: boolean;
  num_speakers: number | null;
  episode_url: string | null;
  episode?: EpisodeInfo;
  created_at: string;
  updated_at: string;
  available_files: string[];
  can_resume_transcription?: boolean;
};

export type Subscription = {
  id: number;
  podcast_id: string;
  title: string;
  author: string;
  description: string;
  source_url: string;
  enabled: boolean;
  done_count: number;
  pending_count: number;
  processing_count: number;
  failed_count: number;
  awaiting_count: number;
  auto_process: boolean;
  poll_interval_minutes: number;
  backend: Backend;
  skip_diarization: boolean;
  num_speakers: number | null;
};

export type SubscriptionEpisodeStatus =
  | "pending"
  | "awaiting"
  | "processing"
  | "done"
  | "failed"
  | "ignored"
  | "skipped";

export type SubscriptionEpisode = {
  id: number;
  eid: string;
  title: string;
  description?: string;
  episode_url: string;
  status: SubscriptionEpisodeStatus;
  published_at: string;
  duration: number;
  backend?: Backend;
  skip_diarization?: boolean;
  num_speakers?: number | null;
  error?: string;
  result_dir?: string | null;
  job_id?: string | null;
  available_files?: string[];
};

export type PublicEpisode = {
  id: number;
  eid: string;
  episode_url: string;
  title: string;
  description: string;
  published_at: string;
  duration: number;
  status: SubscriptionEpisodeStatus;
  has_result: boolean;
  available_files?: string[];
};

export type PublicJob = {
  id: string;
  title: string;
  podcast_title: string;
  description: string;
  published_at: string | null;
  episode_url: string | null;
  available_files: string[];
};

export type LibraryGroup = {
  title: string;
  articles: Array<{ kind: "job" | "episode"; id: string | number; title: string; published_at: string | null; url: string }>;
};

export type ProcessingOptions = {
  backend: Backend;
  skip_diarization: boolean;
  num_speakers: number | null;
};
