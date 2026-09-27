import { describe, expect, it } from "vitest";
import { stageLabel } from "./format";

describe("stageLabel", () => {
  it("翻译后端准备阶段名称", () => {
    expect(stageLabel("starting")).toBe("准备处理");
    expect(stageLabel("archiving")).toBe("归档上一版产物");
    expect(stageLabel("fetching")).toBe("获取节目与音频");
    expect(stageLabel("converting")).toBe("转换音频格式");
  });
});
