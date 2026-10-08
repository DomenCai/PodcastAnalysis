import {
  FileAudio,
  Link2,
  ShieldCheck,
  Sparkles,
  UploadCloud,
} from "lucide-react";
import { type FormEvent, useRef, useState } from "react";
import { api, messageOf } from "../lib/api";
import type { Health, ProcessingOptions as Options } from "../lib/types";
import { navigate } from "../lib/routing";
import {
  defaultProcessingOptions,
  ProcessingOptions,
} from "../components/ProcessingOptions";
import { ErrorState } from "../components/States";

export function NewJobPage({ health }: { health: Health }) {
  const [mode, setMode] = useState<"file" | "url">("file"),
    [file, setFile] = useState<File | null>(null),
    [url, setUrl] = useState(""),
    [options, setOptions] = useState<Options>(() =>
      defaultProcessingOptions(health),
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData();
    if (mode === "file" && file) form.set("file", file);
    if (mode === "url") form.set("url", url.trim());
    form.set("backend", options.backend);
    form.set("skip_diarization", String(options.skip_diarization));
    if (options.num_speakers != null)
      form.set("num_speakers", String(options.num_speakers));
    try {
      const result = await api.createJob(form);
      navigate(`/jobs/${result.job_id}`);
    } catch (err) {
      setError(messageOf(err, "任务创建失败"));
    } finally {
      setBusy(false);
    }
  }
  const valid = mode === "file" ? !!file : /^https?:\/\//.test(url.trim());
  return (
    <section className="narrow stack-xl">
      <header className="page-head">
        <span className="eyebrow">NEW JOB</span>
        <h1>新建转写任务</h1>
        <p>上传音频或提供小宇宙链接。源音频不会作为播放资源保留。</p>
      </header>
      <form className="panel stack-lg" onSubmit={submit}>
        <div className="segmented">
          <button
            type="button"
            className={mode === "file" ? "active" : ""}
            onClick={() => setMode("file")}
          >
            <FileAudio size={17} />
            本地音频
          </button>
          <button
            type="button"
            className={mode === "url" ? "active" : ""}
            onClick={() => setMode("url")}
          >
            <Link2 size={17} />
            小宇宙链接
          </button>
        </div>
        {mode === "file" ? (
          <>
            <input
              ref={input}
              className="visually-hidden"
              type="file"
              accept="audio/*,.m4a,.mp3,.wav,.aac,.flac,.ogg"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <button
              type="button"
              className="dropzone"
              onClick={() => input.current?.click()}
            >
              <UploadCloud size={30} />
              <strong>{file ? file.name : "选择音频文件"}</strong>
              <small>
                {file
                  ? `${(file.size / 1024 / 1024).toFixed(1)} MB`
                  : "MP3、M4A、WAV、AAC、FLAC 或 OGG"}
              </small>
            </button>
          </>
        ) : (
          <label className="field">
            <span>小宇宙单集 URL</span>
            <input
              type="url"
              required
              placeholder="https://www.xiaoyuzhoufm.com/episode/..."
              value={url}
              onChange={(event) => setUrl(event.target.value)}
            />
          </label>
        )}
        <div className="rule" />
        <div>
          <h2 className="form-title">处理方式</h2>
          <p className="form-help">当前任务独立选择，不会改变订阅默认值。</p>
        </div>
        <ProcessingOptions
          value={options}
          health={health}
          disabled={busy}
          onChange={setOptions}
        />
        <div className="pipeline-note">
          <ShieldCheck size={18} />
          <span>
            <strong>固定质量流程</strong>
            <small>
              Whisper 会强制清理错字；转写后生成文章、笔记
              和思维导图。
            </small>
          </span>
          <Sparkles size={18} />
        </div>
        {error && <ErrorState message={error} />}
        <button className="primary submit" disabled={!valid || busy}>
          {busy ? "正在提交…" : "开始处理"}
        </button>
      </form>
    </section>
  );
}
