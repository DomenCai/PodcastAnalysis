export type Health = {
  ffmpeg: boolean;
  ffprobe: boolean;
  output_writable: boolean;
  mimo_key: boolean;
  llm_key: boolean;
};

export type EpisodeListItem = {
  id: string;
  title: string;
  podcast_title: string;
  duration: number;
  has_transcript: boolean;
  has_summary: boolean;
};

export type EpisodeDetail = EpisodeListItem & {
  description?: string;
  shownotes?: string;
  audio_url?: string;
  has_audio: boolean;
};

export type TaskState = {
  task_id: string;
  episode_id: string | null;
  stage:
    | "fetching_info"
    | "downloading"
    | "splitting"
    | "transcribing"
    | "summarizing"
    | "done"
    | "error"
    | string;
  done: number;
  total: number;
  status: "running" | "done" | "error" | string;
  error: string | null;
};
