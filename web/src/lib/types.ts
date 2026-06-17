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
    | "error";
  done: number | null;
  total: number | null;
  status: "running" | "done" | "error";
  error: string | null;
};

export type RegenerateRequest = {
  transcript: boolean;
  summary: boolean;
};

export type SummarySegment = {
  time: string;
  title: string | null;
  text: string;
};

export type MindmapTag = "概念" | "方法" | "反直觉" | "案例" | "事件" | "人物" | "书";

export type MindmapNode = {
  text: string;
  tag: MindmapTag | null;
  children: MindmapNode[];
};

export type WorthItem = {
  type: string;
  title: string;
  by: string | null;
  note: string;
};

export type SummaryData = {
  overview: SummarySegment[];
  mindmap: {
    note: string | null;
    nodes: MindmapNode[];
  };
  worth_following: WorthItem[];
};
