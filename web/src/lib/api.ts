import type {
  EpisodeDetail,
  EpisodeListItem,
  Health,
  RegenerateRequest,
  SummaryData,
  TaskState
} from "./types";

const AUTH_SECRET_STORAGE_KEY = "podcast-analysis-auth-secret";

export type AuthSecretPrompt = {
  error: boolean;
};

type AuthSecretPromptListener = (prompt: AuthSecretPrompt | null) => void;
type AuthSecretResolver = (secret: string | null) => void;

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function readInitialAuthSecret(): string {
  const params = new URLSearchParams(window.location.search);
  const urlSecret = params.get("secret");
  if (urlSecret) {
    localStorage.setItem(AUTH_SECRET_STORAGE_KEY, urlSecret);
    params.delete("secret");
    const nextSearch = params.toString();
    const nextUrl = `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ""}${window.location.hash}`;
    window.history.replaceState({}, "", nextUrl);
    return urlSecret;
  }
  return localStorage.getItem(AUTH_SECRET_STORAGE_KEY) || "";
}

let authSecret = readInitialAuthSecret();
let pendingSecretPrompt: Promise<string | null> | null = null;
let pendingSecretResolver: AuthSecretResolver | null = null;
let currentAuthPrompt: AuthSecretPrompt | null = null;
const authSecretPromptListeners = new Set<AuthSecretPromptListener>();

function setAuthSecret(secret: string) {
  authSecret = secret;
  localStorage.setItem(AUTH_SECRET_STORAGE_KEY, secret);
}

function clearAuthSecret() {
  authSecret = "";
  localStorage.removeItem(AUTH_SECRET_STORAGE_KEY);
}

function authOptions(options?: RequestInit): RequestInit {
  const headers = new Headers(options?.headers);
  if (authSecret) {
    headers.set("X-Auth-Secret", authSecret);
  }
  return { ...options, headers };
}

function notifyAuthPromptListeners() {
  for (const listener of authSecretPromptListeners) {
    listener(currentAuthPrompt);
  }
}

export function subscribeAuthSecretPrompt(listener: AuthSecretPromptListener): () => void {
  authSecretPromptListeners.add(listener);
  listener(currentAuthPrompt);
  return () => {
    authSecretPromptListeners.delete(listener);
  };
}

export function submitAuthSecret(secret: string) {
  pendingSecretResolver?.(secret);
}

function promptForAuthSecret(error: boolean): Promise<string | null> {
  if (!pendingSecretPrompt) {
    pendingSecretPrompt = new Promise<string | null>((resolve) => {
      pendingSecretResolver = resolve;
      currentAuthPrompt = { error };
      notifyAuthPromptListeners();
    }).then((secret) => {
      const nextSecret = secret?.trim() || null;
      if (nextSecret) {
        setAuthSecret(nextSecret);
      }
      return nextSecret;
    }).finally(() => {
      pendingSecretResolver = null;
      currentAuthPrompt = null;
      notifyAuthPromptListeners();
      pendingSecretPrompt = null;
    });
  } else if (error && !currentAuthPrompt?.error) {
    currentAuthPrompt = { error: true };
    notifyAuthPromptListeners();
  }

  return pendingSecretPrompt;
}

async function fetchWithAuth(url: string, options?: RequestInit): Promise<Response> {
  return fetch(url, authOptions(options));
}

async function retryAfterAuthPrompt(url: string, options: RequestInit | undefined, error: boolean): Promise<Response | null> {
  const nextSecret = await promptForAuthSecret(error);
  if (!nextSecret) {
    return null;
  }
  return fetchWithAuth(url, options);
}

async function authFetch(url: string, options?: RequestInit): Promise<Response> {
  let requestSecret = authSecret;
  let response = await fetchWithAuth(url, options);
  if (response.status !== 401) {
    return response;
  }

  for (let attempts = 0; attempts < 2; attempts += 1) {
    let retry: Response | null;

    if (authSecret && authSecret !== requestSecret) {
      retry = await fetchWithAuth(url, options);
    } else {
      retry = await retryAfterAuthPrompt(url, options, attempts > 0);
    }

    if (!retry) {
      return response;
    }
    if (retry.status !== 401) {
      return retry;
    }

    response = retry;
    requestSecret = authSecret;
    clearAuthSecret();
  }

  return response;
}

export function withAuthSecret(url: string): string {
  if (!authSecret) {
    return url;
  }

  const nextUrl = new URL(url, window.location.origin);
  nextUrl.searchParams.set("secret", authSecret);
  return `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`;
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
  const headers = new Headers(options?.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await authFetch(url, { ...options, headers });

  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response));
  }

  return (await response.json()) as T;
}

async function requestText(url: string): Promise<string | null> {
  const response = await authFetch(url);
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

export async function getSummary(id: string): Promise<SummaryData | null> {
  const response = await authFetch(`/api/episodes/${id}/summary`);
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response));
  }
  return (await response.json()) as SummaryData;
}

export function createEpisode(url: string, summary: boolean): Promise<{ task_id: string }> {
  return requestJson<{ task_id: string }>("/api/episodes", {
    method: "POST",
    body: JSON.stringify({ url, summary })
  });
}

export async function deleteEpisode(id: string): Promise<void> {
  const response = await authFetch(`/api/episodes/${id}`, {
    method: "DELETE"
  });

  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response));
  }
}

export function regenerateEpisode(id: string, payload: RegenerateRequest): Promise<{ task_id: string }> {
  return requestJson<{ task_id: string }>(`/api/episodes/${id}/regenerate`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getTask(taskId: string): Promise<TaskState> {
  return requestJson<TaskState>(`/api/tasks/${taskId}`);
}
