import type { Health, ProcessingOptions as Options } from "../lib/types";

export function defaultProcessingOptions(health: Health): Options {
  return {
    backend:
      health.backends?.qwen !== false ? "qwen" : health.backends?.whisper === false && health.backends.mimo === true
        ? "mimo"
        : "whisper",
    skip_diarization: true,
    num_speakers: null,
  };
}

export function ProcessingOptions({
  value,
  health,
  disabled,
  onChange,
}: {
  value: Options;
  health?: Health | null;
  disabled?: boolean;
  onChange: (value: Options) => void;
}) {
  const update = (patch: Partial<Options>) => onChange({ ...value, ...patch });
  return (
    <div className="options-grid">
      <label className="field">
        <span>转写模型</span>
        <select
          value={value.backend}
          disabled={disabled}
          onChange={(event) =>
            update({ backend: event.target.value as Options["backend"], skip_diarization: true, num_speakers: null })
          }
        >
          <option value="qwen" disabled={health?.backends?.qwen === false}>Qwen3-ASR（默认）</option>
          <option
            value="whisper"
            disabled={health?.backends?.whisper === false}
          >
            Whisper
          </option>
          <option value="mimo" disabled={health?.backends?.mimo === false}>
            MiMo
          </option>
        </select>
        <small>
          {value.backend === "whisper"
            ? "强制执行错字清理"
            : "适合直接处理长音频"}
        </small>
      </label>
      <label className="check-card">
        <input
          type="checkbox"
          checked={!value.skip_diarization}
          disabled={disabled || value.backend === "qwen"}
          onChange={(event) =>
            update({
              skip_diarization: !event.target.checked,
              num_speakers: event.target.checked ? value.num_speakers : null,
            })
          }
        />
        <span>
          <strong>识别说话人</strong>
          <small>可选，Whisper / MiMo 支持</small>
        </span>
      </label>
      {!value.skip_diarization && (
        <label className="field">
          <span>说话人数（可选）</span>
          <input
            type="number"
            min="1"
            max="32"
            placeholder="自动判断"
            value={value.num_speakers ?? ""}
            disabled={disabled}
            onChange={(event) =>
              update({
                num_speakers: event.target.value
                  ? Number(event.target.value)
                  : null,
              })
            }
          />
        </label>
      )}
    </div>
  );
}
