import { ArrowLeft, ArrowRight, Clock3, ExternalLink } from "lucide-react";
import { useEffect, useState } from "react";
import { api, messageOf } from "../lib/api";
import type { Subscription, SubscriptionEpisode } from "../lib/types";
import { formatDate, formatDuration } from "../lib/format";
import { navigate } from "../lib/routing";
import { Empty, ErrorState, Loading } from "../components/States";

export function PodcastPage({ id }: { id: number }) {
  const [podcast, setPodcast] = useState<Subscription | null>(null),
    [episodes, setEpisodes] = useState<SubscriptionEpisode[]>([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    Promise.all([api.subscriptions(), api.subscriptionEpisodes(id)])
      .then(([items, rows]) => {
        if (!live) return;
        setPodcast(items.find((item) => item.id === id) ?? null);
        setEpisodes(rows);
      })
      .catch((err) => {
        if (live) setError(messageOf(err, "播客加载失败"));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [id]);
  if (loading) return <Loading label="正在读取播客" />;
  if (error || !podcast) return <ErrorState message={error || "播客不存在"} />;
  const readable = episodes.filter((episode) => episode.status === "done");
  return (
    <section className="reading stack-xl">
      <button className="back" onClick={() => navigate("/")}>
        <ArrowLeft size={16} />
        返回播客列表
      </button>
      <header className="podcast-hero">
        <div className="podcast-art large">播</div>
        <div>
          <span className="eyebrow">PODCAST</span>
          <h1>{podcast.title}</h1>
          <p>{podcast.author}</p>
          {podcast.description && (
            <div className="description">{podcast.description}</div>
          )}
          <a href={podcast.source_url} target="_blank" rel="noreferrer">
            在小宇宙查看 <ExternalLink size={14} />
          </a>
        </div>
      </header>
      <div className="section-head">
        <div>
          <h2>全部单集</h2>
          <p>{readable.length} 集可读</p>
        </div>
      </div>
      {readable.length ? (
        <div className="episode-list">
          {readable.map((episode) => (
            <a
              href={`/episodes/${episode.id}/transcript#article`}
              key={episode.id}
              onClick={(event) => {
                event.preventDefault();
                navigate(`/episodes/${episode.id}/transcript#article`);
              }}
            >
              <span>
                <strong>{episode.title}</strong>
                <small>
                  {formatDate(episode.published_at)} <i /> <Clock3 size={13} />{" "}
                  {formatDuration(episode.duration)}
                </small>
              </span>
              <ArrowRight size={17} />
            </a>
          ))}
        </div>
      ) : (
        <Empty
          title="暂无已发布单集"
          description="完成处理的内容会出现在这里。"
        />
      )}
    </section>
  );
}
