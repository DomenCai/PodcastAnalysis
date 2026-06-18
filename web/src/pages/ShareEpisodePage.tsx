import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, FileText, Podcast } from "lucide-react";
import { getEpisode, getSummary, getTranscript } from "../lib/api";
import { formatDuration, getDescription } from "../lib/format";
import type { EpisodeDetail, SummaryData } from "../lib/types";
import { AudioProgressBar } from "../components/AudioProgressBar";
import { EpisodeDescription } from "../components/EpisodeDescription";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { SummaryExploreView, SummaryOverviewView } from "../components/SummaryView";
import { ThemeToggle } from "../components/ThemeToggle";
import { TranscriptBlock } from "../components/TranscriptBlock";

type DetailTab = "transcript" | "summary" | "explore";

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

export function ShareEpisodePage({ id }: { id: string }) {
  const [episode, setEpisode] = useState<EpisodeDetail | null>(null);
  const [transcript, setTranscript] = useState<string | null>(null);
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>("transcript");
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
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
        if (!transcriptText && summaryText) {
          setActiveTab("summary");
        }
      } catch (err: unknown) {
        if (isActive()) setError(errorMessage(err, "分享内容加载失败"));
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

  const description = episode ? getDescription(episode) : "";

  return (
    <div className={episode?.has_audio ? "min-h-screen bg-[var(--color-bg)] pb-36 text-[var(--color-text)] sm:pb-24" : "min-h-screen bg-[var(--color-bg)] text-[var(--color-text)]"}>
      <header className="border-b border-[var(--color-border)] bg-[var(--color-panel-solid)]/80 backdrop-blur">
        <div className="mx-auto flex max-w-[1180px] items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-10">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--color-primary)] text-[var(--color-on-primary)]">
              <Podcast className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <div className="truncate text-base font-semibold">PodcastAnalysis</div>
              <div className="text-xs text-muted">分享阅读</div>
            </div>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto max-w-[1180px] px-4 py-7 sm:px-6 lg:px-10 lg:py-12">
        {loading && <LoadingState label="正在读取分享内容" />}
        {error && <ErrorState message={error} />}

        {!loading && !error && !episode && <ErrorState message="分享内容不存在" />}

        {!loading && !error && episode && (
          <article className="space-y-7">
            <div className="page-header">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <span className="chip chip-neutral">
                  <Clock3 className="h-3.5 w-3.5" />
                  {formatDuration(episode.duration)}
                </span>
                {episode.has_transcript && (
                  <span className="chip chip-success">
                    <FileText className="h-3.5 w-3.5" />
                    已转录
                  </span>
                )}
                {episode.has_summary && (
                  <span className="chip chip-success">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    已摘要
                  </span>
                )}
              </div>

              <div className="text-sm text-muted">{episode.podcast_title || "未知播客"}</div>
              <h1 className="mt-3 max-w-5xl font-serif text-3xl font-medium leading-tight tracking-normal text-[var(--color-text)] md:text-4xl">
                {episode.title || episode.id}
              </h1>
              {description && <EpisodeDescription text={description} />}
            </div>

            {!episode.has_transcript && !episode.has_summary && (
              <div className="notice chip-danger">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>这集还没有可分享的逐字稿或摘要。</span>
              </div>
            )}

            <section className="space-y-4">
              <div className="tab-list" role="tablist" aria-label="分享内容">
                <TabButton active={activeTab === "transcript"} onClick={() => setActiveTab("transcript")}>
                  逐字稿
                </TabButton>
                <TabButton active={activeTab === "summary"} onClick={() => setActiveTab("summary")}>
                  内容摘要
                </TabButton>
                <TabButton active={activeTab === "explore"} onClick={() => setActiveTab("explore")}>
                  导图追踪
                </TabButton>
              </div>

              {activeTab === "transcript" && (
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
              )}

              {activeTab === "summary" && (
                <div className="content-panel" role="tabpanel">
                  {summary ? (
                    <SummaryOverviewView data={summary} />
                  ) : (
                    <div className="empty-panel">未生成摘要</div>
                  )}
                </div>
              )}

              {activeTab === "explore" && (
                <div className="content-panel" role="tabpanel">
                  {summary ? (
                    <SummaryExploreView data={summary} />
                  ) : (
                    <div className="empty-panel">未生成摘要</div>
                  )}
                </div>
              )}
            </section>
          </article>
        )}
      </main>

      {episode && (
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
          fullWidth
        />
      )}
    </div>
  );
}
