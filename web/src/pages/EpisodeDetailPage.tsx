import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ChevronDown,
  ChevronUp,
  Download,
  Loader2,
  RotateCcw,
  Trash2,
  X
} from "lucide-react";
import {
  deleteEpisode,
  getEpisode,
  getSummary,
  getTask,
  getTranscript,
  regenerateEpisode
} from "../lib/api";
import { formatDuration, getDescription, stageLabel, stageProgressText } from "../lib/format";
import type { EpisodeDetail, SummaryData, TaskState } from "../lib/types";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { SummaryView } from "../components/SummaryView";
import { AudioProgressBar } from "../components/AudioProgressBar";
import { navigate } from "../lib/routing";

type TranscriptLine = {
  time: string | null;
  seconds: number | null;
  content: string;
};

type DialogMode = "delete" | "regenerate";
type DetailTab = "transcript" | "summary";

function timeToSeconds(time: string | null): number | null {
  if (!time) return null;
  const match = time.match(/(\d{2}):(\d{2}):(\d{2})/);
  if (!match) return null;
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
}

function EpisodeDescription({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const canToggle = text.length > 180 || text.includes("\n");
  const ToggleIcon = expanded ? ChevronUp : ChevronDown;
  const toggleButton = (
    <button
      type="button"
      className="inline-flex items-center gap-1 text-sm font-medium text-accent"
      aria-expanded={expanded}
      onClick={() => setExpanded((value) => !value)}
    >
      {expanded ? "收起全文" : "展开全文"}
      <ToggleIcon className="h-4 w-4" />
    </button>
  );

  return (
    <div className="mt-3 max-w-4xl">
      {canToggle && expanded && <div className="mb-2">{toggleButton}</div>}
      <p className={`${expanded ? "" : "line-clamp-4"} whitespace-pre-wrap text-sm leading-7 text-soft`}>
        {text}
      </p>
      {canToggle && !expanded && <div className="mt-2">{toggleButton}</div>}
    </div>
  );
}

function TranscriptBlock({
  text,
  activeTime,
  follow,
  onSeek
}: {
  text: string;
  activeTime: number;
  follow: boolean;
  onSeek: (seconds: number) => void;
}) {
  const paragraphs = useMemo<TranscriptLine[]>(
    () =>
      text
        .split(/\n\s*\n/)
        .map((item) => item.trim())
        .filter(Boolean)
        .map((paragraph) => {
          const match = paragraph.match(/^(\[\d{2}:\d{2}:\d{2}\])\s*(.*)$/s);
          const time = match ? match[1] : null;
          return { time, seconds: timeToSeconds(time), content: match ? match[2] : paragraph };
        }),
    [text]
  );

  const activeIndex = useMemo(() => {
    let idx = 0;
    for (let i = 0; i < paragraphs.length; i += 1) {
      const seconds = paragraphs[i].seconds;
      if (seconds != null && seconds <= activeTime) idx = i;
    }
    return idx;
  }, [paragraphs, activeTime]);

  const activeRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (follow) {
      activeRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [activeIndex, follow]);

  if (paragraphs.length === 0) {
    return <div className="empty-panel">暂无逐字稿内容</div>;
  }

  return (
    <div className="transcript-list">
      {paragraphs.map((paragraph, index) => {
        const isActive = index === activeIndex;
        const seekable = paragraph.seconds != null;
        return (
          <div
            key={`${index}-${paragraph.content.slice(0, 16)}`}
            ref={isActive ? activeRef : null}
            role={seekable ? "button" : undefined}
            tabIndex={seekable ? 0 : undefined}
            onClick={seekable ? () => onSeek(paragraph.seconds as number) : undefined}
            onKeyDown={
              seekable
                ? (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSeek(paragraph.seconds as number);
                    }
                  }
                : undefined
            }
            className={
              isActive
                ? "transcript-row transcript-row-active"
                : seekable
                  ? "transcript-row transcript-row-seekable"
                  : "transcript-row"
            }
          >
            <div className="transcript-time">{paragraph.time || "--:--:--"}</div>
            <p className="transcript-paragraph">{paragraph.content}</p>
          </div>
        );
      })}
    </div>
  );
}

