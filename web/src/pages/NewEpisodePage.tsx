import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Check,
  CircleAlert,
  Download,
  FileAudio,
  FileText,
  Info,
  Loader2,
  RotateCcw,
  Scissors,
  Sparkles,
  UploadCloud
} from "lucide-react";
import { ApiError, createEpisode, getTask } from "../lib/api";
import type { Health, TaskState } from "../lib/types";
import { stageLabel, stageProgressText } from "../lib/format";
import { getBlockingHealthIssues } from "../components/HealthStatus";
import { navigate } from "../lib/routing";

const EPISODE_URL_RE = /\/episode\/([a-f0-9]+)/;
const POLL_MS = 1500;

const baseStages = [
  { key: "fetching_info", icon: Info },
  { key: "downloading", icon: Download },
  { key: "splitting", icon: Scissors },
  { key: "transcribing", icon: FileText },
  { key: "done", icon: Check }
];

function orderedStages(includeSummary: boolean, currentStage?: string) {
  const stages = [...baseStages];
  if (includeSummary || currentStage === "summarizing") {
    stages.splice(stages.length - 1, 0, { key: "summarizing", icon: Sparkles });
  }
  return stages;
}

function ProgressView({
  task,
  includeSummary,
  onRetry,
  retrying
}: {
  task: TaskState | null;
  includeSummary: boolean;
  onRetry: () => void;
  retrying: boolean;
}) {
  const stages = orderedStages(includeSummary, task?.stage);
  const currentIndex = task ? stages.findIndex((stage) => stage.key === task.stage) : -1;
  const failed = task?.status === "error" || task?.stage === "error";
  const failedIndex = failed && currentIndex >= 0 ? currentIndex : -1;

  return (
    <div className="panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="section-title">处理进度</h2>
        {task?.status === "running" && <Loader2 className="h-5 w-5 animate-spin text-accent" />}
      </div>

      {!task && <p className="mt-2 text-sm text-muted">提交后将在这里显示处理进度。</p>}

      {task && (
        <div className="timeline">
          {stages.map(({ key, icon: Icon }, index) => {
            const allDone = task.status === "done";
            const isFailed = index === failedIndex;
            const done = allDone || (currentIndex > index && currentIndex >= 0);
            const active = !isFailed && !done && task.status === "running" && task.stage === key;
            const detail = active ? stageProgressText(task) : null;
            const failedProgress = isFailed && task.done != null && task.total != null && task.total > 0
              ? ` (${Math.round((task.done / task.total) * 100)}%)`
              : "";

            const dotClass = isFailed
              ? "timeline-dot timeline-dot-error"
              : done
                ? "timeline-dot timeline-dot-done"
                : active
                  ? "timeline-dot timeline-dot-active"
                  : "timeline-dot timeline-dot-idle";

            return (
              <div key={key} className={done ? "timeline-step timeline-step-complete" : "timeline-step"}>
                <span className={dotClass}>
                  {done ? <Check className="h-4 w-4" /> : isFailed ? <CircleAlert className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
                </span>
                <div className="min-w-0">
                  <div className={active || done || isFailed ? "timeline-title" : "timeline-title timeline-title-idle"}>
                    {stageLabel(key)}
                    {failedProgress}
                  </div>
                  {detail && <div className="timeline-detail">{detail}</div>}
                  {isFailed && (
                    <div className="notice chip-danger mt-2 flex-col items-start gap-3">
                      <div className="flex items-start gap-2">
                        <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
                        <span>{task.error || "处理失败，本地已生成的产物会保留。"}</span>
                      </div>
                      <button className="secondary-button" onClick={onRetry} disabled={retrying}>
                        <RotateCcw className="h-4 w-4" />
                        {retrying ? "重试中" : "重试"}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Notice({ tone, children }: { tone: "warn" | "error" | "neutral"; children: string }) {
  const className =
    tone === "error" ? "chip-danger" : tone === "warn" ? "chip-warn" : "chip-neutral";

  return (
    <div className={`notice ${className}`}>
      <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{children}</span>
    </div>
  );
}

export function NewEpisodePage({ health }: { health: Health | null }) {
  const [url, setUrl] = useState("");
  const [summary, setSummary] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [task, setTask] = useState<TaskState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [submittedSummary, setSubmittedSummary] = useState(false);

  const blockers = useMemo(() => getBlockingHealthIssues(health), [health]);
  const llmMissing = health ? !health.llm_key : true;

  useEffect(() => {
    if (llmMissing && summary) {
      setSummary(false);
    }
  }, [llmMissing, summary]);

  useEffect(() => {
    if (!taskId) {
      return;
    }

    let active = true;
    let timer: number | undefined;

    const poll = () => {
      getTask(taskId)
        .then((nextTask) => {
          if (!active) return;
          setTask(nextTask);
          if (nextTask.status === "done" && nextTask.episode_id) {
            navigate(`/episodes/${nextTask.episode_id}`);
            return;
          }
          if (nextTask.status === "running") {
            timer = window.setTimeout(poll, POLL_MS);
          }
        })
        .catch((err: unknown) => {
          if (!active) return;
          setMessage(err instanceof Error ? err.message : "任务状态读取失败");
          timer = window.setTimeout(poll, POLL_MS);
        });
    };

    poll();

    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [taskId]);

  async function startTask() {
    const trimmedUrl = url.trim();
    setMessage(null);

    if (!trimmedUrl) {
      setMessage("请输入小宇宙节目链接");
      return;
    }
    if (!EPISODE_URL_RE.test(trimmedUrl)) {
      setMessage("请输入合法的小宇宙 episode 链接");
      return;
    }
    if (blockers.length > 0) {
      setMessage(blockers.join("、"));
      return;
    }

    setSubmitting(true);
    try {
      const result = await createEpisode(trimmedUrl, summary);
      setSubmittedSummary(summary);
      setTaskId(result.task_id);
      setTask({
        task_id: result.task_id,
        episode_id: null,
        stage: "fetching_info",
        done: null,
        total: null,
        status: "running",
        error: null
      });
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        setMessage("已有任务进行中");
      } else {
        setMessage(err instanceof Error ? err.message : "提交失败");
      }
    } finally {
      setSubmitting(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void startTask();
  }

  const taskRunning = task?.status === "running";
  const submitDisabled = submitting || blockers.length > 0 || taskRunning;

  return (
    <section className="space-y-7">
      <div className="page-header">
        <h1 className="page-title">新建处理</h1>
        <p className="page-subtitle mt-1 text-sm">粘贴小宇宙节目链接，生成本地音频、逐字稿和可选摘要。</p>
      </div>

      <div className="panel">
        <form className="grid gap-4 lg:grid-cols-[minmax(260px,1fr)_auto_auto]" onSubmit={handleSubmit}>
          <label className="min-w-0">
            <span className="field-label">小宇宙节目链接</span>
            <div className="relative">
              <UploadCloud className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" />
              <input
                className="text-input pl-9"
                type="url"
                value={url}
                placeholder="https://www.xiaoyuzhoufm.com/episode/..."
                disabled={taskRunning}
                onChange={(event) => setUrl(event.target.value)}
              />
            </div>
          </label>

          <label className={llmMissing ? "disabled-check self-end pb-2" : "check-row self-end pb-2"}>
            <input
              className="theme-checkbox"
              type="checkbox"
              checked={summary}
              disabled={llmMissing || taskRunning}
              onChange={(event) => setSummary(event.target.checked)}
            />
            <span>生成摘要</span>
          </label>

          <button className="primary-button self-end" disabled={submitDisabled}>
            <FileAudio className="h-4 w-4" />
            {submitting ? "提交中" : "开始处理"}
          </button>
        </form>

        <div className="mt-5 grid gap-3 lg:grid-cols-2">
          {llmMissing && <Notice tone="warn">缺少 LLM_API_KEY，摘要选项不可用，转录仍可继续。</Notice>}
          {blockers.length > 0 && <Notice tone="error">{blockers.join("、")}</Notice>}
          {message && <Notice tone="neutral">{message}</Notice>}
        </div>
      </div>

      <ProgressView
        task={task}
        includeSummary={submittedSummary}
        onRetry={() => void startTask()}
        retrying={submitting}
      />
    </section>
  );
}
