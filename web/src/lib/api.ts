import type { EpisodeDetail, EpisodeListItem, Health, TaskState } from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function parseError(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) {
    return response.statusText || "请求失败";
  }

  try {
    const data = JSON.parse(text) as { detail?: unknown; error?: unknown };
    const message = data.detail ?? data.error;
    return typeof message === "string" ? message : text;
  } catch {
    return text;
  }
}

async function requestJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...options?.headers
    },
    ...options
  });

  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response));
  }

  return (await response.json()) as T;
}

async function requestText(url: string): Promise<string | null> {
  const response = await fetch(url);
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response));
  }
  return response.text();
}

export function getHealth(): Promise<Health> {
  return requestJson<Health>("/api/health");
}

export function getEpisodes(): Promise<EpisodeListItem[]> {
  return requestJson<EpisodeListItem[]>("/api/episodes");
}

export function getEpisode(id: string): Promise<EpisodeDetail> {
  return requestJson<EpisodeDetail>(`/api/episodes/${id}`);
}

export function getTranscript(id: string): Promise<string | null> {
  return requestText(`/api/episodes/${id}/transcript`);
}

export function getSummary(id: string): Promise<string | null> {
  return requestText(`/api/episodes/${id}/summary`);
}

export function createEpisode(url: string, summary: boolean): Promise<{ task_id: string }> {
  return requestJson<{ task_id: string }>("/api/episodes", {
    method: "POST",
    body: JSON.stringify({ url, summary })
  });
}

export function getTask(taskId: string): Promise<TaskState> {
  return requestJson<TaskState>(`/api/tasks/${taskId}`);
}
