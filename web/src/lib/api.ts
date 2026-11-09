import type {
  ArtifactName,
  Health,
  Job,
  ProcessingOptions,
  PublicEpisode,
  PublicJob,
  LibraryGroup,
  Subscription,
  SubscriptionEpisode,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function errorText(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) return response.statusText || "请求失败";
  try {
    const body = JSON.parse(text) as { detail?: unknown; error?: unknown };
    const message = body.detail ?? body.error;
    return typeof message === "string" ? message : text;
  } catch {
    return text;
  }
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok)
    throw new ApiError(response.status, await errorText(response));
  if (response.status === 204) return undefined as T;
  const body = await response.text();
  return (body ? JSON.parse(body) : undefined) as T;
}

async function mutate<T>(
  url: string,
  method: "POST" | "PUT" | "DELETE",
  body?: unknown,
): Promise<T> {
  return json<T>(url, {
    method,
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export async function textFile(url: string): Promise<string | null> {
  const response = await fetch(url);
  if (response.status === 404) return null;
  if (!response.ok)
    throw new ApiError(response.status, await errorText(response));
  return response.text();
}

export const api = {
  health: () => json<Health>("/api/health"),
  library: () => json<LibraryGroup[]>("/api/library"),
  publicJob: (id: string) => json<PublicJob>(`/api/jobs/${encodeURIComponent(id)}`),
  publicJobFile: (id: string, name: ArtifactName) => textFile(`/api/jobs/${encodeURIComponent(id)}/files/${name}`),
  jobs: () => json<Job[]>("/api/jobs"),
  job: (id: string) => json<Job>(`/api/jobs/${encodeURIComponent(id)}`),
  createJob: (form: FormData) =>
    json<{ job_id: string; status_url: string }>("/api/jobs", {
      method: "POST",
      body: form,
    }),
  jobFile: (id: string, name: ArtifactName) =>
    textFile(`/api/jobs/${encodeURIComponent(id)}/files/${name}`),
  analyzeJob: (id: string) =>
    mutate<{ job_id: string; status_url: string }>(
      `/api/jobs/${encodeURIComponent(id)}/analyze`,
      "POST",
    ),
  retryJob: (id: string, options: Partial<ProcessingOptions>) =>
    mutate<{ job_id: string; status_url: string }>(
      `/api/jobs/${encodeURIComponent(id)}/retry`,
      "POST",
      options,
    ),
  subscriptions: () => json<Subscription[]>("/api/subscriptions"),
  subscriptionEpisodes: (id: number) =>
    json<SubscriptionEpisode[]>(`/api/subscriptions/${id}/episodes`),
  createSubscription: (
    payload: {
      url: string;
      poll_interval_minutes: number;
      initial_backfill: number;
      auto_process: boolean;
    } & ProcessingOptions,
  ) => mutate<Subscription>("/api/subscriptions", "POST", payload),
  checkSubscription: (id: number) =>
    mutate<void>(`/api/subscriptions/${id}/check`, "POST"),
  setSubscriptionEnabled: (id: number, enabled: boolean) =>
    mutate<void>(`/api/subscriptions/${id}/enabled`, "PUT", { enabled }),
  setSubscriptionAutoProcess: (id: number, auto_process: boolean) =>
    mutate<void>(`/api/subscriptions/${id}/auto-process`, "PUT", {
      auto_process,
    }),
  setSubscriptionOptions: (id: number, options: ProcessingOptions) =>
    mutate<void>(`/api/subscriptions/${id}/options`, "PUT", options),
  deleteSubscription: (id: number) =>
    mutate<void>(`/api/subscriptions/${id}`, "DELETE"),
  retrySubscriptionEpisode: (
    id: number,
    options?: Partial<ProcessingOptions>,
  ) =>
    mutate<void>(
      `/api/subscription-episodes/${id}/retry`,
      "POST",
      options ?? {},
    ),
  transcribeSubscriptionEpisode: (
    id: number,
    options?: Partial<ProcessingOptions>,
  ) =>
    mutate<void>(
      `/api/subscription-episodes/${id}/transcribe`,
      "POST",
      options ?? {},
    ),
  dismissSubscriptionEpisode: (id: number) =>
    mutate<void>(`/api/subscription-episodes/${id}/dismiss`, "POST"),
  analyzeSubscriptionEpisode: (id: number) =>
    mutate<void>(`/api/subscription-episodes/${id}/analyze`, "POST"),
  episode: (id: number) => json<PublicEpisode>(`/api/episodes/${id}`),
  episodeFile: (id: number, name: ArtifactName) =>
    textFile(`/api/episodes/${id}/files/${name}`),
};

export function messageOf(error: unknown, fallback = "请求失败"): string {
  return error instanceof Error ? error.message : fallback;
}
