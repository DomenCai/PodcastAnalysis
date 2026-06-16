import type { Health } from "../lib/types";

type Props = {
  health: Health | null;
  loading: boolean;
  error: string | null;
};

const labels: Record<keyof Health, string> = {
  ffmpeg: "ffmpeg",
  ffprobe: "ffprobe",
  output_writable: "output",
  mimo_key: "MIMO",
  llm_key: "LLM"
};

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

export function HealthStatus({ health, loading, error }: Props) {
  if (loading) {
    return <div className="status-chip chip-neutral">环境检查中</div>;
  }

  if (error || !health) {
    return (
      <div className="status-chip chip-danger">
        环境状态不可用
      </div>
    );
  }

  const values = Object.entries(health) as Array<[keyof Health, boolean]>;
  const ok = values.every(([, value]) => value);

  return (
    <div
      className={
        ok
          ? "status-chip chip-success"
          : "status-chip chip-warn"
      }
      title={values.map(([key, value]) => `${labels[key]}: ${value ? "ok" : "missing"}`).join(" / ")}
    >
      {ok ? "环境就绪" : "环境缺项"}
    </div>
  );
}
