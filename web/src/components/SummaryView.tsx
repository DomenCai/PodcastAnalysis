import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { ChevronRight } from "lucide-react";
import type { MindmapNode as MindmapNodeType, SummaryData } from "../lib/types";

const TAG_CLASS: Record<string, string> = {
  概念: "mm-tag-concept",
  方法: "mm-tag-method",
  反直觉: "mm-tag-counter",
  案例: "mm-tag-case",
  事件: "mm-tag-event",
  人物: "mm-tag-person",
  书: "mm-tag-book"
};

const WORTH_ICON: Record<string, string> = {
  书: "📚",
  论文: "📄",
  工具: "🛠️",
  人物: "👤",
  播客: "🎙️",
  视频: "🎬"
};

function MindmapNode({ node, depth }: { node: MindmapNodeType; depth: number }) {
  const [open, setOpen] = useState(true);
  const hasChildren = node.children.length > 0;
  const tagClass = node.tag ? TAG_CLASS[node.tag] : null;

  return (
    <div className="mm-node">
      <div
        className={hasChildren ? "mm-row mm-row-toggle" : "mm-row"}
        data-top={depth === 0 ? "true" : undefined}
        role={hasChildren ? "button" : undefined}
        tabIndex={hasChildren ? 0 : undefined}
        onClick={hasChildren ? () => setOpen((v) => !v) : undefined}
        onKeyDown={
          hasChildren
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setOpen((v) => !v);
                }
              }
            : undefined
        }
      >
        <span className="mm-bullet">
          {hasChildren ? (
            <ChevronRight className={open ? "mm-chevron mm-chevron-open" : "mm-chevron"} />
          ) : (
            <span className="mm-dot" />
          )}
        </span>
        <span className="mm-text">{node.text}</span>
        {node.tag && <span className={`mm-tag ${tagClass ?? ""}`}>{node.tag}</span>}
      </div>
      {hasChildren && open && (
        <div className="mm-children">
          {node.children.map((child, index) => (
            <MindmapNode key={`${depth}-${index}-${child.text.slice(0, 12)}`} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export function SummaryOverviewView({ data }: { data: SummaryData }) {
  return (
    <div className="summary-view">
      <section>
        <h3 className="summary-section-title">这期讲了什么</h3>
        <div className="overview-list">
          {data.overview.map((seg, index) => (
            <div key={`${index}-${seg.time}`} className="overview-card">
              <div className="overview-head">
                <span className="overview-time">{seg.time}</span>
                {seg.title && <span className="overview-title">{seg.title}</span>}
              </div>
              <div className="markdown-content overview-body">
                <ReactMarkdown>{seg.text}</ReactMarkdown>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export function SummaryExploreView({ data }: { data: SummaryData }) {
  const { mindmap, worth_following: worth } = data;

  return (
    <div className="summary-view">
      <section>
        <h3 className="summary-section-title">思维导图</h3>
        {mindmap.note ? (
          <div className="empty-panel">{mindmap.note}</div>
        ) : (
          <div className="mm-tree">
            {mindmap.nodes.map((node, index) => (
              <MindmapNode key={`${index}-${node.text.slice(0, 12)}`} node={node} depth={0} />
            ))}
          </div>
        )}
      </section>

      {worth.length > 0 && (
        <section>
          <h3 className="summary-section-title">值得追的</h3>
          <div className="worth-list">
            {worth.map((item, index) => (
              <div key={`${index}-${item.title}`} className="worth-item">
                <span className="worth-icon">{WORTH_ICON[item.type] ?? "🔖"}</span>
                <div>
                  <div className="worth-head">
                    <span className="worth-title">{item.title}</span>
                    {item.by && <span className="worth-by">{item.by}</span>}
                  </div>
                  {item.note && <p className="worth-note">{item.note}</p>}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
