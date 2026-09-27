export function normalizeUrl(raw, kind) {
  const value = String(raw || "").trim();
  let url;
  try { url = new URL(value); } catch { throw new Error("请填写完整的小宇宙链接"); }
  const expected = kind === "episode" ? "episode" : "podcast";
  const other = kind === "episode" ? "播客主页" : "单集";
  if (url.protocol !== "https:" || !["www.xiaoyuzhoufm.com", "xiaoyuzhoufm.com"].includes(url.hostname)) throw new Error("只支持小宇宙 HTTPS 链接");
  if (!new RegExp(`^/${expected}/[0-9a-f]{24}/?$`).test(url.pathname)) throw new Error(`这里需要${kind === "episode" ? "单集" : "播客主页"}链接；你可能填了${other}链接`);
  return `https://www.xiaoyuzhoufm.com${url.pathname.replace(/\/$/, "")}`;
}
