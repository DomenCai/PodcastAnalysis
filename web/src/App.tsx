import { useEffect, useState } from "react";
import { getHealth } from "./lib/api";
import { parseRoute, type Route } from "./lib/routing";
import type { Health } from "./lib/types";
import { Layout } from "./components/Layout";
import { HomePage } from "./pages/HomePage";
import { NewEpisodePage } from "./pages/NewEpisodePage";
import { EpisodeDetailPage } from "./pages/EpisodeDetailPage";

export function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname));
  const [health, setHealth] = useState<Health | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [healthError, setHealthError] = useState<string | null>(null);

  useEffect(() => {
    const handleRoute = () => setRoute(parseRoute(window.location.pathname));
    window.addEventListener("popstate", handleRoute);
    return () => window.removeEventListener("popstate", handleRoute);
  }, []);

  useEffect(() => {
    let active = true;

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
  }, []);

  return (
    <Layout health={health} healthLoading={healthLoading} healthError={healthError}>
      {route.name === "home" && <HomePage />}
      {route.name === "new" && <NewEpisodePage health={health} />}
      {route.name === "episode" && <EpisodeDetailPage id={route.id} />}
    </Layout>
  );
}
