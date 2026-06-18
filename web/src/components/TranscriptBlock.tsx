import { useEffect, useMemo, useRef } from "react";

type TranscriptLine = {
  time: string | null;
  seconds: number | null;
  content: string;
};

function timeToSeconds(time: string | null): number | null {
  if (!time) return null;
  const match = time.match(/(\d{2}):(\d{2}):(\d{2})/);
  if (!match) return null;
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
}

export function TranscriptBlock({
  text,
  activeTime,
  follow,
  onSeek
}: {
  text: string;
  activeTime: number;
  follow: boolean;
  onSeek: (seconds: number) => void;
}) {
  const paragraphs = useMemo<TranscriptLine[]>(
    () =>
      text
        .split(/\n\s*\n/)
        .map((item) => item.trim())
        .filter(Boolean)
        .map((paragraph) => {
          const match = paragraph.match(/^(\[\d{2}:\d{2}:\d{2}\])\s*(.*)$/s);
          const time = match ? match[1] : null;
          return { time, seconds: timeToSeconds(time), content: match ? match[2] : paragraph };
        }),
    [text]
  );

  const activeIndex = useMemo(() => {
    let idx = 0;
    for (let i = 0; i < paragraphs.length; i += 1) {
      const seconds = paragraphs[i].seconds;
      if (seconds != null && seconds <= activeTime) idx = i;
    }
    return idx;
  }, [paragraphs, activeTime]);

  const activeRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (follow) {
      activeRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [activeIndex, follow]);

  if (paragraphs.length === 0) {
    return <div className="empty-panel">暂无逐字稿内容</div>;
  }

  return (
    <div className="transcript-list">
      {paragraphs.map((paragraph, index) => {
        const isActive = index === activeIndex;
        const seekable = paragraph.seconds != null;
        return (
          <div
            key={`${index}-${paragraph.content.slice(0, 16)}`}
            ref={isActive ? activeRef : null}
            role={seekable ? "button" : undefined}
            tabIndex={seekable ? 0 : undefined}
            onClick={seekable ? () => onSeek(paragraph.seconds as number) : undefined}
            onKeyDown={
              seekable
                ? (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSeek(paragraph.seconds as number);
                    }
                  }
                : undefined
            }
            className={
              isActive
                ? "transcript-row transcript-row-active"
                : seekable
                  ? "transcript-row transcript-row-seekable"
                  : "transcript-row"
            }
          >
            <div className="transcript-time">{paragraph.time || "--:--:--"}</div>
            <p className="transcript-paragraph">{paragraph.content}</p>
          </div>
        );
      })}
    </div>
  );
}
