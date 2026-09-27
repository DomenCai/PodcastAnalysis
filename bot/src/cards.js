import { randomUUID } from "node:crypto";

const publicBase = (process.env.PODCAST_PUBLIC_URL || "https://podcast.fullai.top").replace(/\/$/, "");

const title = (content) => ({ tag: "plain_text", content });
const plain = (content) => ({ tag: "plain_text", content });
const md = (content) => ({ tag: "markdown", content });
const option = (text, value) => ({ text: plain(text), value: String(value) });
const button = (text, value, type = "default") => ({
  tag: "button", text: plain(text), type,
  behaviors: [{ type: "callback", value }],
});
const link = (text, url) => ({ tag: "button", text: plain(text), type: "primary", behaviors: [{ type: "open_url", default_url: url }] });
const card = (heading, elements, template = "blue") => ({ schema: "2.0", header: { title: title(heading), template }, body: { elements } });

export function helpCard() {
  return card("播客阅读助手", [
    md("选择操作，填入对应的小宇宙链接。"),
    button("处理单集", { action: "episode_form" }, "primary"),
    button("订阅播客", { action: "subscription_form" }),
    button("任务状态", { action: "jobs" }),
    button("订阅管理", { action: "subscriptions" }),
    link("打开阅读列表", `${publicBase}/podcasts`),
  ]);
}

export function episodeForm() {
  const token = randomUUID();
  return card("处理单集", [{
    tag: "form", name: "episode", elements: [
      { tag: "input", name: "url", label: plain("小宇宙单集链接"), placeholder: plain("https://www.xiaoyuzhoufm.com/episode/...") },
      md("转录模型"),
      { tag: "select_static", name: "backend", initial_option: "qwen", options: [option("Qwen（默认）", "qwen"), option("MiMo", "mimo")] },
      { tag: "button", name: "submit_episode", text: plain("确定"), type: "primary", form_action_type: "submit", behaviors: [{ type: "callback", value: { action: "submit_episode", token } }] },
    ],
  }]);
}

export function subscriptionForm() {
  const token = randomUUID();
  return card("订阅播客", [{
    tag: "form", name: "subscription", elements: [
      { tag: "input", name: "url", label: plain("小宇宙播客主页"), placeholder: plain("https://www.xiaoyuzhoufm.com/podcast/...") },
      md("转录模型"),
      { tag: "select_static", name: "backend", initial_option: "qwen", options: [option("Qwen（默认）", "qwen"), option("MiMo", "mimo")] },
      md("开始时处理"),
      { tag: "select_static", name: "initial_backfill", initial_option: "1", options: [option("仅未来更新", "0"), option("最新 1 集（默认）", "1"), option("最新 3 集", "3")] },
      { tag: "button", name: "submit_subscription", text: plain("确定"), type: "primary", form_action_type: "submit", behaviors: [{ type: "callback", value: { action: "submit_subscription", token } }] },
    ],
  }]);
}

export function jobsCard(jobs) {
  return card("任务状态", jobs.length ? jobs.slice(0, 10).flatMap((job) => {
    const elements = [md(`**${job.episode?.title || job.filename || job.id}**\n${job.status} · ${job.stage} · ${job.backend}`)];
    if (job.status === "error") {
      elements.push(button("失败重试", { action: "retry_job", id: job.id }));
    }
    if (["done", "error"].includes(job.status) && job.available_files?.includes("transcript.txt")) elements.push(button("仅重新生成文章", { action: "analyze_job", id: job.id }));
    if (job.status === "done") elements.push(link("阅读", `${publicBase}/jobs/${job.id}`));
    return elements;
  }) : [md("还没有任务")]);
}

export function subscriptionsCard(items) {
  return card("订阅管理", items.length ? items.slice(0, 10).flatMap((item) => [
    md(`**${item.title}** · ${item.enabled ? "已启用" : "已暂停"} · 完成 ${item.done_count || 0}`),
    button(item.enabled ? "暂停" : "恢复", { action: "toggle_subscription", id: item.id, enabled: !item.enabled }),
    button("立即检查更新", { action: "check_subscription", id: item.id }),
    link("阅读列表", `${publicBase}/podcasts`),
  ]) : [md("还没有订阅")]);
}

export function completionCard(job) {
  const titleText = job.episode?.title || job.filename || "播客处理完成";
  const intro = (job.episode?.description || "文章、笔记和逐字稿已生成。")
    .replace(/\s+/g, " ").slice(0, 120);
  return card(titleText, [md(intro), link("阅读", `${publicBase}/jobs/${job.id}`)], "green");
}

export function failureCard(job) {
  return card(`处理失败：${job.episode?.title || job.filename || job.id}`, [
    md((job.error || "请稍后重试").slice(0, 300)),
    button("失败重试", { action: "retry_job", id: job.id }),
    ...(job.available_files?.includes("transcript.txt") ? [button("仅重新生成文章", { action: "analyze_job", id: job.id })] : []),
  ], "red");
}

export function resultCard(message) {
  return card("已受理", [md(message)], "green");
}
