import type { Backend, JobStatus, SubscriptionEpisodeStatus } from "./types";

export function formatDate(value?: string | null): string {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatDuration(seconds?: number | null): string {
  if (seconds == null || seconds < 0) return "时长未知";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours} 小时 ${minutes} 分钟` : `${minutes} 分钟`;
}

export const backendLabel = (backend?: Backend) =>
  backend === "qwen" ? "Qwen3-ASR" : backend === "mimo" ? "MiMo" : "Whisper";

export function statusLabel(
  status: JobStatus | SubscriptionEpisodeStatus,
): string {
  return (
    (
      {
        queued: "排队中",
        running: "处理中",
        done: "已完成",
        error: "失败",
        pending: "等待中",
        awaiting: "待确认",
        processing: "处理中",
        failed: "失败",
        ignored: "已忽略",
        skipped: "已跳过",
      } as Record<string, string>
    )[status] ?? status
  );
}

export function stageLabel(stage: string): string {
  return (
    (
      {
        queued: "等待单任务 worker",
        starting: "准备处理",
        archiving: "归档上一版产物",
        fetching: "获取节目与音频",
        downloading: "获取音频",
        converting: "转换音频格式",
        transcribing: "转写与错字清理",
        diarizing: "识别说话人",
        analyzing: "生成文章、笔记与导图",
        done: "处理完成",
        error: "处理失败",
      } as Record<string, string>
    )[stage] ?? stage
  );
}
