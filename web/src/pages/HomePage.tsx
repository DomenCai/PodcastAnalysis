import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Clock3, FileText, MicVocal, Plus, Search, Sparkles } from "lucide-react";
import { getEpisodes } from "../lib/api";
import { formatDuration } from "../lib/format";
import { navigate } from "../lib/routing";
import type { EpisodeListItem } from "../lib/types";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";

function EpisodeCard({ episode }: { episode: EpisodeListItem }) {
  return (
    <button className="episode-card group" onClick={() => navigate(`/episodes/${episode.id}`)}>
      <div className="flex min-w-0 items-start gap-3">
        <span className="episode-cover">
          <MicVocal className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="item-title line-clamp-2 text-base leading-snug">
            {episode.title || episode.id}
          </h2>
          <p className="mt-1 truncate text-sm text-muted">{episode.podcast_title || "未知播客"}</p>
        </div>
      </div>

      <div className="mt-auto flex flex-wrap items-center gap-2 text-xs">
        <span className="chip chip-neutral">
          <Clock3 className="h-3.5 w-3.5" />
          {formatDuration(episode.duration)}
        </span>
        <span className={episode.has_transcript ? "chip chip-success" : "chip chip-neutral"}>
          <FileText className="h-3.5 w-3.5" />
          {episode.has_transcript ? "已转录" : "未转录"}
        </span>
        <span className={episode.has_summary ? "chip chip-success" : "chip chip-neutral"}>
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
  const [query, setQuery] = useState("");

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

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return episodes;
    return episodes.filter(
      (item) =>
        item.title?.toLowerCase().includes(keyword) ||
        item.podcast_title?.toLowerCase().includes(keyword)
    );
  }, [episodes, query]);

  return (
    <section className="space-y-7">
      <div className="page-header flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="page-title">节目库</h1>
          <p className="page-subtitle mt-1 text-sm">本地已处理节目：{episodes.length} 集</p>
        </div>
        <div className="flex items-center gap-3">
          {episodes.length > 0 && (
            <label className="search-field">
              <Search className="search-icon" />
              <input
                className="text-input"
                type="search"
                value={query}
                placeholder="搜索节目…"
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
          )}
          <button className="primary-button" onClick={() => navigate("/new")}>
            <Plus className="h-4 w-4" />
            新建处理
          </button>
        </div>
      </div>

      {loading && <LoadingState label="正在读取节目库" />}
      {error && <ErrorState message={error} />}

      {!loading && !error && episodes.length === 0 && (
        <div className="panel flex flex-col items-center gap-4 p-12 text-center">
          <span className="episode-cover h-14 w-14">
            <MicVocal className="h-6 w-6" />
          </span>
          <div>
            <p className="section-title">暂无节目</p>
            <p className="mt-1 text-sm text-muted">开始你的第一次分析吧，粘贴小宇宙节目链接即可。</p>
          </div>
          <button className="primary-button" onClick={() => navigate("/new")}>
            <Plus className="h-4 w-4" />
            新建处理
          </button>
        </div>
      )}

      {!loading && !error && episodes.length > 0 && filtered.length === 0 && (
        <div className="empty-panel">没有匹配「{query}」的节目</div>
      )}

      {!loading && !error && filtered.length > 0 && (
        <div className="episode-grid">
          {filtered.map((episode) => (
            <EpisodeCard key={episode.id} episode={episode} />
          ))}
        </div>
      )}
    </section>
  );
}
