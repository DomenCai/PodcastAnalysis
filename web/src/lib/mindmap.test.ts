import { describe, expect, it } from "vitest";
import { parseMindmap } from "./mindmap";

describe("parseMindmap", () => {
  it("把 Markdown 标题和嵌套列表转换为可折叠树", () => {
    expect(
      parseMindmap("# 核心主题\n## 第一部分\n- 观点 A\n  - 证据 A1\n- 观点 B"),
    ).toEqual([
      {
        text: "核心主题",
        children: [
          {
            text: "第一部分",
            children: [
              { text: "观点 A", children: [{ text: "证据 A1", children: [] }] },
              { text: "观点 B", children: [] },
            ],
          },
        ],
      },
    ]);
  });
});
