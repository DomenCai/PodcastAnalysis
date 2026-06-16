import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import { ArrowLeft, ChevronDown, ChevronUp, Download } from "lucide-react";
import { getEpisode, getSummary, getTranscript } from "../lib/api";
import { formatDuration, getDescription } from "../lib/format";
import type { EpisodeDetail } from "../lib/types";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { WaveformPlayer } from "../components/WaveformPlayer";
import { navigate } from "../lib/routing";

type TranscriptLine = {
  time: string | null;
  content: string;
};

type DetailTab = "transcript" | "summary";

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

function TranscriptBlock({ text }: { text: string }) {
  const paragraphs = useMemo<TranscriptLine[]>(
    () =>
      text
        .split(/\n\s*\n/)
        .map((item) => item.trim())
        .filter(Boolean)
        .map((paragraph) => {
          const match = paragraph.match(/^(\[\d{2}:\d{2}:\d{2}\])\s*(.*)$/s);
          return match ? { time: match[1], content: match[2] } : { time: null, content: paragraph };
        }),
    [text]
  );

  if (paragraphs.length === 0) {
    return <div className="empty-panel">暂无逐字稿内容</div>;
  }

  return (
    <div className="transcript-list">
      {paragraphs.map((paragraph, index) => (
        <div
          key={`${index}-${paragraph.content.slice(0, 16)}`}
          className={index === 0 ? "transcript-row transcript-row-active" : "transcript-row"}
        >
          <div className="transcript-time">{paragraph.time || "--:--:--"}</div>
          <p className="transcript-paragraph">{paragraph.content}</p>
        </div>
      ))}
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
      <span className="secondary-button disabled-link download-button">
        <Download className="h-4 w-4" />
        {children}
      </span>
    );
  }

  return (
    <a className="secondary-button download-button" href={href} download>
      <Download className="h-4 w-4" />
      {children}
    </a>
  );
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
  const [summary, setSummary] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>("transcript");

  useEffect(() => {
    let active = true;

    async function load() {
      setLoading(true);
      setError(null);
      setTranscript(null);
      setSummary(null);

      try {
        const meta = await getEpisode(id);
        if (!active) return;
        setEpisode(meta);

        const [transcriptText, summaryText] = await Promise.all([
          meta.has_transcript ? getTranscript(id) : Promise.resolve(null),
          meta.has_summary ? getSummary(id) : Promise.resolve(null)
        ]);

        if (!active) return;
        setTranscript(transcriptText);
        setSummary(summaryText);
      } catch (err: unknown) {
        if (active) setError(err instanceof Error ? err.message : "节目详情加载失败");
      } finally {
        if (active) setLoading(false);
      }
    }

    load();

    return () => {
      active = false;
    };
  }, [id]);

  if (loading) {
    return <LoadingState label="正在读取节目详情" />;
  }

  if (error || !episode) {
    return <ErrorState message={error || "节目不存在"} />;
  }

  const description = getDescription(episode);

  return (
    <article className="space-y-5">
      <div className="page-header flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0 xl:flex-1">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <button className="secondary-button" onClick={() => navigate("/")}>
              <ArrowLeft className="h-4 w-4" />
              节目库
            </button>
            <span className="chip chip-neutral">
              {formatDuration(episode.duration)}
            </span>
            {episode.has_transcript && (
              <span className="chip chip-success">
                已转录
              </span>
            )}
            {episode.has_summary && (
              <span className="chip chip-success">
                已摘要
              </span>
            )}
          </div>
          <div className="text-sm text-muted">{episode.podcast_title || "未知播客"}</div>
          <h1 className="mt-2 max-w-5xl text-2xl font-semibold leading-snug tracking-normal text-[var(--color-text)]">
            {episode.title || episode.id}
          </h1>
          {description && <EpisodeDescription text={description} />}
        </div>

        <section className="download-panel">
          <h2 className="section-title">下载入口</h2>
          <div className="mt-3 grid gap-2">
            <DownloadLink href={`/api/episodes/${id}/audio`} disabled={!episode.has_audio}>
              audio.m4a
            </DownloadLink>
            <DownloadLink href={`/api/episodes/${id}/transcript`} disabled={!episode.has_transcript}>
              transcript.txt
            </DownloadLink>
            <DownloadLink href={`/api/episodes/${id}/summary`} disabled={!episode.has_summary}>
              summary.md
            </DownloadLink>
          </div>
        </section>
      </div>

      <section className="space-y-4">
        <div className="tab-list" role="tablist" aria-label="节目详情内容">
          <TabButton active={activeTab === "transcript"} onClick={() => setActiveTab("transcript")}>
            音频与逐字稿
          </TabButton>
          <TabButton active={activeTab === "summary"} onClick={() => setActiveTab("summary")}>
            结构化摘要
          </TabButton>
        </div>

        {activeTab === "transcript" ? (
          <div className="min-w-0 space-y-5" role="tabpanel">
            <section className="space-y-3">
              <h2 className="section-title">音频</h2>
              <WaveformPlayer episodeId={id} hasAudio={episode.has_audio} />
            </section>

            <section className="space-y-3">
              <h2 className="section-title">逐字稿</h2>
              <div className="content-panel">
                {transcript ? <TranscriptBlock text={transcript} /> : <div className="empty-panel">未生成逐字稿</div>}
              </div>
            </section>
          </div>
        ) : (
          <section className="space-y-3" role="tabpanel">
            <h2 className="section-title">结构化摘要</h2>
            <div className="content-panel">
              {summary ? (
                <div className="markdown-content">
                  <ReactMarkdown>{summary}</ReactMarkdown>
                </div>
              ) : (
                <div className="empty-panel">未生成摘要</div>
              )}
            </div>
          </section>
        )}
      </section>

    </article>
  );
}
