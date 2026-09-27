export type Route =
  | { name: "home" }
  | { name: "library" }
  | { name: "jobs" }
  | { name: "new" }
  | { name: "job"; id: string }
  | { name: "subscriptions" }
  | { name: "podcast"; id: number }
  | { name: "episode"; id: number }
  | { name: "not-found" };

export function parseRoute(pathname: string): Route {
  if (pathname === "/") return { name: "home" };
  if (pathname === "/podcasts") return { name: "library" };
  if (pathname === "/jobs") return { name: "jobs" };
  if (pathname === "/new") return { name: "new" };
  if (pathname === "/subscriptions") return { name: "subscriptions" };
  const job = pathname.match(/^\/jobs\/([0-9a-f-]+)\/?$/i);
  if (job) return { name: "job", id: job[1] };
  const podcast = pathname.match(/^\/podcasts\/(\d+)\/?$/);
  if (podcast) return { name: "podcast", id: Number(podcast[1]) };
  const episode = pathname.match(/^\/episodes\/(\d+)\/transcript\/?$/);
  if (episode) return { name: "episode", id: Number(episode[1]) };
  return { name: "not-found" };
}

export function navigate(to: string): void {
  window.history.pushState({}, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0, behavior: "instant" });
}
