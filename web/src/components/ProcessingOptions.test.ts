import { describe, expect, it } from "vitest";
import { defaultProcessingOptions } from "./ProcessingOptions";
import type { Health } from "../lib/types";

const health = (whisper: boolean, mimo: boolean): Health => ({
  ok: true,
  read_only: false,
  backends: { qwen: false, whisper, mimo },
});

describe("defaultProcessingOptions", () => {
  it("在仅 MiMo 可用时为新表单默认选择 MiMo", () => {
    expect(defaultProcessingOptions(health(false, true))).toEqual({
      backend: "mimo",
      skip_diarization: true,
      num_speakers: null,
    });
  });

  it("Whisper 可用时仍保持默认 Whisper", () => {
    expect(defaultProcessingOptions(health(true, true)).backend).toBe(
      "whisper",
    );
  });
});
