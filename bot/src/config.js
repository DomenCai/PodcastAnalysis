import fs from "node:fs";
import path from "node:path";

export const dataDir = path.resolve(process.env.PODCAST_BOT_DATA_DIR || new URL("../data", import.meta.url).pathname);
export const configPath = path.join(dataDir, "lark.json");

export function readConfig() {
  const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
  if (!config.appId || !config.appSecret || !config.ownerOpenId) {
    throw new Error("飞书配置缺少应用凭据或 owner；请运行 npm run setup");
  }
  return config;
}

export function writeConfig(config) {
  fs.mkdirSync(dataDir, { recursive: true, mode: 0o700 });
  const temp = `${configPath}.${process.pid}.tmp`;
  fs.writeFileSync(temp, `${JSON.stringify(config, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temp, configPath);
}
