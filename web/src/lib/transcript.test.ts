import { describe, expect, it } from "vitest";
import { parseTranscript } from "./transcript";

describe("parseTranscript", () => {
  it("解析旧版逐行时间戳与说话人标签", () => {
    expect(
      parseTranscript(
        "[00:00:03 发言人 1] 欢迎收听\n[00:00:08 发言人 2] 大家好",
      ),
    ).toEqual([
      { time: "00:00:03", speaker: "发言人 1", text: "欢迎收听" },
      { time: "00:00:08", speaker: "发言人 2", text: "大家好" },
    ]);
  });

  it("按空行保留 MiMo 的自然段", () => {
    expect(
      parseTranscript(
        "第一段没有时间戳。\n仍然属于第一段。\n\n第二段。\n\n\n第三段。",
      ),
    ).toEqual([
      {
        time: null,
        speaker: null,
        text: "第一段没有时间戳。\n仍然属于第一段。",
      },
      { time: null, speaker: null, text: "第二段。" },
      { time: null, speaker: null, text: "第三段。" },
    ]);
  });
});
