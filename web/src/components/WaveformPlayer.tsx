import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import WaveSurfer from "wavesurfer.js";
import { useTheme } from "../lib/theme";

type Props = {
  episodeId: string;
  hasAudio: boolean;
  onTime?: (seconds: number) => void;
  onPlayingChange?: (playing: boolean) => void;
  onReady?: (controls: { seek: (seconds: number) => void }) => void;
};

function formatTime(seconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safeSeconds / 60);
  const rest = safeSeconds % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

function themeColor(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function WaveformPlayer({ episodeId, hasAudio, onTime, onPlayingChange, onReady }: Props) {
  const { theme } = useTheme();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const waveRef = useRef<WaveSurfer | null>(null);
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState(1);
  const speedRef = useRef(1);
  const [audioError, setAudioError] = useState<string | null>(null);

  const onTimeRef = useRef(onTime);
  const onPlayingChangeRef = useRef(onPlayingChange);
  const onReadyRef = useRef(onReady);
  onTimeRef.current = onTime;
  onPlayingChangeRef.current = onPlayingChange;
  onReadyRef.current = onReady;

  function setPlayingState(value: boolean) {
    setPlaying(value);
    onPlayingChangeRef.current?.(value);
  }

  useEffect(() => {
    if (!hasAudio || !containerRef.current) {
      return;
    }

    setReady(false);
    setPlayingState(false);
    setAudioError(null);

    const wave = WaveSurfer.create({
      container: containerRef.current,
      url: `/api/episodes/${episodeId}/audio`,
      height: 96,
      barGap: 2,
      barRadius: 2,
      barWidth: 2,
      cursorColor: themeColor("--wave-cursor"),
      progressColor: themeColor("--wave-progress"),
      waveColor: themeColor("--wave-base")
    });

    waveRef.current = wave;
    wave.on("ready", () => {
      setReady(true);
      setDuration(wave.getDuration());
      wave.setPlaybackRate(speedRef.current);
      onReadyRef.current?.({ seek: (seconds) => wave.setTime(seconds) });
    });
    wave.on("play", () => setPlayingState(true));
    wave.on("pause", () => setPlayingState(false));
    wave.on("finish", () => setPlayingState(false));
    wave.on("timeupdate", (time) => {
      setCurrentTime(time);
      onTimeRef.current?.(time);
    });
    wave.on("error", () => {
      setReady(false);
      setPlayingState(false);
      setAudioError("音频不可用");
    });

    return () => {
      wave.destroy();
      waveRef.current = null;
    };
  }, [episodeId, hasAudio, theme]);

  function changeSpeed(rate: number) {
    setSpeed(rate);
    speedRef.current = rate;
    waveRef.current?.setPlaybackRate(rate);
  }

  if (!hasAudio) {
    return <div className="empty-panel">音频不可用</div>;
  }

  return (
    <div className="panel">
      <div ref={containerRef} className="min-h-24" />
      {audioError ? (
        <div className="mt-3 text-sm text-[var(--color-danger-text)]">{audioError}</div>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            className="secondary-button"
            disabled={!ready}
            onClick={() => waveRef.current?.playPause()}
          >
            {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            {playing ? "暂停" : "播放"}
          </button>
          <div className="text-sm tabular-nums text-muted">
            {formatTime(currentTime)} / {formatTime(duration)}
          </div>
          <div className="speed-group ml-auto">
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
      )}
    </div>
  );
}
