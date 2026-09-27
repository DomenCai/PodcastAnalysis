import { useEffect, useState } from "react";
import { api, messageOf } from "./lib/api";
import { navigate, parseRoute, type Route } from "./lib/routing";
import type { Health } from "./lib/types";
import { Layout } from "./components/Layout";
import { ErrorState, Loading } from "./components/States";
import { HomePage } from "./pages/HomePage";
import { JobsPage } from "./pages/JobsPage";
import { NewJobPage } from "./pages/NewJobPage";
import { JobDetailPage } from "./pages/JobDetailPage";
import { SubscriptionsPage } from "./pages/SubscriptionsPage";
import { PodcastPage } from "./pages/PodcastPage";
import { EpisodePage } from "./pages/EpisodePage";
import { PublicLibraryPage } from "./pages/PublicLibraryPage";
import { PublicJobPage } from "./pages/PublicJobPage";

function Page({ route, health }: { route: Route; health: Health }) {
  if (health.read_only && route.name === "job") return <PublicJobPage id={route.id} />;
  if (health.read_only && route.name === "library") return <PublicLibraryPage />;
  if (health.read_only && (route.name === "jobs" || route.name === "new" || route.name === "subscriptions" || route.name === "home")) {
    return (
      <ErrorState
        message="此页面仅在本地工作台开放。"
        action={
          undefined
        }
      />
    );
  }
  switch (route.name) {
    case "home":
      return <HomePage health={health} />;
    case "library":
      return <PublicLibraryPage />;
    case "jobs":
      return <JobsPage />;
    case "new":
      return <NewJobPage health={health} />;
    case "job":
      return <JobDetailPage id={route.id} health={health} />;
    case "subscriptions":
      return <SubscriptionsPage health={health} />;
    case "podcast":
      return <PodcastPage id={route.id} />;
    case "episode":
      return <EpisodePage id={route.id} />;
    default:
      return (
        <ErrorState
          message="页面不存在。"
          action={
            <button className="danger-link" onClick={() => navigate("/")}>
              返回首页
            </button>
          }
        />
      );
  }
}

export function App() {
  const [route, setRoute] = useState(() => parseRoute(location.pathname)),
    [health, setHealth] = useState<Health | null>(null),
    [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const update = () => setRoute(parseRoute(location.pathname));
    addEventListener("popstate", update);
    return () => removeEventListener("popstate", update);
  }, []);
  useEffect(() => {
    let live = true;
    api
      .health()
      .then((data) => {
        if (live) setHealth(data);
      })
      .catch((err) => {
        if (live) setError(messageOf(err, "无法连接服务"));
      });
    return () => {
      live = false;
    };
  }, []);
  if (error)
    return (
      <main className="boot">
        <ErrorState message={error} />
      </main>
    );
  if (!health)
    return (
      <main className="boot">
        <Loading label="正在检查服务状态" />
      </main>
    );
  return (
    <Layout health={health}>
      <Page route={route} health={health} />
    </Layout>
  );
}
