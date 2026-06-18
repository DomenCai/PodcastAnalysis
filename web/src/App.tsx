import { type FormEvent, useEffect, useRef, useState } from "react";
import {
  type AuthSecretPrompt,
  getHealth,
  submitAuthSecret,
  subscribeAuthSecretPrompt
} from "./lib/api";
import { parseRoute, type Route } from "./lib/routing";
import type { Health } from "./lib/types";
import { Layout } from "./components/Layout";
import { HomePage } from "./pages/HomePage";
import { NewEpisodePage } from "./pages/NewEpisodePage";
import { EpisodeDetailPage } from "./pages/EpisodeDetailPage";
import { ShareEpisodePage } from "./pages/ShareEpisodePage";

function AuthSecretDialog({ prompt }: { prompt: AuthSecretPrompt | null }) {
  const [secret, setSecret] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!prompt) return;
    setSecret("");
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, [prompt]);

  if (!prompt) {
    return null;
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!secret.trim()) return;
    submitAuthSecret(secret);
  }

  return (
    <div className="modal-backdrop">
      <form className="modal-panel" role="dialog" aria-modal="true" aria-labelledby="auth-dialog-title" onSubmit={handleSubmit}>
        <h2 id="auth-dialog-title" className="section-title">访问密码</h2>
        <p className="mt-2 text-sm text-soft">
          {prompt.error ? "密码不正确，请重新输入。" : "请输入访问密码继续。"}
        </p>
        <label className="field-label mt-5" htmlFor="auth-secret-input">密码</label>
        <input
          ref={inputRef}
          id="auth-secret-input"
          className="text-input"
          type="password"
          autoComplete="current-password"
          value={secret}
          onChange={(event) => setSecret(event.currentTarget.value)}
        />
        <div className="modal-actions">
          <button type="submit" className="primary-button" disabled={!secret.trim()}>
            进入
          </button>
        </div>
      </form>
    </div>
  );
}

export function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname));
  const [health, setHealth] = useState<Health | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [authPrompt, setAuthPrompt] = useState<AuthSecretPrompt | null>(null);

  useEffect(() => {
    const handleRoute = () => setRoute(parseRoute(window.location.pathname));
    window.addEventListener("popstate", handleRoute);
    return () => window.removeEventListener("popstate", handleRoute);
  }, []);

  useEffect(() => subscribeAuthSecretPrompt(setAuthPrompt), []);

  useEffect(() => {
    if (route.name === "share") {
      setHealth(null);
      setHealthError(null);
      setHealthLoading(false);
      return;
    }

    let active = true;
    setHealthLoading(true);

    getHealth()
      .then((nextHealth) => {
        if (active) setHealth(nextHealth);
      })
      .catch((err: unknown) => {
        if (active) setHealthError(err instanceof Error ? err.message : "环境检查失败");
      })
      .finally(() => {
        if (active) setHealthLoading(false);
      });

    return () => {
      active = false;
    };
  }, [route.name]);

  if (route.name === "share") {
    return <ShareEpisodePage id={route.id} />;
  }

  return (
    <>
      <Layout health={health} healthLoading={healthLoading} healthError={healthError}>
        {route.name === "home" && <HomePage />}
        {route.name === "new" && <NewEpisodePage health={health} />}
        {route.name === "episode" && <EpisodeDetailPage id={route.id} />}
      </Layout>
      <AuthSecretDialog prompt={authPrompt} />
    </>
  );
}
