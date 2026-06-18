import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

export function EpisodeDescription({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const canToggle = text.length > 180 || text.includes("\n");
  const ToggleIcon = expanded ? ChevronUp : ChevronDown;
  const toggleButton = (
    <button
      type="button"
      className="inline-flex items-center gap-1 text-sm font-medium text-accent"
      aria-expanded={expanded}
      onClick={() => setExpanded((value) => !value)}
    >
      {expanded ? "收起全文" : "展开全文"}
      <ToggleIcon className="h-4 w-4" />
    </button>
  );

  return (
    <div className="mt-3 max-w-4xl">
      {canToggle && expanded && <div className="mb-2">{toggleButton}</div>}
      <p className={`${expanded ? "" : "line-clamp-4"} whitespace-pre-wrap text-sm leading-7 text-soft`}>
        {text}
      </p>
      {canToggle && !expanded && <div className="mt-2">{toggleButton}</div>}
    </div>
  );
}
