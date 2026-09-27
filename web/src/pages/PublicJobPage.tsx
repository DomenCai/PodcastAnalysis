import { useCallback, useEffect, useState } from "react";
import { api, messageOf } from "../lib/api";
import type { ArtifactName, PublicJob } from "../lib/types";
import { ArtifactReader } from "../components/ArtifactReader";
import { ErrorState, Loading } from "../components/States";

export function PublicJobPage({ id }: { id: string }) {
  const [job, setJob] = useState<PublicJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setJob(null);
    setError(null);
    api.publicJob(id).then((next) => { if (live) setJob(next); }).catch((err) => { if (live) setError(messageOf(err, "文章加载失败")); });
    return () => { live = false; };
  }, [id]);
  const load = useCallback((name: ArtifactName) => api.publicJobFile(id, name), [id]);
  if (error) return <ErrorState message={error} />;
  if (!job) return <Loading label="正在读取文章" />;
  return <article className="reading stack-xl">
    <header className="reading-head"><span className="eyebrow">PODCAST ARTICLE</span><h1>{job.title}</h1></header>
    <ArtifactReader available={job.available_files} load={load} defaultTab="article" description={job.description} />
  </article>;
}
