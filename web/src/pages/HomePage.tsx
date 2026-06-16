import { useEffect, useState } from "react";
import { CheckCircle2, Clock3, FileText, ListMusic, Plus, Sparkles } from "lucide-react";
import { getEpisodes } from "../lib/api";
import { formatDuration } from "../lib/format";
import { navigate } from "../lib/routing";
import type { EpisodeListItem } from "../lib/types";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";

function EpisodeCard({ episode }: { episode: EpisodeListItem }) {
  return (
    <button
      className="card-button group grid w-full gap-5 p-5 md:grid-cols-[minmax(0,1fr)_auto]"
      onClick={() => navigate(`/episodes/${episode.id}`)}
    >
      <div className="min-w-0 space-y-2">
        <div className="flex min-w-0 items-center gap-2 text-sm text-muted">
          <ListMusic className="h-4 w-4 shrink-0 text-faint" />
          <span className="truncate">{episode.podcast_title || "未知播客"}</span>
        </div>
        <h2 className="item-title line-clamp-2 text-lg leading-snug">
          {episode.title || episode.id}
        </h2>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs md:justify-end">
        <span className="chip chip-neutral">
          <Clock3 className="h-3.5 w-3.5" />
          {formatDuration(episode.duration)}
        </span>
        <span
          className={episode.has_transcript ? "chip chip-success" : "chip chip-neutral"}
        >
          <FileText className="h-3.5 w-3.5" />
          {episode.has_transcript ? "已转录" : "未转录"}
        </span>
        <span
          className={episode.has_summary ? "chip chip-success" : "chip chip-neutral"}
        >
          {episode.has_summary ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
          {episode.has_summary ? "已摘要" : "未摘要"}
        </span>
      </div>
    </button>
  );
}

export function HomePage() {
  const [episodes, setEpisodes] = useState<EpisodeListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    getEpisodes()
      .then((items) => {
        if (active) setEpisodes(items);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : "节目库加载失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  return (
    <section className="space-y-7">
      <div className="page-header flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="page-title">节目库</h1>
          <p className="page-subtitle mt-1 text-sm">本地已处理节目：{episodes.length} 集</p>
        </div>
        <button className="primary-button" onClick={() => navigate("/new")}>
          <Plus className="h-4 w-4" />
          新建处理
        </button>
      </div>

      {loading && <LoadingState label="正在读取节目库" />}
      {error && <ErrorState message={error} />}

      {!loading && !error && episodes.length === 0 && (
        <div className="panel p-10 text-center text-sm text-muted">
          暂无已处理节目
        </div>
      )}

      {!loading && !error && episodes.length > 0 && (
        <div className="space-y-4">
          {episodes.map((episode) => (
            <EpisodeCard key={episode.id} episode={episode} />
          ))}
        </div>
      )}
    </section>
  );
}
