export type Route =
  | { name: "home" }
  | { name: "new" }
  | { name: "episode"; id: string };

export function parseRoute(pathname: string): Route {
  const episodeMatch = pathname.match(/^\/episodes\/([a-f0-9]+)$/);
  if (episodeMatch) {
    return { name: "episode", id: episodeMatch[1] };
  }
  if (pathname === "/new") {
    return { name: "new" };
  }
  return { name: "home" };
}

export function navigate(path: string): void {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
