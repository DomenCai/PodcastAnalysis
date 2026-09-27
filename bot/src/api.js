const base = process.env.PODCAST_API_URL || "http://127.0.0.1:18000";

export async function api(path, method = "GET", body) {
  const response = await fetch(new URL(path, base), {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(45_000),
  });
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { /* plain error */ }
    throw new Error(typeof detail === "string" ? detail : `本地 API 返回 HTTP ${response.status}`);
  }
  return response.status === 204 ? null : response.json();
}

export async function createEpisode(url, backend) {
  const form = new FormData();
  form.set("url", url);
  form.set("backend", backend);
  const response = await fetch(new URL("/api/jobs", base), {
    method: "POST", body: form, signal: AbortSignal.timeout(45_000),
  });
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { /* plain error */ }
    throw new Error(typeof detail === "string" ? detail : `本地 API 返回 HTTP ${response.status}`);
  }
  return response.json();
}
