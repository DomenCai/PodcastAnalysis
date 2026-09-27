import { useEffect, useState } from "react";
import type { ArtifactName } from "../lib/types";
import { messageOf } from "../lib/api";
import { MarkdownView, MindmapView, TranscriptView } from "./ContentViews";
import { ErrorState, Loading } from "./States";

const artifactTabs: Array<{ hash: string; name: ArtifactName; label: string }> = [
  { hash: "article", name: "article.md", label: "文章" },
  { hash: "notes", name: "notes.md", label: "笔记" },
  { hash: "mindmap", name: "mindmap.md", label: "思维导图" },
  { hash: "transcript", name: "transcript.txt", label: "逐字稿" },
];
const descriptionTab = { hash: "description", name: null, label: "节目简介" } as const;

export function DescriptionView({ text }: { text: string }) {
  return <div className="description-text">{text}</div>;
}

function selectedHash(available?: string[], fallback = "article", description?: string) {
  const value = location.hash.slice(1);
  if (artifactTabs.some((tab) => tab.hash === value) || (value === "description" && description)) return value;
  if (
    fallback === "article" &&
    available?.includes("article.md") === false &&
    available.includes("transcript.txt")
  )
    return "transcript";
  return fallback;
}

export function ArtifactReader({
  available,
  load,
  defaultTab = "article",
  revision,
  description,
}: {
  available?: string[];
  load: (name: ArtifactName) => Promise<string | null>;
  defaultTab?: "article" | "notes" | "mindmap" | "transcript";
  revision?: string;
  description?: string;
}) {
  const [hash, setHash] = useState(() => selectedHash(available, defaultTab, description));
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tabs = description ? [...artifactTabs, descriptionTab] : artifactTabs;
  const tab = tabs.find((item) => item.hash === hash) ?? tabs[0];

  useEffect(() => {
    const onHash = () => setHash(selectedHash(available, defaultTab, description));
    onHash();
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, [available, defaultTab, description]);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    setContent(null);
    if (tab.name === null) {
      setContent(description || "");
      setLoading(false);
      return;
    }
    load(tab.name)
      .then((text) => {
        if (live) setContent(text);
      })
      .catch((err) => {
        if (live) setError(messageOf(err, "内容加载失败"));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [load, revision, tab.name, description]);

  return (
    <section className="reader">
      <div className="tabs" role="tablist" aria-label="内容类型">
        {tabs.map((item) => (
          <a
            href={`#${item.hash}`}
            role="tab"
            aria-selected={item.hash === hash}
            className={item.hash === hash ? "active" : ""}
            key={item.hash}
          >
            {item.label}
            {item.name && available && !available.includes(item.name) && <i />}
          </a>
        ))}
      </div>
      <div className="content-card" role="tabpanel">
        {loading ? (
          <Loading label={`正在读取${tab.label}`} />
        ) : error ? (
          <ErrorState message={error} />
        ) : content ? (
          tab.name === null ? (
            <DescriptionView text={content} />
          ) : tab.name === "transcript.txt" ? (
            <TranscriptView text={content} />
          ) : tab.name === "mindmap.md" ? (
            <MindmapView markdown={content} />
          ) : (
            <MarkdownView markdown={content} />
          )
        ) : (
          <div className="missing">
            <strong>暂未生成{tab.label}</strong>
            <p>这是旧内容或该产物尚未生成。你仍可查看其他标签页。</p>
          </div>
        )}
      </div>
    </section>
  );
}
