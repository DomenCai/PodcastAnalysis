import { type CSSProperties, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import { withAuthSecret } from "../lib/api";

type Props = {
  episodeId: string;
  hasAudio: boolean;
  title: string;
  onTime?: (seconds: number) => void;
  onPlayingChange?: (playing: boolean) => void;
  onReady?: (controls: { seek: (seconds: number) => void }) => void;
};

function formatTime(seconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const rest = safeSeconds % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
  }
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

export function AudioProgressBar({
  episodeId,
  hasAudio,
  title,
  onTime,
  onPlayingChange,
  onReady
}: Props) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState(1);
  const [audioError, setAudioError] = useState<string | null>(null);

  function setPlayingState(value: boolean) {
    setPlaying(value);
    onPlayingChange?.(value);
  }

  function syncTime(seconds: number) {
    setCurrentTime(seconds);
    onTime?.(seconds);
  }

  function seek(seconds: number) {
    const audio = audioRef.current;
    if (!audio) return;
    const nextTime = duration > 0 ? Math.min(Math.max(seconds, 0), duration) : Math.max(seconds, 0);
    audio.currentTime = nextTime;
    syncTime(nextTime);
  }

  async function togglePlayback() {
    const audio = audioRef.current;
    if (!audio || !ready) return;

    if (audio.paused) {
      try {
        await audio.play();
      } catch {
        setAudioError("音频播放失败");
      }
      return;
    }

    audio.pause();
  }

  function changeSpeed(rate: number) {
    setSpeed(rate);
    if (audioRef.current) {
      audioRef.current.playbackRate = rate;
    }
  }

  if (!hasAudio) {
    return null;
  }

  const progress = duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0;
  const progressStyle = { "--audio-progress": `${progress}%` } as CSSProperties;

  return (
    <div className="audio-progress-bar">
      <audio
        ref={audioRef}
        src={withAuthSecret(`/api/episodes/${episodeId}/audio`)}
        preload="metadata"
        onLoadedMetadata={(event) => {
          const audio = event.currentTarget;
          const nextDuration = Number.isFinite(audio.duration) ? audio.duration : 0;
          audio.playbackRate = speed;
          setReady(true);
          setDuration(nextDuration);
          setAudioError(null);
          onReady?.({ seek });
        }}
        onPlay={() => setPlayingState(true)}
        onPause={() => setPlayingState(false)}
        onEnded={() => setPlayingState(false)}
        onTimeUpdate={(event) => syncTime(event.currentTarget.currentTime)}
        onError={() => {
          setReady(false);
          setPlayingState(false);
          setAudioError("音频不可用");
        }}
      />

      <div className="audio-progress-inner">
        <div className="audio-progress-main">
          <button
            type="button"
            className="icon-button"
            aria-label={playing ? "暂停" : "播放"}
            title={playing ? "暂停" : "播放"}
            disabled={!ready}
            onClick={togglePlayback}
          >
            {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </button>
          <div className="audio-progress-meta">
            <div className="audio-progress-title">{title}</div>
            <div className="audio-progress-time">
              {audioError || `${formatTime(currentTime)} / ${formatTime(duration)}`}
            </div>
          </div>
        </div>

        <input
          className="audio-progress-range"
          type="range"
          min="0"
          max={duration || 0}
          step="0.1"
          value={duration > 0 ? Math.min(currentTime, duration) : 0}
          disabled={!ready}
          aria-label="播放进度"
          style={progressStyle}
          onChange={(event) => seek(Number(event.currentTarget.value))}
        />

        <div className="speed-group audio-progress-speed">
          {[1, 1.25, 1.5, 2].map((rate) => (
            <button
              key={rate}
              type="button"
              className="speed-button"
              data-active={speed === rate ? "true" : undefined}
              disabled={!ready}
              onClick={() => changeSpeed(rate)}
            >
              {rate}x
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
