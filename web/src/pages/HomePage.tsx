import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileText,
  Plus,
  Radio,
  Sparkles,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api, messageOf } from "../lib/api";
import type { Health, Job, Subscription } from "../lib/types";
import { formatDate, stageLabel } from "../lib/format";
import { navigate } from "../lib/routing";
import { StatusBadge } from "../components/Status";
import { Empty, ErrorState, Loading } from "../components/States";

export function HomePage({ health }: { health: Health }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const request = health.read_only
      ? api.subscriptions().then((items) => {
          if (live) setSubscriptions(items);
        })
      : Promise.all([api.jobs(), api.subscriptions()]).then(
          ([nextJobs, nextSubscriptions]) => {
            if (live) {
              setJobs(nextJobs);
              setSubscriptions(nextSubscriptions);
            }
          },
        );
    request
      .catch((err) => {
        if (live) setError(messageOf(err, "首页加载失败"));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [health.read_only]);
  if (loading) return <Loading label="正在读取播客内容" />;
  if (error) return <ErrorState message={error} />;

  if (health.read_only)
    return (
      <section>
        <header className="page-head">
          <div>
            <span className="eyebrow">PUBLIC LIBRARY</span>
            <h1>播客阅读</h1>
            <p>从逐字稿到文章、笔记与思维导图，安静地读完一期播客。</p>
          </div>
        </header>
        <PodcastGrid subscriptions={subscriptions} />
      </section>
    );

  const active = jobs.filter(
    (job) => job.status === "queued" || job.status === "running",
  );
  const complete = jobs.filter((job) => job.status === "done").length;
  return (
    <section className="stack-xl">
      <header className="page-head split">
        <div>
          <span className="eyebrow">LOCAL WORKSPACE</span>
          <h1>工作台</h1>
          <p>默认使用 Qwen3-ASR 转写，自动生成文章、笔记和思维导图。</p>
        </div>
        <button className="primary" onClick={() => navigate("/new")}>
          <Plus size={17} />
          新建任务
        </button>
      </header>
      <div className="metric-grid">
        <div className="metric">
          <Clock3 />
          <span>
            <b>{active.length}</b>
            <small>处理中</small>
          </span>
        </div>
        <div className="metric">
          <CheckCircle2 />
          <span>
            <b>{complete}</b>
            <small>已完成任务</small>
          </span>
        </div>
        <div className="metric">
          <Radio />
          <span>
            <b>{subscriptions.filter((item) => item.enabled).length}</b>
            <small>活跃订阅</small>
          </span>
        </div>
        <div className="metric">
          <Sparkles />
          <span>
            <b>{health.analysis?.available ? "就绪" : "不可用"}</b>
            <small>{health.analysis?.backend === "pi" ? "Pi · K3 分析" : "Agy 分析"}</small>
          </span>
        </div>
      </div>
      <section>
        <div className="section-head">
          <div>
            <h2>最近任务</h2>
            <p>单任务 worker 按顺序处理</p>
          </div>
          <button className="text-button" onClick={() => navigate("/jobs")}>
            查看全部 <ArrowRight size={15} />
          </button>
        </div>
        {jobs.length ? (
          <div className="list-card">
            {jobs.slice(0, 5).map((job) => (
              <button
                className="list-row"
                key={job.id}
                onClick={() => navigate(`/jobs/${job.id}`)}
              >
                <FileText size={18} />
                <span className="row-main">
                  <strong>
                    {job.episode?.title || job.filename || "未命名任务"}
                  </strong>
                  <small>
                    {stageLabel(job.stage)} · {formatDate(job.updated_at)}
                  </small>
                </span>
                <StatusBadge status={job.status} />
                <ArrowRight size={16} />
              </button>
            ))}
          </div>
        ) : (
          <Empty
            title="还没有任务"
            description="上传音频或粘贴小宇宙单集链接开始。"
          />
        )}
      </section>
      <section>
        <div className="section-head">
          <div>
            <h2>播客订阅</h2>
            <p>自动发现并处理新单集</p>
          </div>
          <button
            className="text-button"
            onClick={() => navigate("/subscriptions")}
          >
            管理订阅 <ArrowRight size={15} />
          </button>
        </div>
        <PodcastGrid subscriptions={subscriptions} />
      </section>
    </section>
  );
}

export function PodcastGrid({
  subscriptions,
}: {
  subscriptions: Subscription[];
}) {
  if (!subscriptions.length)
    return (
      <Empty title="暂无可读播客" description="内容发布后会出现在这里。" />
    );
  return (
    <div className="podcast-grid">
      {subscriptions.map((item) => (
        <a
          href={`/podcasts/${item.id}`}
          className="podcast-card"
          key={item.id}
          onClick={(event) => {
            event.preventDefault();
            navigate(`/podcasts/${item.id}`);
          }}
        >
          <span className="podcast-art">
            <Radio size={24} />
          </span>
          <div>
            <h2>{item.title || "未命名播客"}</h2>
            <p>{item.author || "小宇宙播客"}</p>
          </div>
          <small>{item.done_count} 集可读</small>
        </a>
      ))}
    </div>
  );
}