function DownloadLink({
  href,
  children,
  disabled
}: {
  href: string;
  children: string;
  disabled?: boolean;
}) {
  if (disabled) {
    return (
      <span className="secondary-button disabled-link">
        <Download className="h-4 w-4" />
        {children}
      </span>
    );
  }

  return (
    <a className="secondary-button" href={href} download>
      <Download className="h-4 w-4" />
      {children}
    </a>
  );
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

function TabButton({
  active,
  children,
  onClick
}: {
  active: boolean;
  children: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      className="tab-button"
      data-active={active ? "true" : undefined}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export function EpisodeDetailPage({ id }: { id: string }) {
  const [episode, setEpisode] = useState<EpisodeDetail | null>(null);
  const [transcript, setTranscript] = useState<string | null>(null);
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<DialogMode | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [regenerateTranscript, setRegenerateTranscript] = useState(false);
  const [regenerateSummary, setRegenerateSummary] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [task, setTask] = useState<TaskState | null>(null);
  const [pendingTab, setPendingTab] = useState<DetailTab>("transcript");
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [activeTab, setActiveTab] = useState<DetailTab>("transcript");
  const seekRef = useRef<((seconds: number) => void) | null>(null);

  function seekTo(seconds: number) {
    seekRef.current?.(seconds);
    setCurrentTime(seconds);
  }

  const loadDetails = useCallback(
    async (isActive: () => boolean = () => true) => {
      setLoading(true);
      setError(null);
      setTranscript(null);
      setSummary(null);

      try {
        const meta = await getEpisode(id);
        if (!isActive()) return;
        setEpisode(meta);

        const [transcriptText, summaryText] = await Promise.all([
          meta.has_transcript ? getTranscript(id) : Promise.resolve(null),
          meta.has_summary ? getSummary(id) : Promise.resolve(null)
        ]);

        if (!isActive()) return;
        setTranscript(transcriptText);
        setSummary(summaryText);
      } catch (err: unknown) {
        if (isActive()) setError(errorMessage(err, "节目详情加载失败"));
      } finally {
        if (isActive()) setLoading(false);
      }
    },
    [id]
  );

  useEffect(() => {
    let active = true;
    void loadDetails(() => active);

    return () => {
      active = false;
    };
  }, [loadDetails]);

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
          if (nextTask.status === "done") {
            setTaskId(null);
            setTask(null);
            setActionError(null);
            setActiveTab(pendingTab);
            void loadDetails();
            return;
          }
          if (nextTask.status === "error") {
            setTaskId(null);
            setActionError(nextTask.error || "重新生成失败");
            return;
          }
          timer = window.setTimeout(poll, 1500);
        })
        .catch((err: unknown) => {
          if (!active) return;
          setTaskId(null);
          setActionError(errorMessage(err, "任务状态读取失败"));
        });
    };

    poll();

    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [loadDetails, pendingTab, taskId]);

  function openDialog(mode: DialogMode) {
    setActionError(null);
    setDialog(mode);
    if (mode === "regenerate") {
      setRegenerateTranscript(false);
      setRegenerateSummary(false);
    }
  }

  const closeDialog = useCallback(() => {
    if (deleting || regenerating) return;
    setDialog(null);
  }, [deleting, regenerating]);

  useEffect(() => {
    if (!dialog) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeDialog();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [dialog, closeDialog]);

  async function confirmDelete() {
    setDeleting(true);
    setActionError(null);
    try {
      await deleteEpisode(id);
      navigate("/");
    } catch (err: unknown) {
      setActionError(errorMessage(err, "删除失败"));
    } finally {
      setDeleting(false);
    }
  }

  async function confirmRegenerate() {
    if (!regenerateTranscript && !regenerateSummary) {
      setActionError("请选择需要重新生成的内容");
      return;
    }

    setRegenerating(true);
    setActionError(null);
    try {
      const result = await regenerateEpisode(id, {
        transcript: regenerateTranscript,
        summary: regenerateSummary
      });
      setPendingTab(regenerateSummary ? "summary" : "transcript");
      setTaskId(result.task_id);
      setTask({
        task_id: result.task_id,
        episode_id: id,
        stage: regenerateTranscript ? "transcribing" : "summarizing",
        done: null,
        total: null,
        status: "running",
        error: null
      });
      setDialog(null);
    } catch (err: unknown) {
      setActionError(errorMessage(err, "重新生成失败"));
    } finally {
      setRegenerating(false);
    }
  }

  if (loading) {
    return <LoadingState label="正在读取节目详情" />;
  }

  if (error || !episode) {
    return <ErrorState message={error || "节目不存在"} />;
  }

  const description = getDescription(episode);
  const actionBusy = deleting || regenerating || task?.status === "running";
  const canRegenerateSummary = episode.has_transcript || regenerateTranscript;
  const runningTaskProgress = task?.status === "running" ? stageProgressText(task) : null;

  return (
    <article className={episode.has_audio ? "space-y-7 pb-36 sm:pb-24" : "space-y-7"}>
      <div className="page-header">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <button className="secondary-button" onClick={() => navigate("/")}>
            <ArrowLeft className="h-4 w-4" />
            节目库
          </button>
          <span className="chip chip-neutral">{formatDuration(episode.duration)}</span>
          {episode.has_transcript && <span className="chip chip-success">已转录</span>}
          {episode.has_summary && <span className="chip chip-success">已摘要</span>}
          <div className="episode-header-actions">
            <button
              type="button"
              className="icon-button"
              aria-label="重新生成"
              title="重新生成"
              disabled={actionBusy}
              onClick={() => openDialog("regenerate")}
            >
              <RotateCcw className="h-4 w-4" />
            </button>
            <button
              type="button"
              className="icon-button icon-button-danger"
              aria-label="删除"
              title="删除"
              disabled={actionBusy}
              onClick={() => openDialog("delete")}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="text-sm text-muted">{episode.podcast_title || "未知播客"}</div>
        <h1 className="mt-3 max-w-5xl font-serif text-3xl font-medium leading-tight tracking-normal text-[var(--color-text)] md:text-4xl">
          {episode.title || episode.id}
        </h1>
        {description && <EpisodeDescription text={description} />}

        <div className="mt-5 flex flex-wrap gap-2">
          <DownloadLink href={`/api/episodes/${id}/audio`} disabled={!episode.has_audio}>
            audio.m4a
          </DownloadLink>
          <DownloadLink href={`/api/episodes/${id}/transcript`} disabled={!episode.has_transcript}>
            transcript.txt
          </DownloadLink>
          <DownloadLink href={`/api/episodes/${id}/summary.md`} disabled={!episode.has_summary}>
            summary.md
          </DownloadLink>
        </div>

        {task?.status === "running" && (
          <div className="notice chip-neutral mt-4">
            <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
            <span>
              正在重新生成：{stageLabel(task.stage)}
              {runningTaskProgress ? `（${runningTaskProgress}）` : ""}
            </span>
          </div>
        )}
        {actionError && !dialog && (
          <div className="notice chip-danger mt-4">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{actionError}</span>
          </div>
        )}
      </div>

      <section className="space-y-4">
        <div className="tab-list" role="tablist" aria-label="节目详情内容">
          <TabButton active={activeTab === "transcript"} onClick={() => setActiveTab("transcript")}>
            逐字稿
          </TabButton>
          <TabButton active={activeTab === "summary"} onClick={() => setActiveTab("summary")}>
            内容摘要
          </TabButton>
        </div>

        {activeTab === "transcript" ? (
          <div className="content-panel" role="tabpanel">
            {transcript ? (
              <TranscriptBlock
                text={transcript}
                activeTime={currentTime}
                follow={playing}
                onSeek={seekTo}
              />
            ) : (
              <div className="empty-panel">未生成逐字稿</div>
            )}
          </div>
        ) : (
          <div className="content-panel" role="tabpanel">
            {summary ? (
              <SummaryView data={summary} />
            ) : (
              <div className="empty-panel">未生成摘要</div>
            )}
          </div>
        )}
      </section>

      <AudioProgressBar
        key={id}
        episodeId={id}
        hasAudio={episode.has_audio}
        title={episode.title || episode.id}
        onTime={setCurrentTime}
        onPlayingChange={setPlaying}
        onReady={(controls) => {
          seekRef.current = controls.seek;
        }}
      />

      {dialog === "delete" && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget) closeDialog();
          }}
        >
          <div className="modal-panel" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="delete-dialog-title" className="section-title">删除节目</h2>
                <p className="mt-2 text-sm text-soft">
                  这会删除本地 output/{id} 下的音频、逐字稿、摘要和元数据。
                </p>
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label="关闭"
                title="关闭"
                disabled={deleting}
                onClick={closeDialog}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {actionError && (
              <div className="notice chip-danger mt-4">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{actionError}</span>
              </div>
            )}
            <div className="modal-actions">
              <button type="button" className="secondary-button" disabled={deleting} onClick={closeDialog}>
                取消
              </button>
              <button type="button" className="danger-button" disabled={deleting} onClick={confirmDelete}>
                {deleting && <Loader2 className="h-4 w-4 animate-spin" />}
                删除
              </button>
            </div>
          </div>
        </div>
      )}

      {dialog === "regenerate" && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget) closeDialog();
          }}
        >
          <div className="modal-panel" role="dialog" aria-modal="true" aria-labelledby="regenerate-dialog-title">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="regenerate-dialog-title" className="section-title">重新生成</h2>
                <p className="mt-2 text-sm text-soft">会复用当前 audio.m4a，不会重新下载音频。</p>
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label="关闭"
                title="关闭"
                disabled={regenerating}
                onClick={closeDialog}
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-5 grid grid-cols-2 gap-3">
              <label className={episode.has_audio ? "dialog-check-row" : "dialog-check-row dialog-check-row-disabled"}>
                <input
                  className="theme-checkbox"
                  type="checkbox"
                  checked={regenerateTranscript}
                  disabled={!episode.has_audio || regenerating}
                  onChange={(event) => {
                    const checked = event.target.checked;
                    setRegenerateTranscript(checked);
                    if (!checked && !episode.has_transcript) {
                      setRegenerateSummary(false);
                    }
                  }}
                />
                <span>逐字稿</span>
              </label>
              <label className={canRegenerateSummary ? "dialog-check-row" : "dialog-check-row dialog-check-row-disabled"}>
                <input
                  className="theme-checkbox"
                  type="checkbox"
                  checked={regenerateSummary}
                  disabled={!canRegenerateSummary || regenerating}
                  onChange={(event) => setRegenerateSummary(event.target.checked)}
                />
                <span>摘要</span>
              </label>
            </div>

            {actionError && (
              <div className="notice chip-danger mt-4">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{actionError}</span>
              </div>
            )}
            <div className="modal-actions">
              <button type="button" className="secondary-button" disabled={regenerating} onClick={closeDialog}>
                取消
              </button>
              <button
                type="button"
                className="primary-button"
                disabled={regenerating || (!regenerateTranscript && !regenerateSummary)}
                onClick={confirmRegenerate}
              >
                {regenerating && <Loader2 className="h-4 w-4 animate-spin" />}
                重新生成
              </button>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}
