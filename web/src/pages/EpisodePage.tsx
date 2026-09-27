import { ExternalLink } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, messageOf } from "../lib/api";
import type { ArtifactName, PublicEpisode } from "../lib/types";
import { formatDate, formatDuration } from "../lib/format";
import { ArtifactReader } from "../components/ArtifactReader";
import { ErrorState, Loading } from "../components/States";

export function EpisodePage({ id }: { id: number }) {
  const [episode, setEpisode] = useState<PublicEpisode | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api
      .episode(id)
      .then((data) => {
        if (live) setEpisode(data);
      })
      .catch((err) => {
        if (live) setError(messageOf(err, "单集加载失败"));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [id]);
  const loadFile = useCallback(
    (name: ArtifactName) => api.episodeFile(id, name),
    [id],
  );
  if (loading) return <Loading label="正在读取单集" />;
  if (error || !episode)
    return <ErrorState message={error || "单集不存在或尚未公开"} />;
  return (
    <article className="reading stack-xl">
      <header className="reading-head">
        <span className="eyebrow">PODCAST EPISODE</span>
        <h1>{episode.title}</h1>
        <div>
          <span>{formatDate(episode.published_at)}</span>
          <i /> <span>{formatDuration(episode.duration)}</span>
        </div>
        {episode.episode_url && (
          <a href={episode.episode_url} target="_blank" rel="noreferrer">
            在小宇宙查看原节目 <ExternalLink size={14} />
          </a>
        )}
      </header>
      {episode.has_result ? (
        <ArtifactReader
          available={episode.available_files}
          load={loadFile}
          defaultTab="article"
          description={episode.description}
        />
      ) : (
        <ErrorState message="这期节目还没有可公开阅读的内容" />
      )}
    </article>
  );
}
