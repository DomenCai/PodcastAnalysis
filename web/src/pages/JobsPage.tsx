import { ArrowRight, Plus, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, messageOf } from "../lib/api";
import type { Job } from "../lib/types";
import { backendLabel, formatDate, stageLabel } from "../lib/format";
import { navigate } from "../lib/routing";
import { StatusBadge } from "../components/Status";
import { Empty, ErrorState, Loading } from "../components/States";

export function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]),
    [query, setQuery] = useState(""),
    [loading, setLoading] = useState(true),
    [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true,
      timer: number | undefined;
    const poll = () =>
      api
        .jobs()
        .then((data) => {
          if (!live) return;
          setJobs(data);
          setLoading(false);
          if (
            data.some(
              (job) => job.status === "queued" || job.status === "running",
            )
          )
            timer = window.setTimeout(poll, 3000);
        })
        .catch((err) => {
          if (live) {
            setError(messageOf(err));
            setLoading(false);
          }
        });
    void poll();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, []);
  const filtered = useMemo(() => {
    const word = query.trim().toLowerCase();
    return word
      ? jobs.filter((job) =>
          `${job.filename} ${job.episode?.title ?? ""}`
            .toLowerCase()
            .includes(word),
        )
      : jobs;
  }, [jobs, query]);
  return (
    <section className="stack-xl">
      <header className="page-head split">
        <div>
          <span className="eyebrow">JOBS</span>
          <h1>任务</h1>
          <p>查看排队、转写、说话人识别与 Agy 分析进度。</p>
        </div>
        <button className="primary" onClick={() => navigate("/new")}>
          <Plus size={17} />
          新建任务
        </button>
      </header>
      {jobs.length > 0 && (
        <label className="search">
          <Search size={17} />
          <input
            type="search"
            placeholder="搜索文件名或单集标题"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      )}
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} />
      ) : !jobs.length ? (
        <Empty title="暂无任务" />
      ) : !filtered.length ? (
        <Empty title="没有匹配的任务" />
      ) : (
        <div className="list-card">
          {filtered.map((job) => (
            <button
              className="list-row roomy"
              key={job.id}
              onClick={() => navigate(`/jobs/${job.id}`)}
            >
              <span className="row-main">
                <strong>{job.episode?.title || job.filename}</strong>
                <small>
                  {backendLabel(job.backend)} · {stageLabel(job.stage)} ·{" "}
                  {formatDate(job.created_at)}
                </small>
              </span>
              <span className="row-options">
                {job.skip_diarization
                  ? "未识别说话人"
                  : `${job.num_speakers ?? "自动"} 位说话人`}
              </span>
              <StatusBadge status={job.status} />
              <ArrowRight size={16} />
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
