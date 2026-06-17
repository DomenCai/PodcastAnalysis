export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds < 0) {
    return "未知时长";
  }

  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
  }

  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

export function getDescription(meta: { description?: string; shownotes?: string }): string {
  return meta.description?.trim() || meta.shownotes?.trim() || "";
}

export function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    fetching_info: "获取元数据",
    downloading: "下载音频",
    splitting: "切片",
    transcribing: "转录",
    summarizing: "摘要",
    done: "完成",
    error: "失败"
  };
  return labels[stage] || stage;
}
