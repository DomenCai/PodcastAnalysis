import { useEffect, useState } from "react";
import { api, messageOf } from "../lib/api";
import type { LibraryGroup } from "../lib/types";
import { formatDate } from "../lib/format";
import { navigate } from "../lib/routing";
import { Empty, ErrorState, Loading } from "../components/States";

export function PublicLibraryPage() {
  const [groups, setGroups] = useState<LibraryGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.library().then(setGroups).catch((err) => setError(messageOf(err, "阅读列表加载失败")));
  }, []);
  if (error) return <ErrorState message={error} />;
  if (!groups) return <Loading label="正在读取播客文章" />;
  return <section className="reading stack-xl">
    <header className="page-head"><div><span className="eyebrow">PUBLIC LIBRARY</span><h1>播客阅读</h1></div></header>
    {groups.length ? groups.map((group) => <section key={group.title} className="stack-xl">
      <div className="section-head"><h2>{group.title}</h2><small>{group.articles.length} 篇</small></div>
      <div className="episode-list">{group.articles.map((article) => <a key={`${article.kind}-${article.id}`} href={article.url} onClick={(event) => { event.preventDefault(); navigate(article.url); }}>
        <span><strong>{article.title}</strong><small>{formatDate(article.published_at)}</small></span>
      </a>)}</div>
    </section>) : <Empty title="暂无可读文章" description="处理完成的播客会出现在这里。" />}
  </section>;
}
