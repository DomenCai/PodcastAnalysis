import {
  ArrowLeft,
  ExternalLink,
  FileUp,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, messageOf } from "../lib/api";
import type {
  ArtifactName,
  Health,
  Job,
  ProcessingOptions as Options,
} from "../lib/types";
import { backendLabel, formatDate, stageLabel } from "../lib/format";
import { navigate } from "../lib/routing";
import { ArtifactReader } from "../components/ArtifactReader";
import { ProcessingOptions } from "../components/ProcessingOptions";
import { StatusBadge } from "../components/Status";
import { ErrorState, Loading } from "../components/States";

const POLL_MS = 2500;

export function JobDetailPage({ id, health }: { id: string; health: Health }) {
  const [job, setJob] = useState<Job | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState<string | null>(null),
    [actionError, setActionError] = useState<string | null>(null),
    [busy, setBusy] = useState(false),
    [needsUpload, setNeedsUpload] = useState(false),
    [pollKey, setPollKey] = useState(0);
  const [options, setOptions] = useState<Options>({
    backend: "qwen",
    skip_diarization: true,
    num_speakers: null,
  });
  const refresh = useCallback(async () => {
    const data = await api.job(id);
    setJob(data);
    setOptions({
      backend: data.backend,
      skip_diarization: data.skip_diarization,
      num_speakers: data.num_speakers,
    });
    return data;
  }, [id]);
  useEffect(() => {
    let live = true,
      timer: number | undefined;
    const poll = async () => {
      try {
        const data = await api.job(id);
        if (!live) return;
        setJob(data);
        setOptions({
          backend: data.backend,
          skip_diarization: data.skip_diarization,
          num_speakers: data.num_speakers,
        });
        setLoading(false);
        if (data.status === "queued" || data.status === "running")
          timer = window.setTimeout(poll, POLL_MS);
      } catch (err) {
        if (live) {
          setError(messageOf(err, "任务加载失败"));
          setLoading(false);
        }
      }
    };
    void poll();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [id, pollKey]);
  const loadFile = useCallback(
    (name: ArtifactName) => api.jobFile(id, name),
    [id],
  );
  async function retry(resume = false) {
    setBusy(true);
    setActionError(null);
    setNeedsUpload(false);
    try {
      const result = await api.retryJob(id, resume ? {} : options);
      if (result.job_id !== id) {
        navigate(`/jobs/${result.job_id}`);
        return;
      }
      await refresh();
      setPollKey((value) => value + 1);
    } catch (err) {
      setActionError(messageOf(err, "重试失败"));
      setNeedsUpload(err instanceof ApiError && err.status === 409);
    } finally {
      setBusy(false);
    }
  }
  async function analyze() {
    setBusy(true);
    setActionError(null);
    try {
      const result = await api.analyzeJob(id);
      if (result.job_id !== id) {
        navigate(`/jobs/${result.job_id}`);
        return;
      }
      await refresh();
      setPollKey((value) => value + 1);
    } catch (err) {
      setActionError(messageOf(err, "分析任务提交失败"));
    } finally {
      setBusy(false);
    }
  }
  if (loading) return <Loading label="正在读取任务" />;
  if (error || !job) return <ErrorState message={error || "任务不存在"} />;
  const active = job.status === "queued" || job.status === "running";
  const terminal = job.status === "done" || job.status === "error";
  const hasTranscript = job.available_files.includes("transcript.txt");
  const missingAnalysis = ["article.md", "notes.md", "mindmap.md"].some(
    (name) => !job.available_files.includes(name),
  );
  return (
    <section className="stack-xl">
      <button className="back" onClick={() => navigate("/jobs")}>
        <ArrowLeft size={16} />
        返回任务列表
      </button>
      <header className="detail-head">
        <div>
          <div className="title-badges">
            <StatusBadge status={job.status} />
            <span className="badge neutral">{backendLabel(job.backend)}</span>
          </div>
          <h1>{job.episode?.title || job.filename}</h1>
          <p>
            {job.episode?.podcast_title || job.filename} · 创建于{" "}
            {formatDate(job.created_at)}
          </p>
        </div>
        {job.episode_url && (
          <a
            className="secondary"
            href={job.episode_url}
            target="_blank"
            rel="noreferrer"
          >
            在小宇宙查看 <ExternalLink size={15} />
          </a>
        )}
      </header>
      {active && (
        <div className="progress-panel">
          <span className="pulse" />
          <div>
            <strong>{stageLabel(job.stage)}</strong>
            <p>
              {job.status === "queued"
                ? "任务将在当前任务结束后开始。"
                : "页面会自动更新，请放心离开后再回来。"}
            </p>
          </div>
        </div>
      )}
      {job.status === "error" && (
        <ErrorState message={job.error || "处理失败"} />
      )}
      {actionError && (
        <ErrorState
          message={actionError}
          action={
            needsUpload ? (
              <button className="danger-link" onClick={() => navigate("/new")}>
                <FileUp size={15} />
                重新上传
              </button>
            ) : undefined
          }
        />
      )}
      {terminal && hasTranscript && (
        <div className="analysis-callout">
          <Sparkles size={20} />
          <span>
            <strong>
              {missingAnalysis ? "补齐文章、笔记与导图" : "仅重新生成文章、笔记与导图"}
            </strong>
            <p>
              复用现有逐字稿，只生成 article.md、notes.md 和
              mindmap.md，不会重新转写。
            </p>
          </span>
          <button className="secondary" onClick={analyze} disabled={busy}>
            {busy ? "提交中…" : "仅重新分析"}
          </button>
        </div>
      )}
      {terminal && job.episode_url && (
        <div className="panel stack-lg">
          <div>
            <h2 className="form-title">从节目链接重新转写</h2>
            <p className="form-help">
              可更换模型或说话人配置；这会重新获取节目音频并完整执行转写与内容
              分析。
            </p>
          </div>
          <ProcessingOptions
            value={options}
            health={health}
            disabled={busy}
            onChange={setOptions}
          />
          <button
            className="secondary self-start"
            onClick={() => retry()}
            disabled={busy}
          >
            <RefreshCw size={16} />
            {busy ? "提交中…" : "使用这些配置重新转写"}
          </button>
        </div>
      )}
      {job.can_resume_transcription && !job.episode_url && (
        <div className="upload-callout">
          <span><strong>继续已有转录任务</strong><p>复用转录服务保存的进度与结果。</p></span>
          <button className="secondary" disabled={busy} onClick={() => retry(true)}>继续处理</button>
        </div>
      )}
      {terminal && !job.episode_url && !job.can_resume_transcription && (
        <div className="upload-callout">
          <FileUp size={20} />
          <span>
            <strong>重新转写需要再次上传源文件</strong>
            <p>上传任务不会保留音频；新建任务后可重新选择模型和说话人配置。</p>
          </span>
          <button className="secondary" onClick={() => navigate("/new")}>
            重新上传
          </button>
        </div>
      )}
      {(job.status === "done" || job.available_files.length > 0) && (
        <ArtifactReader
          available={job.available_files}
          load={loadFile}
          revision={terminal ? job.updated_at : job.status}
          description={job.episode?.description}
        />
      )}
    </section>
  );
}
