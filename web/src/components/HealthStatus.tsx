import type { Health } from "../lib/types";

export function getBlockingHealthIssues(health: Health | null): string[] {
  if (!health) {
    return ["无法读取环境状态"];
  }

  const issues: string[] = [];
  if (!health.ffmpeg) issues.push("缺少 ffmpeg");
  if (!health.ffprobe) issues.push("缺少 ffprobe");
  if (!health.output_writable) issues.push("输出目录不可写");
  if (!health.mimo_key) issues.push("缺少 MIMO_API_KEY");
  return issues;
}
