import { ChevronRight } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { parseMindmap, type MindmapNode } from "../lib/mindmap";
import { parseTranscript } from "../lib/transcript";

export function MarkdownView({ markdown }: { markdown: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        skipHtml
        urlTransform={(url) => (/^(https?:|mailto:)/i.test(url) ? url : "")}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}

export function TranscriptView({ text }: { text: string }) {
  const entries = parseTranscript(text);
  return (
    <div className="transcript">
      {entries.map((entry, index) => (
        <div className="transcript-entry" key={`${entry.time ?? "p"}-${index}`}>
          {(entry.time || entry.speaker) && (
            <div className="transcript-meta">
              {entry.time && <time>{entry.time}</time>}
              {entry.speaker && <span>{entry.speaker}</span>}
            </div>
          )}
          <p>{entry.text}</p>
        </div>
      ))}
    </div>
  );
}

function Branch({ node, depth = 0 }: { node: MindmapNode; depth?: number }) {
  if (!node.children.length)
    return (
      <li className="mind-leaf">
        <span>{node.text}</span>
      </li>
    );
  return (
    <li>
      <details open={depth < 2}>
        <summary>
          <ChevronRight size={15} />
          {node.text}
          <small>{node.children.length}</small>
        </summary>
        <ul>
          {node.children.map((child, index) => (
            <Branch
              key={`${child.text}-${index}`}
              node={child}
              depth={depth + 1}
            />
          ))}
        </ul>
      </details>
    </li>
  );
}

export function MindmapView({ markdown }: { markdown: string }) {
  const nodes = parseMindmap(markdown);
  if (!nodes.length) return <MarkdownView markdown={markdown} />;
  return (
    <div className="mindmap">
      <ul>
        {nodes.map((node, index) => (
          <Branch key={`${node.text}-${index}`} node={node} />
        ))}
      </ul>
    </div>
  );
}
