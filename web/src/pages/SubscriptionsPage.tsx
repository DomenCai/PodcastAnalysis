import {
  BookOpenText,
  ChevronDown,
  ExternalLink,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { api, messageOf } from "../lib/api";
import type {
  Health,
  ProcessingOptions as Options,
  Subscription,
  SubscriptionEpisode,
} from "../lib/types";
import { backendLabel, formatDate } from "../lib/format";
import { navigate } from "../lib/routing";
import {
  defaultProcessingOptions,
  ProcessingOptions,
} from "../components/ProcessingOptions";
import { Empty, ErrorState, Loading } from "../components/States";
import { StatusBadge } from "../components/Status";

export function SubscriptionsPage({ health }: { health: Health }) {
  const [items, setItems] = useState<Subscription[]>([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState<string | null>(null),
    [showForm, setShowForm] = useState(false);
  const load = useCallback(() => api.subscriptions().then(setItems), []);
  useEffect(() => {
    let live = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await api.subscriptions();
        if (live) {
          setItems(next);
          setError(null);
        }
      } catch (err) {
        if (live) setError(messageOf(err));
      } finally {
        if (live) {
          setLoading(false);
          timer = window.setTimeout(poll, 5000);
        }
      }
    };
    void poll();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, []);
  return (
    <section className="stack-xl">
      <header className="page-head split">
        <div>
          <span className="eyebrow">SUBSCRIPTIONS</span>
          <h1>播客订阅</h1>
          <p>按固定间隔检查小宇宙，未来单集使用各订阅保存的默认配置。</p>
        </div>
        <button
          className="primary"
          onClick={() => setShowForm((value) => !value)}
        >
          <Plus size={17} />
          添加订阅
        </button>
      </header>
      {showForm && (
        <NewSubscription
          health={health}
          onCreated={async () => {
            setShowForm(false);
            await load();
          }}
        />
      )}
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} />
      ) : !items.length ? (
        <Empty
          title="还没有订阅"
          description="添加小宇宙播客主页后，系统会自动发现新单集。"
        />
      ) : (
        <div className="subscription-list">
          {items.map((item) => (
            <SubscriptionCard
              key={item.id}
              item={item}
              health={health}
              onChanged={load}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function NewSubscription({
  health,
  onCreated,
}: {
  health: Health;
  onCreated: () => Promise<void>;
}) {
  const [url, setUrl] = useState(""),
    [interval, setIntervalValue] = useState(30),
    [backfill, setBackfill] = useState(1),
    [options, setOptions] = useState<Options>(() =>
      defaultProcessingOptions(health),
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createSubscription({
        url: url.trim(),
        poll_interval_minutes: interval,
        initial_backfill: backfill,
        ...options,
      });
      await onCreated();
    } catch (err) {
      setError(messageOf(err, "订阅创建失败"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="panel stack-lg" onSubmit={submit}>
      <div>
        <h2 className="form-title">添加小宇宙播客</h2>
        <p className="form-help">
          首次回溯只影响添加时，之后会自动追踪新单集。
        </p>
      </div>
      <label className="field">
        <span>播客主页 URL</span>
        <input
          type="url"
          required
          placeholder="https://www.xiaoyuzhoufm.com/podcast/..."
          value={url}
          onChange={(event) => setUrl(event.target.value)}
        />
      </label>
      <div className="two-col">
        <label className="field">
          <span>检查间隔（分钟）</span>
          <input
            type="number"
            min="5"
            max="10080"
            value={interval}
            onChange={(event) => setIntervalValue(Number(event.target.value))}
          />
        </label>
        <label className="field">
          <span>首次回溯集数</span>
          <input
            type="number"
            min="0"
            max="15"
            value={backfill}
            onChange={(event) => setBackfill(Number(event.target.value))}
          />
        </label>
      </div>
      <ProcessingOptions
        value={options}
        health={health}
        disabled={busy}
        onChange={setOptions}
      />
      {error && <ErrorState message={error} />}
      <button className="primary self-start" disabled={busy || !url.trim()}>
        {busy ? "正在添加…" : "添加订阅"}
      </button>
    </form>
  );
}

function SubscriptionCard({
  item,
  health,
  onChanged,
}: {
  item: Subscription;
  health: Health;
  onChanged: () => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false),
    [episodes, setEpisodes] = useState<SubscriptionEpisode[]>([]),
    [loadingEpisodes, setLoadingEpisodes] = useState(false),
    [editing, setEditing] = useState(false),
    [options, setOptions] = useState<Options>({
      backend: item.backend,
      skip_diarization: item.skip_diarization,
      num_speakers: item.num_speakers,
    }),
    [busy, setBusy] = useState<string | null>(null),
    [error, setError] = useState<string | null>(null);
  const loadEpisodes = useCallback(async () => {
    setLoadingEpisodes(true);
    try {
      setEpisodes(await api.subscriptionEpisodes(item.id));
    } catch (err) {
      setError(messageOf(err, "单集列表加载失败"));
    } finally {
      setLoadingEpisodes(false);
    }
  }, [item.id]);
  useEffect(() => {
    if (!editing) {
      setOptions({
        backend: item.backend,
        skip_diarization: item.skip_diarization,
        num_speakers: item.num_speakers,
      });
    }
  }, [editing, item.backend, item.skip_diarization, item.num_speakers]);
  useEffect(() => {
    if (
      !expanded ||
      !episodes.some(
        (episode) =>
          episode.status === "pending" || episode.status === "processing",
      )
    )
      return;
    const timer = window.setTimeout(() => void loadEpisodes(), 3000);
    return () => clearTimeout(timer);
  }, [episodes, expanded, loadEpisodes]);
  async function run(
    key: string,
    action: () => Promise<unknown>,
    refreshEpisodes = false,
  ): Promise<boolean> {
    setBusy(key);
    setError(null);
    try {
      await action();
      await onChanged();
      if (refreshEpisodes) await loadEpisodes();
      return true;
    } catch (err) {
      setError(messageOf(err));
      return false;
    } finally {
      setBusy(null);
    }
  }
  async function toggleEpisodes() {
    const next = !expanded;
    setExpanded(next);
    if (next && !episodes.length) await loadEpisodes();
  }
  return (
    <article className="subscription-card">
      <div className="subscription-top">
        <div className="subscription-identity">
          <span
            className={
              item.enabled ? "subscription-dot" : "subscription-dot off"
            }
          />
          <div>
            <h2>{item.title}</h2>
            <p>{item.author || "小宇宙播客"}</p>
          </div>
        </div>
        <div className="subscription-actions">
          <a
            className="icon-button"
            href={item.source_url}
            target="_blank"
            rel="noreferrer"
            title="在小宇宙查看"
          >
            <ExternalLink size={16} />
          </a>
          <button
            className="secondary compact"
            disabled={!!busy}
            onClick={() =>
              run("check", () => api.checkSubscription(item.id), true)
            }
          >
            <RefreshCw size={15} />
            立即检查
          </button>
          <button
            className="ghost compact"
            disabled={!!busy}
            onClick={() =>
              run("toggle", () =>
                api.setSubscriptionEnabled(item.id, !item.enabled),
              )
            }
          >
            {item.enabled ? "暂停" : "启用"}
          </button>
          <button
            className="icon-button danger-icon"
            disabled={!!busy}
            title="删除订阅"
            onClick={() => {
              if (
                window.confirm(
                  `删除订阅“${item.title}”？已生成的公开内容是否保留由服务端决定。`,
                )
              )
                void run("delete", () => api.deleteSubscription(item.id));
            }}
          >
            <Trash2 size={16} />
          </button>
        </div>
      </div>
      <div className="subscription-stats">
        <span>
          <b>{item.done_count}</b> 已完成
        </span>
        <span>
          <b>{item.pending_count}</b> 等待
        </span>
        <span>
          <b>{item.processing_count}</b> 处理中
        </span>
        <span className={item.failed_count ? "warn-text" : ""}>
          <b>{item.failed_count}</b> 失败
        </span>
      </div>
      <div className="subscription-config">
        <span>{backendLabel(item.backend)}</span>
        <span>
          {item.skip_diarization
            ? "不识别说话人"
            : `${item.num_speakers ?? "自动"} 位说话人`}
        </span>
        <span>每 {item.poll_interval_minutes} 分钟检查</span>
        <button
          className="text-button"
          onClick={() => setEditing((value) => !value)}
        >
          修改未来默认配置
        </button>
      </div>
      {editing && (
        <div className="inline-editor">
          <ProcessingOptions
            value={options}
            health={health}
            disabled={!!busy}
            onChange={setOptions}
          />
          <div className="inline-actions">
            <button
              className="secondary compact"
              onClick={() => setEditing(false)}
            >
              取消
            </button>
            <button
              className="primary compact"
              disabled={!!busy}
              onClick={() =>
                void run("options", () =>
                  api.setSubscriptionOptions(item.id, options),
                ).then((saved) => {
                  if (saved) setEditing(false);
                })
              }
            >
              保存默认配置
            </button>
          </div>
        </div>
      )}
      {error && <ErrorState message={error} />}
      <button className="episode-toggle" onClick={toggleEpisodes}>
        查看单集 <ChevronDown size={16} className={expanded ? "rotated" : ""} />
      </button>
      {expanded && (
        <div className="admin-episodes">
          {loadingEpisodes ? (
            <Loading label="正在读取单集" />
          ) : !episodes.length ? (
            <Empty title="暂无单集" />
          ) : (
            episodes.map((episode) => (
              <EpisodeAdminRow
                key={episode.id}
                episode={episode}
                subscription={item}
                health={health}
                busy={!!busy}
                onRetry={(nextOptions) =>
                  run(
                    `retry-${episode.id}`,
                    () => api.retrySubscriptionEpisode(episode.id, nextOptions),
                    true,
                  )
                }
                onAnalyze={() =>
                  run(
                    `analyze-${episode.id}`,
                    () => api.analyzeSubscriptionEpisode(episode.id),
                    true,
                  )
                }
              />
            ))
          )}
        </div>
      )}
    </article>
  );
}

function EpisodeAdminRow({
  episode,
  subscription,
  health,
  busy,
  onRetry,
  onAnalyze,
}: {
  episode: SubscriptionEpisode;
  subscription: Subscription;
  health: Health;
  busy: boolean;
  onRetry: (options: Options) => Promise<boolean>;
  onAnalyze: () => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const resolvedOptions = (): Options => {
    const skipDiarization =
      episode.skip_diarization ?? subscription.skip_diarization;
    return {
      backend: episode.backend ?? subscription.backend,
      skip_diarization: skipDiarization,
      num_speakers: skipDiarization
        ? null
        : episode.num_speakers !== undefined
          ? episode.num_speakers
          : subscription.num_speakers,
    };
  };
  const [options, setOptions] = useState<Options>(resolvedOptions);
  useEffect(() => {
    if (!editing) setOptions(resolvedOptions());
  }, [editing, episode, subscription]);
  const canRetranscribe =
    episode.status === "done" ||
    episode.status === "ignored" ||
    episode.status === "failed" ||
    episode.status === "skipped";
  const canAnalyze =
    (episode.status === "done" || episode.status === "failed") &&
    episode.available_files?.includes("transcript.txt") === true;

  return (
    <div className="admin-episode-wrap">
      <div className="admin-episode">
        <span className="row-main">
          <strong>{episode.title}</strong>
          <small>
            {formatDate(episode.published_at)} ·{" "}
            {backendLabel(episode.backend ?? subscription.backend)}
            {episode.error ? ` · ${episode.error}` : ""}
          </small>
        </span>
        <StatusBadge status={episode.status} />
        <div className="mini-actions">
          {episode.status === "done" && (
            <button
              onClick={() =>
                navigate(`/episodes/${episode.id}/transcript#article`)
              }
            >
              <BookOpenText size={14} />
              阅读
            </button>
          )}
          {canRetranscribe && (
            <button
              disabled={busy}
              onClick={() => setEditing((value) => !value)}
            >
              <RefreshCw size={14} />
              重新转写
            </button>
          )}
          {canAnalyze && (
            <button disabled={busy} onClick={() => void onAnalyze()}>
              <Sparkles size={14} />
              仅重新分析
            </button>
          )}
          {episode.status === "failed" && !canAnalyze && episode.job_id && (
            <button onClick={() => navigate(`/jobs/${episode.job_id}`)}>
              <BookOpenText size={14} />
              查看关联任务
            </button>
          )}
        </div>
      </div>
      {editing && (
        <div className="episode-retry-editor">
          <div>
            <strong>本次重新转写配置</strong>
            <p>仅用于这一集，不修改订阅未来默认值。</p>
          </div>
          <ProcessingOptions
            value={options}
            health={health}
            disabled={busy}
            onChange={setOptions}
          />
          <div className="inline-actions">
            <button
              className="secondary compact"
              onClick={() => setEditing(false)}
            >
              取消
            </button>
            <button
              className="primary compact"
              disabled={busy}
              onClick={() =>
                void onRetry(options).then((queued) => {
                  if (queued) setEditing(false);
                })
              }
            >
              按此配置加入队列
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
