import { registerApp } from "@larksuite/channel";
import { existsSync } from "node:fs";
import { configPath, writeConfig } from "./config.js";

if (existsSync(configPath)) {
  throw new Error(`配置已存在：${configPath}。为避免覆盖机器人身份，请先人工备份并移走。`);
}

let result;
try { result = await registerApp({
  source: "podcast-analysis",
  appPreset: { name: "播客阅读助手", description: "私聊提交播客、管理订阅并阅读文章" },
  addons: {
    scopes: { tenant: [
      "im:message.p2p_msg:readonly",
      "im:message:send_as_bot",
      "im:message:update",
      "im:chat:read",
      "cardkit:card:read",
      "cardkit:card:write",
    ] },
    events: { items: { tenant: ["im.message.receive_v1"] } },
    callbacks: { items: ["card.action.trigger"] },
  },
  createOnly: true,
  onQRCodeReady: ({ url, expireIn }) => {
    console.log(`请用飞书扫码创建独立的播客机器人（${expireIn} 秒内有效）：\n${url}`);
  },
  onStatusChange: ({ status }) => console.log(`注册状态：${status}`),
}); } catch (error) {
  console.error(`飞书注册失败：${error instanceof Error ? error.name : "Error"}`);
  process.exit(1);
}

const ownerOpenId = result.user_info?.open_id;
if (!ownerOpenId) throw new Error("注册返回缺少 owner open_id；配置未保存");
writeConfig({
  appId: result.client_id,
  appSecret: result.client_secret,
  ownerOpenId,
  domain: result.user_info?.tenant_brand === "lark" ? "https://open.larksuite.com" : "https://open.feishu.cn",
});
console.log(`独立应用已保存到 ${configPath}，owner 已绑定。`);
