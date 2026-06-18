export type Route =
  | { name: "home" }
  | { name: "new" }
  | { name: "episode"; id: string }
  | { name: "share"; id: string };

export function parseRoute(pathname: string): Route {
  const shareMatch = pathname.match(/^\/share\/([a-f0-9]+)$/);
  if (shareMatch) {
    return { name: "share", id: shareMatch[1] };
  }
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
