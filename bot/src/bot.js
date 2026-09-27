import { createLarkChannel } from "@larksuite/channel";
import { api, createEpisode } from "./api.js";
import { readConfig } from "./config.js";
import { Ledger } from "./ledger.js";
import { completionCard, episodeForm, failureCard, helpCard, jobsCard, resultCard, subscriptionForm, subscriptionsCard } from "./cards.js";
import { normalizeUrl } from "./validation.js";
import { deliverNotification } from "./notifications.js";
import { allowedAction, allowedMessage } from "./auth.js";
import { finishAndPresent } from "./submission.js";

const config = readConfig();
const ledger = new Ledger();
function safeError(error) {
  const data = error && typeof error === "object" ? error.response?.data : undefined;
  const code = typeof data?.code === "number" ? ` code=${data.code}` : "";
  const message = typeof data?.msg === "string" ? ` msg=${data.msg.replaceAll(config.appSecret, "[REDACTED]").slice(0, 240)}` : "";
  return `${error instanceof Error ? error.name : typeof error}${code}${message}`;
}
const channel = createLarkChannel({
  appId: config.appId,
  appSecret: config.appSecret,
  domain: config.domain,
  policy: { dmMode: "allowlist", dmAllowlist: [config.ownerOpenId], requireMention: false, groupAllowlist: [] },
  logger: Object.fromEntries(["error", "warn", "info", "debug", "trace"].map((level) => [level, (...args) => {
    if (level === "error" || level === "warn") console.error(`飞书 SDK ${level}: ${args.map(safeError).join(" ")}`);
  }])),
  loggerLevel: 2,
});

const logError = (label, error) => console.error(label, safeError(error));
const sendText = (chatId, text) => channel.send(chatId, { text });
const sendCard = (chatId, card) => channel.send(chatId, { card });
const defer = (label, operation) => {
  setImmediate(() => Promise.resolve().then(operation).catch((error) => logError(label, error)));
};

function backendOf(value) {
  return value === "mimo" ? "mimo" : "qwen";
}

async function handleMessage(msg) {
  if (!allowedMessage(msg, config.ownerOpenId)) return;
  if (!ledger.claimEvent(`message:${msg.messageId}`)) return;
  const content = msg.content.trim();
  if (content === "/help" || content === "帮助" || content === "菜单") await sendCard(msg.chatId, helpCard());
  else await sendText(msg.chatId, "发送 /help 查看播客操作入口。请通过卡片提交链接。");
}

async function handleAction(evt) {
  if (evt.operator.openId !== config.ownerOpenId) return;
  const value = evt.action.value;
  if (!value || typeof value !== "object" || typeof value.action !== "string") return;
  const form = evt.action.formValue || {};
  const key = `card:${evt.messageId}:${value.action}:${JSON.stringify(value)}:${JSON.stringify(form)}`;
  if (!ledger.claimEvent(key, 10_000)) return;
  const chatId = evt.chatId;
  const act = value.action;
  // Return to the card callback immediately; network requests and feed fetches run afterwards.
  defer(`卡片操作 ${act} 失败`, async () => {
    try {
      if (!allowedAction(evt, config.ownerOpenId, await channel.getChatMode(chatId))) return;
      if (act === "episode_form") return await sendCard(chatId, episodeForm());
      if (act === "subscription_form") return await sendCard(chatId, subscriptionForm());
      if (act === "jobs") return await sendCard(chatId, jobsCard(await api("/api/jobs")));
      if (act === "subscriptions") return await sendCard(chatId, subscriptionsCard(await api("/api/subscriptions")));
      if (act === "submit_episode") {
        if (typeof value.token !== "string" || !ledger.claimSubmission(value.token)) return;
        let result;
        try {
        const url = normalizeUrl(form.url, "episode");
        result = await createEpisode(url, backendOf(form.backend));
        } catch (error) { ledger.failSubmission(value.token); throw error; }
        await finishAndPresent(ledger, value.token, result.job_id, channel, evt.messageId, chatId,
          resultCard(`单集任务已创建：${result.job_id}。完成后会推送阅读卡片。`),
          `单集任务已创建：${result.job_id}。完成后会推送阅读卡片。`);
        return;
      }
      if (act === "submit_subscription") {
        if (typeof value.token !== "string" || !ledger.claimSubmission(value.token)) return;
        let result;
        try {
        const url = normalizeUrl(form.url, "podcast");
        const initial_backfill = Number(form.initial_backfill ?? 1);
        if (![0, 1, 3].includes(initial_backfill)) throw new Error("初始处理集数只能是 0、1 或 3");
        try { result = await api("/api/subscriptions", "POST", { url, backend: backendOf(form.backend), initial_backfill, poll_interval_minutes: 30 }); }
        catch (error) {
          result = (await api("/api/subscriptions")).find((item) => item.source_url === url);
          if (!result) throw error;
        }
        } catch (error) { ledger.failSubmission(value.token); throw error; }
        await finishAndPresent(ledger, value.token, result.id, channel, evt.messageId, chatId,
          resultCard(`已订阅「${result.title}」，每 30 分钟检查更新。`),
          `已订阅「${result.title}」，每 30 分钟检查更新。`);
        return;
      }
      if (act === "retry_job" || act === "analyze_job") {
        await api(`/api/jobs/${encodeURIComponent(value.id)}/${act === "retry_job" ? "retry" : "analyze"}`, "POST");
        return await sendText(chatId, act === "retry_job" ? "任务已重新排队。" : "文章重新生成已排队。" );
      }
      if (act === "toggle_subscription") {
        await api(`/api/subscriptions/${Number(value.id)}/enabled`, "PUT", { enabled: value.enabled === true });
        return await sendCard(chatId, subscriptionsCard(await api("/api/subscriptions")));
      }
      if (act === "check_subscription") {
        await api(`/api/subscriptions/${Number(value.id)}/check`, "POST");
        return await sendText(chatId, "已请求立即检查更新。");
      }
    } catch (error) {
      await sendText(chatId, `操作失败：${error instanceof Error ? error.message : String(error)}`);
    }
  });
}

let polling = false;
async function poll() {
  if (polling) return;
  polling = true;
  try {
    const jobs = await api("/api/jobs");
    ledger.seed(jobs);
    for (const job of jobs) {
      if (!["done", "error"].includes(job.status)) continue;
      const key = `${job.id}:${job.status}:${job.updated_at}`;
      if (ledger.state.notifications[key]) continue;
      try {
        await deliverNotification(channel, ledger, config.ownerOpenId, key, job.status === "done" ? completionCard(job) : failureCard(job));
      }
      catch (error) { logError(`任务 ${job.id} 推送失败`, error); }
    }
  } catch (error) { logError("任务轮询失败", error); }
  finally { polling = false; }
}

channel.on({
  message: (msg) => handleMessage(msg).catch((error) => logError("消息处理失败", error)),
  cardAction: (evt) => handleAction(evt).catch((error) => logError("卡片回调失败", error)),
  error: (error) => logError("飞书连接错误", error),
});
await channel.connect();
console.log("播客飞书机器人已连接");
await poll();
setInterval(poll, 30_000);
