import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MarkdownView } from "./ContentViews";

describe("MarkdownView security", () => {
  it("不执行或透传 Markdown 中的原始 HTML，并过滤危险链接协议", () => {
    const html = renderToStaticMarkup(
      <MarkdownView
        markdown={
          '# 标题\n\n<script>alert("xss")</script>\n\n[危险链接](javascript:alert(1))\n\n<img src=x onerror=alert(1)>'
        }
      />,
    );
    expect(html).toContain("标题");
    expect(html).not.toContain("<script");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("javascript:");
    expect(html).not.toContain("onerror");
  });
});
